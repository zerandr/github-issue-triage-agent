from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AblationVariant:
    name: str
    description: str
    env: dict[str, str] = field(default_factory=dict)


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


def build_variants(args: argparse.Namespace) -> list[AblationVariant]:
    return [
        AblationVariant(
            name="baseline",
            description="Baseline graph, strict grounding prompt, primary model.",
            env={
                "OLLAMA_MODEL": args.primary_model,
                "TRIAGE_PROMPT_VARIANT": "strict",
                "TRIAGE_GRAPH_VARIANT": "baseline",
            },
        ),
        AblationVariant(
            name="model_secondary",
            description="Same graph and prompt, secondary model.",
            env={
                "OLLAMA_MODEL": args.secondary_model,
                "TRIAGE_PROMPT_VARIANT": "strict",
                "TRIAGE_GRAPH_VARIANT": "baseline",
            },
        ),
        AblationVariant(
            name="prompt_permissive",
            description="Same graph and model, materially weaker prompt/tool discipline.",
            env={
                "OLLAMA_MODEL": args.primary_model,
                "TRIAGE_PROMPT_VARIANT": "permissive",
                "TRIAGE_GRAPH_VARIANT": "baseline",
            },
        ),
        AblationVariant(
            name="graph_no_human_gate",
            description="Same model and prompt, but ambiguous cases bypass HITL routing.",
            env={
                "OLLAMA_MODEL": args.primary_model,
                "TRIAGE_PROMPT_VARIANT": "strict",
                "TRIAGE_GRAPH_VARIANT": "no_human_gate",
            },
        ),
    ]


def run_variant(
    variant: AblationVariant,
    args: argparse.Namespace,
) -> dict[str, Any]:
    out_dir = Path(args.out) / variant.name
    summary_path = Path(args.report_dir) / f"{variant.name}_summary.json"

    command = [
        sys.executable,
        "-m",
        "src.eval.run_eval",
        "--tasks",
        args.tasks,
        "--out",
        str(out_dir),
        "--summary",
        str(summary_path),
    ]

    if args.limit is not None:
        command.extend(["--limit", str(args.limit)])

    env = os.environ.copy()
    env.update(variant.env)

    print(f"Running ablation `{variant.name}`...")
    completed = subprocess.run(
        command,
        cwd=args.repo_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    result: dict[str, Any] = {
        "name": variant.name,
        "description": variant.description,
        "env": variant.env,
        "out_dir": str(out_dir),
        "summary_path": str(summary_path),
        "returncode": completed.returncode,
        "stdout_tail": completed.stdout[-4000:],
        "stderr_tail": completed.stderr[-4000:],
    }

    if summary_path.exists():
        result["summary"] = read_json(summary_path)

    if completed.returncode != 0 and args.required:
        raise RuntimeError(
            f"Ablation `{variant.name}` failed with exit code {completed.returncode}"
        )

    return result


def comparison_rows(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for result in results:
        summary = result.get("summary", {})
        rows.append(
            {
                "variant": result["name"],
                "status": "ok" if result["returncode"] == 0 else "failed",
                "n_tasks": summary.get("n_tasks"),
                "mean_score_3pt": summary.get("mean_score_3pt"),
                "tool_selection_accuracy": summary.get("tool_selection_accuracy"),
                "mean_steps": summary.get("mean_steps"),
                "mean_tool_calls": summary.get("mean_tool_calls"),
                "mean_latency_seconds": summary.get("mean_latency_seconds"),
                "total_tokens": summary.get("total_tokens"),
                "total_estimated_usd_cost": summary.get("total_estimated_usd_cost"),
                "total_ungrounded_claims": summary.get("total_ungrounded_claims"),
                "total_hallucinated_tool_args": summary.get(
                    "total_hallucinated_tool_args"
                ),
                "total_unnecessary_tool_calls": summary.get(
                    "total_unnecessary_tool_calls"
                ),
            }
        )

    return rows


def render_markdown(results: list[dict[str, Any]]) -> str:
    rows = comparison_rows(results)
    headers = [
        "variant",
        "status",
        "n_tasks",
        "mean_score_3pt",
        "tool_selection_accuracy",
        "mean_steps",
        "mean_tool_calls",
        "mean_latency_seconds",
        "total_tokens",
        "total_estimated_usd_cost",
        "total_ungrounded_claims",
        "total_hallucinated_tool_args",
        "total_unnecessary_tool_calls",
    ]

    lines = [
        "# Ablation Study",
        "",
        "All variants use the same evaluation set. Each row is generated from the JSON summary written by `src.eval.run_eval`.",
        "",
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]

    for row in rows:
        lines.append(
            "| " + " | ".join(str(row.get(header, "")) for header in headers) + " |"
        )

    lines.extend(["", "## Variants", ""])

    for result in results:
        lines.append(f"### {result['name']}")
        lines.append(result["description"])
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(result["env"], ensure_ascii=False, indent=2))
        lines.append("```")
        lines.append("")

    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run required ablation experiments.")
    parser.add_argument("--tasks", default="data/eval_tasks.jsonl")
    parser.add_argument("--out", default="runs/ablations")
    parser.add_argument("--report-dir", default="reports/ablations")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument(
        "--primary-model", default=os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct")
    )
    parser.add_argument("--secondary-model", default="llama3:latest")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--required", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    variants = build_variants(args)
    results = [run_variant(variant, args) for variant in variants]

    payload = {
        "variants": results,
        "comparison": comparison_rows(results),
    }

    report_dir = Path(args.report_dir)
    write_json(report_dir / "ablation_results.json", payload)
    write_text(report_dir / "ablation_study.md", render_markdown(results))

    print(json.dumps(payload["comparison"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
