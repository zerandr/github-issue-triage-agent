from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def tool_names(final_state: dict[str, Any]) -> list[str]:
    names: list[str] = []

    for event in final_state.get("tool_events", []) or []:
        if isinstance(event, dict) and event.get("tool"):
            names.append(str(event["tool"]))

    for item in final_state.get("evidence", []) or []:
        if not isinstance(item, dict):
            continue

        source_tool = str(item.get("source_tool") or "")
        summary = str(item.get("summary") or "")

        if source_tool:
            names.append(source_tool)

        if source_tool == "triage_cache_get" and summary.startswith("Cache hit for "):
            cached_key = summary.removeprefix("Cache hit for ").split(":", 1)[0]

            if cached_key:
                names.append(cached_key)

    return sorted(set(names))


def expected_tools(task: dict[str, Any]) -> list[str]:
    return [
        str(item)
        for item in task.get("expected_tool_classes", task.get("expected_tools", []))
    ]


def classify_failure(trace: dict[str, Any]) -> tuple[str, str]:
    task = trace.get("task", {})
    final_state = trace.get("final_state", {})
    metrics = trace.get("metrics", {})
    stop_reason = metrics.get("stop_reason")

    expected = expected_tools(task)
    used = tool_names(final_state)
    task_type = str(task.get("task_type", ""))

    if final_state.get("__interrupt__") or stop_reason == "human_interrupt_pending":
        return (
            "Human review interrupt pending",
            (
                "The automated eval correctly reached the human-in-the-loop gate, "
                "but the interrupt was not resumed by a reviewer, so the trace ends "
                "with a pending human decision."
            ),
        )

    if metrics.get("hallucinated_tool_args", 0):
        return (
            "Hallucinated tool arguments",
            "At least one tool call failed with validation or bad-argument style errors.",
        )

    if metrics.get("unnecessary_tool_calls", 0):
        return (
            "Unnecessary extra tool calls",
            (
                "The trajectory used additional GitHub tool classes beyond the rubric's "
                f"expected set {expected}. Recorded tool classes: {used}."
            ),
        )

    if metrics.get("ungrounded_claims", 0):
        return (
            "Ungrounded final claim",
            "The final state contained claims without traceable evidence.",
        )

    if metrics.get("tool_selection_accuracy", 1.0) < 1.0:
        if task_type.startswith("adversarial"):
            return (
                "Adversarial tool-selection miss",
                (
                    "The adversarial task expected defensive evidence gathering with "
                    f"{expected}, but the trajectory recorded {used or 'no tool events'}."
                ),
            )

        return (
            "Expected tool class was not observed",
            (
                "The task rubric expected "
                f"{expected}, but the trajectory recorded {used or 'no tool events'}."
            ),
        )

    if task_type == "adversarial_nonexistent_repo" and stop_reason not in {
        "completed",
        None,
        "None",
    }:
        return (
            "Deleted or nonexistent repository path",
            (
                "The agent correctly avoided fabrication, but the trajectory ends "
                "as a non-completion 404 path instead of a user-friendly completed refusal."
            ),
        )

    if task_type == "adversarial_nonexistent_issue" and stop_reason not in {
        "completed",
        None,
        "None",
    }:
        return (
            "Nonexistent issue path",
            (
                "The agent correctly avoided fabrication, but the trajectory ends "
                "as a non-completion 404 path instead of a normal completed not-found report."
            ),
        )

    if stop_reason not in {"completed", None, "None"}:
        return (
            "Non-completion stop reason",
            f"The trajectory stopped with `{stop_reason}` instead of a normal completion.",
        )

    if metrics.get("score_3pt", 3) < 3:
        return (
            "Partial-quality trajectory",
            "The rule-based eval assigned a score below 3 despite normal completion.",
        )

    return (
        "Residual risk",
        "This trace is included for manual review because it ranks among the weakest runs.",
    )


def short_error(final_state: dict[str, Any]) -> str:
    fatal = str(final_state.get("fatal_error") or "").strip()

    if fatal:
        return fatal[:500]

    for event in final_state.get("tool_events", []) or []:
        if isinstance(event, dict) and event.get("error"):
            return str(event["error"])[:500]

    return ""


def summarize_trace(path: Path) -> dict[str, Any]:
    trace = read_json(path)
    task = trace.get("task", {})
    final_state = trace.get("final_state", {})
    metrics = trace.get("metrics", {})
    mode, explanation = classify_failure(trace)

    return {
        "task_id": trace.get("task_id"),
        "file": str(path),
        "repo": task.get("repo"),
        "issue_number": task.get("issue_number"),
        "task_type": task.get("task_type"),
        "failure_mode": mode,
        "explanation": explanation,
        "expected_tools": expected_tools(task),
        "used_tools": tool_names(final_state),
        "metrics": metrics,
        "classification": final_state.get("classification"),
        "stop_reason": metrics.get("stop_reason"),
        "error": short_error(final_state),
        "evidence": final_state.get("evidence", [])[:5],
        "related_issues_count": len(final_state.get("related_issues", []) or []),
    }


def rank_key(item: dict[str, Any]) -> tuple[float, float, int, float]:
    metrics = item.get("metrics", {})
    score = float(metrics.get("score_3pt", 3) or 3)
    tool_accuracy = float(metrics.get("tool_selection_accuracy", 1) or 0)
    abnormal_stop = 0 if item.get("stop_reason") in {"completed", None, "None"} else -1
    latency = float(metrics.get("latency_seconds", 0) or 0)

    return (score, tool_accuracy, abnormal_stop, -latency)


