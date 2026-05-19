from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from src.agent.graph import Graph
from src.agent.state import TriageState
from src.eval.git_mcp_autocommit import commit_json_artifacts


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []

    if not path.exists():
        raise FileNotFoundError(f"Tasks file not found: {path}")

    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            line = line.strip()

            if not line:
                continue

            try:
                tasks.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_number}") from exc

    return tasks


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)


def make_json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, (list, tuple)):
        return [make_json_safe(item) for item in value]

    if isinstance(value, dict):
        return {str(key): make_json_safe(item) for key, item in value.items()}

    if hasattr(value, "model_dump"):
        return make_json_safe(value.model_dump())

    if hasattr(value, "dict"):
        return make_json_safe(value.dict())

    if hasattr(value, "__dict__"):
        return make_json_safe(vars(value))

    return str(value)


def state_to_dict(state: Any) -> dict[str, Any]:
    converted = make_json_safe(state)

    if isinstance(converted, dict):
        return converted

    return {"value": converted}


def build_initial_state(task: dict[str, Any]) -> TriageState:
    return TriageState(
        repo=str(task.get("repo", "")),
        issue_number=int(task.get("issue_number", 0)),
    )


def extract_tool_names(final_state: dict[str, Any]) -> list[str]:
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

    calls = final_state.get("tool_calls", [])

    if isinstance(calls, list):
        for call in calls:
            if isinstance(call, dict) and (call.get("tool") or call.get("name")):
                names.append(str(call.get("tool") or call.get("name")))
            elif isinstance(call, str):
                names.append(call)

    return names


def score_task(task: dict[str, Any], final_state: dict[str, Any]) -> int:
    task_type = str(task.get("task_type", ""))
    fatal_error = str(final_state.get("fatal_error", ""))
    stop_reason = str(final_state.get("stop_reason", ""))

    evidence = final_state.get("evidence", [])
    evidence_count = len(evidence) if isinstance(evidence, list) else 0

    if fatal_error:
        if task_type.startswith("adversarial") or "nonexistent" in task_type:
            return 3

        return 1

    if stop_reason not in {"completed", "", "None", "null"}:
        return 2

    if evidence_count <= 0:
        return 1

    expected = [
        str(item)
        for item in task.get(
            "expected_tool_classes",
            task.get("expected_tools", []),
        )
    ]

    used = extract_tool_names(final_state)

    if expected and not any(exp in got for exp in expected for got in used):
        return 2

    return 3


def tool_selection_accuracy(
    task: dict[str, Any],
    final_state: dict[str, Any],
) -> float:
    expected = [
        str(item)
        for item in task.get(
            "expected_tool_classes",
            task.get("expected_tools", []),
        )
    ]

    if not expected:
        return 1.0

    used = extract_tool_names(final_state)

    if not used:
        return 0.0

    matched = sum(1 for exp in expected if any(exp in got for got in used))

    return matched / len(expected)


def count_ungrounded_claims(final_state: dict[str, Any]) -> int:
    evidence = final_state.get("evidence", [])

    if isinstance(evidence, list) and len(evidence) > 0:
        return 0

    claim_keys = [
        "classification",
        "justification",
        "probable_code_areas",
        "related_issues",
        "current_state_summary",
    ]

    return 1 if any(final_state.get(key) for key in claim_keys) else 0


def count_hallucinated_tool_args(final_state: dict[str, Any]) -> int:
    count = 0

    for event in final_state.get("tool_events", []) or []:
        if not isinstance(event, dict):
            continue

        status = int(event.get("status", 0) or 0)
        error = str(event.get("error", "")).lower()

        if status == 400 or "validation" in error or "bad argument" in error:
            count += 1

    return count


def terminal_state(final_state: dict[str, Any]) -> str:
    stop_reason = final_state.get("stop_reason")

    if stop_reason in {None, "", "None", "null"} and final_state.get("__interrupt__"):
        return "human_interrupt_pending"

    if stop_reason in {None, ""}:
        return "unknown"

    return str(stop_reason)


