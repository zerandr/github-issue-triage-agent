import json
import time
import argparse

from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from src.agent.graph import Graph
from src.agent.state import TriageState


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    return (
        {"type": "interrupt", "repr": str(value)}
        if value.__class__.__name__ == "Interrupt"
        else value
    )


def _score_run(out: dict[str, Any]) -> int:
    if (
        out.get("classification") != "unknown"
        and out.get("evidence_ids")
        and out.get("justification")
    ):
        return 3
    return 2 if out.get("classification") != "unknown" else 1


class EvalRunner:
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self.app = Graph().build_graph()

    def run_single(
        self, repo: str, issue_number: int, thread_id: str
    ) -> dict[str, Any]:
        return _jsonable(
            self.app.invoke(
                TriageState(repo=repo, issue_number=issue_number),
                config={"configurable": {"thread_id": thread_id}},
            )
        )

    def evaluate(self, tasks: list[dict[str, Any]]) -> dict[str, Any]:
        out_dir = Path("reports/trajectories")
        out_dir.mkdir(parents=True, exist_ok=True)
        summary: dict[str, Any] = {
            "model": self.model_name,
            "n_tasks": len(tasks),
            "runs": [],
        }

        for task in tasks:
            t0, out, error = time.time(), {}, ""
            try:
                out = self.run_single(
                    task.get("repo", ""),
                    int(task.get("issue_number", 0)),
                    f"eval:{task['task_id']}",
                )
            except Exception as exc:
                error = str(exc)
                print(exc)

            expected = set(str(x) for x in task.get("expected_tool_classes", []))
            events = out.get("tool_events", [])
            called = [str(x.get("tool", "")) for x in events]
            run = {
                "task_id": task["task_id"],
                "task_type": task.get("task_type", "unknown"),
                "latency_sec": round(time.time() - t0, 3),
                "score_3pt": _score_run(out) if out else 1,
                "tool_selection_ok": expected.issubset(set(called))
                if expected
                else True,
                "n_steps": out.get("step_count", 0),
                "n_tool_calls": out.get("tool_calls", 0),
                "unnecessary_tool_calls": sum(
                    1 for t in called if expected and t not in expected
                ),
                "hallucinated_tool_args": sum(
                    1 for x in events if int(x.get("status", 0) or 0) == 400
                ),
                "ungrounded_claims": 0 if out.get("evidence_ids") else 1,
                "stop_reason": out.get("stop_reason", "exception"),
                "error": error,
            }
            summary["runs"].append(run)

            trajectory = {
                "task": {
                    "task_id": task.get("task_id"),
                    "repo": task.get("repo"),
                    "issue_number": task.get("issue_number"),
                    "task_type": task.get("task_type", "unknown"),
                },
                "run": run,
                "terminal_state": {
                    "classification": out.get("classification", "unknown"),
                    "justification": out.get("justification", ""),
                    "probable_code_areas": out.get("probable_code_areas", []),
                    "related_issues": [
                        {
                            "number": i.get("number"),
                            "title": i.get("title"),
                            "url": i.get("html_url"),
                        }
                        for i in out.get("related_issues", [])
                    ],
                    "evidence_ids": out.get("evidence_ids", []),
                    "tool_events": events,
                    "step_count": out.get("step_count", 0),
                    "tool_calls": out.get("tool_calls", 0),
                    "token_count": out.get("token_count", 0),
                    "stop_reason": out.get("stop_reason"),
                    "fatal_error": out.get("fatal_error", ""),
                },
                "timestamp_unix": int(time.time()),
            }
            (out_dir / f"{task['task_id']}.json").write_text(
                json.dumps(trajectory, ensure_ascii=False, indent=2), encoding="utf-8"
            )

        Path("reports/eval_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return summary


def load_tasks(path: str) -> list[dict[str, Any]]:
    return [
        json.loads(x)
        for x in Path(path).read_text(encoding="utf-8").splitlines()
        if x.strip()
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--model", required=True)
    args = parser.parse_args()
    EvalRunner(model_name=args.model).evaluate(load_tasks(args.tasks))


if __name__ == "__main__":
    main()