def select_failures(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    candidates = [
        item
        for item in items
        if item["metrics"].get("score_3pt", 3) < 3
        or item["metrics"].get("tool_selection_accuracy", 1.0) < 1.0
        or item.get("stop_reason") not in {"completed", None, "None"}
        or item.get("classification") == "unknown"
        or item["metrics"].get("ungrounded_claims", 0)
        or item["metrics"].get("hallucinated_tool_args", 0)
        or item["metrics"].get("unnecessary_tool_calls", 0)
    ]

    selected: list[dict[str, Any]] = []
    seen_modes: set[str] = set()

    for item in sorted(candidates, key=rank_key):
        if item["failure_mode"] in seen_modes:
            continue
        selected.append(item)
        seen_modes.add(item["failure_mode"])

        if len(selected) >= limit:
            return selected

    for item in sorted(candidates, key=rank_key):
        if item in selected:
            continue
        selected.append(item)

        if len(selected) >= limit:
            return selected

    if len(selected) >= limit:
        return selected

    for item in sorted(items, key=rank_key):
        if item in selected:
            continue

        residual = dict(item)
        residual["failure_mode"] = "Residual trajectory risk"
        residual["explanation"] = (
            "This trajectory did not fail the rule-based rubric, but is included "
            "to provide the requested third annotated trace and document residual risk."
        )
        selected.append(residual)

        if len(selected) >= limit:
            return selected

    return selected


def render_markdown(items: list[dict[str, Any]]) -> str:
    lines = [
        "# Annotated Failure Traces",
        "",
        "These traces were selected from machine-readable trajectory JSON files.",
        "",
    ]

    for index, item in enumerate(items, start=1):
        metrics = item["metrics"]
        lines.extend(
            [
                f"## {index}. {item['task_id']} - {item['failure_mode']}",
                "",
                f"- Source: `{item['file']}`",
                f"- Task: `{item['task_type']}` for `{item['repo']}#{item['issue_number']}`",
                f"- Score: `{metrics.get('score_3pt')}`",
                f"- Tool-selection accuracy: `{metrics.get('tool_selection_accuracy')}`",
                f"- Unnecessary tool calls: `{metrics.get('unnecessary_tool_calls')}`",
                f"- Stop reason: `{item.get('stop_reason')}`",
                f"- Expected tools: `{item.get('expected_tools')}`",
                f"- Used tools: `{item.get('used_tools')}`",
                "",
                "### What happened",
                item["explanation"],
                "",
                "### Evidence and symptoms",
            ]
        )

        if item.get("error"):
            lines.append(f"- Error: `{item['error']}`")

        lines.append(f"- Final classification: `{item.get('classification')}`")
        lines.append(f"- Evidence count shown: `{len(item.get('evidence', []))}`")
        lines.append(f"- Related issues found: `{item.get('related_issues_count')}`")
        lines.extend(["", "### Suggested fix", suggested_fix(item), ""])

    return "\n".join(lines)


def suggested_fix(item: dict[str, Any]) -> str:
    mode = item["failure_mode"]

    if mode == "Expected tool class was not observed":
        return (
            "Improve tool event accounting for cache hits or require live verification "
            "for tasks whose rubric expects a specific tool class."
        )

    if mode == "Unnecessary extra tool calls":
        return (
            "Route task-specific workflows more tightly so simple classification tasks "
            "can stop after issue retrieval unless duplicate or stale-state evidence is needed."
        )

    if mode == "Non-completion stop reason":
        return (
            "Treat GitHub rate-limit responses as retriable when the response body "
            "indicates rate limiting, and prefer authenticated requests during eval."
        )

    if mode == "Deleted or nonexistent repository path":
        return (
            "Map repository-level 404s into a completed refusal artifact with explicit "
            "`repo_not_found` wording, while keeping the raw tool error in the trace."
        )

    if mode == "Nonexistent issue path":
        return (
            "Map issue-level 404s into a completed not-found triage report instead of "
            "using the same terminal state as unexpected tool failures."
        )

    if mode == "Human review interrupt pending":
        return (
            "During live demo, resume the interrupt with a reviewer classification; "
            "for automated eval, keep this explicit terminal state instead of an "
            "implicit missing stop reason."
        )

    if mode == "Hallucinated tool arguments":
        return "Tighten tool argument schema validation before tool dispatch."

    if mode == "Ungrounded final claim":
        return "Add a final grounding validator that maps each final claim to evidence ids."

    return "Inspect the trajectory and add a targeted regression task for this failure mode."


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract annotated failure traces.")
    parser.add_argument("--trajectories", default="runs/main/trajectories")
    parser.add_argument("--out-json", default="reports/failure_traces.json")
    parser.add_argument("--out-md", default="reports/failure_traces.md")
    parser.add_argument("--limit", type=int, default=3)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    trajectory_dir = Path(args.trajectories)
    items = [summarize_trace(path) for path in sorted(trajectory_dir.glob("*.json"))]
    selected = select_failures(items, args.limit)

    payload = {
        "source": str(trajectory_dir),
        "selected": selected,
        "n_selected": len(selected),
    }

    write_json(Path(args.out_json), payload)
    write_text(Path(args.out_md), render_markdown(selected))
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