def count_unnecessary_tool_calls(
    task: dict[str, Any],
    final_state: dict[str, Any],
) -> int:
    expected = {
        str(item)
        for item in task.get(
            "expected_tool_classes",
            task.get("expected_tools", []),
        )
    }

    observed = {
        name for name in extract_tool_names(final_state) if name.startswith("github_")
    }

    return sum(1 for name in observed if name not in expected)


def run_one_task(
    compiled_graph: Any,
    task: dict[str, Any],
    trajectory_dir: Path,
) -> dict[str, Any]:
    task_id = str(task.get("task_id", f"task_{int(time.time())}"))

    initial_state = build_initial_state(task)
    started = time.time()

    config = {
        "configurable": {
            "thread_id": task_id,
        }
    }

    try:
        final_state_raw = compiled_graph.invoke(initial_state, config=config)
        error = None
    except Exception as exc:
        final_state_raw = initial_state
        error = str(exc)

    final_state = state_to_dict(final_state_raw)

    if error:
        final_state["fatal_error"] = error
        final_state["stop_reason"] = "eval_exception"

    latency = round(time.time() - started, 3)

    tool_calls_raw = final_state.get("tool_calls", 0)

    if isinstance(tool_calls_raw, int):
        tool_calls_count = tool_calls_raw
    elif isinstance(tool_calls_raw, list):
        tool_calls_count = len(tool_calls_raw)
    else:
        tool_calls_count = 0

    metrics = {
        "score_3pt": score_task(task, final_state),
        "tool_selection_accuracy": tool_selection_accuracy(task, final_state),
        "steps": int(final_state.get("step_count", 0) or 0),
        "tool_calls": tool_calls_count,
        "latency_seconds": latency,
        "token_count": int(final_state.get("token_count", 0) or 0),
        "estimated_usd_cost": 0.0,
        "ungrounded_claims": count_ungrounded_claims(final_state),
        "hallucinated_tool_args": count_hallucinated_tool_args(final_state),
        "unnecessary_tool_calls": count_unnecessary_tool_calls(task, final_state),
        "stop_reason": terminal_state(final_state),
    }

    trajectory = {
        "task_id": task_id,
        "task": task,
        "trajectory_events": final_state.get("trajectory_events", []),
        "final_state": final_state,
        "metrics": metrics,
    }

    write_json(trajectory_dir / f"{task_id}.json", trajectory)

    return trajectory


def aggregate_results(trajectories: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(trajectories)

    if n == 0:
        return {"n_tasks": 0}

    metrics = [trajectory["metrics"] for trajectory in trajectories]

    def mean(key: str) -> float:
        return round(
            sum(float(item.get(key, 0) or 0) for item in metrics) / n,
            3,
        )

    score_counts: dict[str, int] = {}
    stop_reasons: dict[str, int] = {}

    for item in metrics:
        score = str(item.get("score_3pt", 0))
        score_counts[score] = score_counts.get(score, 0) + 1

        reason = str(item.get("stop_reason", "unknown"))
        stop_reasons[reason] = stop_reasons.get(reason, 0) + 1

    return {
        "n_tasks": n,
        "mean_score_3pt": mean("score_3pt"),
        "score_counts": score_counts,
        "tool_selection_accuracy": mean("tool_selection_accuracy"),
        "mean_steps": mean("steps"),
        "mean_tool_calls": mean("tool_calls"),
        "mean_latency_seconds": mean("latency_seconds"),
        "total_tokens": int(
            sum(int(item.get("token_count", 0) or 0) for item in metrics)
        ),
        "total_estimated_usd_cost": round(
            sum(float(item.get("estimated_usd_cost", 0) or 0) for item in metrics),
            6,
        ),
        "total_ungrounded_claims": int(
            sum(int(item.get("ungrounded_claims", 0) or 0) for item in metrics)
        ),
        "total_hallucinated_tool_args": int(
            sum(int(item.get("hallucinated_tool_args", 0) or 0) for item in metrics)
        ),
        "total_unnecessary_tool_calls": int(
            sum(int(item.get("unnecessary_tool_calls", 0) or 0) for item in metrics)
        ),
        "stop_reasons": stop_reasons,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run GitHub issue triage evaluation.")

    parser.add_argument(
        "--tasks",
        default="data/eval_tasks.jsonl",
        help="Path to JSONL evaluation tasks.",
    )

    parser.add_argument(
        "--out",
        default="runs/main",
        help="Output directory.",
    )

    parser.add_argument(
        "--summary",
        default="reports/eval_summary.json",
        help="Path to aggregate summary JSON.",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional task limit for quick checks.",
    )

    parser.add_argument(
        "--git-mcp-autocommit",
        action="store_true",
        help="Commit JSON eval artifacts through a third-party Git MCP server.",
    )

    parser.add_argument(
        "--git-mcp-push",
        action="store_true",
        help="Push the Git MCP commit to the configured remote.",
    )

    parser.add_argument(
        "--git-mcp-required",
        action="store_true",
        help="Fail evaluation if Git MCP auto-commit/push fails.",
    )

    parser.add_argument(
        "--git-mcp-dir",
        default=None,
        help="Directory of JSON artifacts to commit. Defaults to the eval output directory.",
    )

    parser.add_argument(
        "--git-mcp-message",
        default="Auto-commit eval JSON artifacts",
        help="Commit message used by Git MCP.",
    )

    parser.add_argument(
        "--git-mcp-remote",
        default="origin",
        help="Remote used by Git MCP push.",
    )

    parser.add_argument(
        "--git-mcp-branch",
        default=None,
        help="Branch used by Git MCP push. Defaults to the server/git current branch.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    tasks = read_jsonl(Path(args.tasks))

    if args.limit is not None:
        tasks = tasks[: args.limit]

    compiled_graph = Graph().build_graph()

    trajectory_dir = Path(args.out) / "trajectories"
    trajectories: list[dict[str, Any]] = []

    for index, task in enumerate(tasks, start=1):
        task_id = task.get("task_id", f"task_{index}")

        print(f"[{index}/{len(tasks)}] Running {task_id}...")

        trajectory = run_one_task(
            compiled_graph=compiled_graph,
            task=task,
            trajectory_dir=trajectory_dir,
        )

        trajectories.append(trajectory)

        print(
            f"  score={trajectory['metrics']['score_3pt']} "
            f"latency={trajectory['metrics']['latency_seconds']}s"
        )

    summary = aggregate_results(trajectories)

    write_json(Path(args.summary), summary)
    write_json(Path(args.out) / "summary.json", summary)

    if args.git_mcp_autocommit:
        summary["git_mcp_autocommit"] = {
            "requested": True,
            "push": bool(args.git_mcp_push),
            "artifact_dir": str(Path(args.git_mcp_dir or args.out)),
        }
        write_json(Path(args.summary), summary)
        write_json(Path(args.out) / "summary.json", summary)

        artifact_dir = Path(args.git_mcp_dir or args.out)

        try:
            git_result = commit_json_artifacts(
                artifact_dir,
                repo_root=Path("."),
                message=args.git_mcp_message,
                push=args.git_mcp_push,
                remote=args.git_mcp_remote,
                branch=args.git_mcp_branch,
            )
        except Exception as exc:
            git_result = {
                "ok": False,
                "error": str(exc),
            }

        print(
            json.dumps(
                {"git_mcp_autocommit_result": git_result}, ensure_ascii=False, indent=2
            )
        )

        if not git_result.get("ok") and args.git_mcp_required:
            raise RuntimeError(f"Git MCP auto-commit failed: {git_result}")

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
