from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from src.agent.graph import build_graph
from src.agent.state import TriageState


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump()
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    return value


def _score_run(out: dict) -> int:
    if (
        out.get("classification") != "unknown"
        and out.get("evidence_ids")
        and out.get("justification")
    ):
        return 3
    if out.get("classification") != "unknown":
        return 2
    return 1


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--tasks", required=True)
    p.add_argument("--model", required=True)
    args = p.parse_args()

    tasks = [
        json.loads(x)
        for x in Path(args.tasks).read_text(encoding="utf-8").splitlines()
        if x.strip()
    ]

    out_dir = Path("reports/trajectories")
    out_dir.mkdir(parents=True, exist_ok=True)

    app = build_graph()
    summary = {"model": args.model, "n_tasks": len(tasks), "runs": []}

    for t in tasks:
        repo = t.get("repo")
        issue_number = int(t.get("issue_number", 0))

        t0 = time.time()
        terminal_state: dict[str, Any] = {}
        error = ""
        try:
            init = TriageState(repo=repo, issue_number=issue_number)
            terminal_state = _jsonable(
                app.invoke(
                    init, config={"configurable": {"thread_id": f"eval:{t['task_id']}"}}
                )
            )
        except Exception as e:
            error = str(e)

        latency = round(time.time() - t0, 3)
        score = _score_run(terminal_state) if terminal_state else 1

        run = {
            "task_id": t["task_id"],
            "task_type": t.get("task_type", "unknown"),
            "latency_sec": latency,
            "score_3pt": score,
            "tool_selection_ok": bool(terminal_state.get("tool_events")),
            "n_tool_calls": terminal_state.get("tool_calls", 0),
            "n_steps": terminal_state.get("step_count", 0),
            "hallucinated_tool_args": 0,
            "unnecessary_tool_calls": 0,
            "ungrounded_claims": 0 if terminal_state.get("evidence_ids") else 1,
            "stop_reason": terminal_state.get("stop_reason", "exception"),
            "error": error,
        }
        summary["runs"].append(run)

        (out_dir / f"{t['task_id']}.json").write_text(
            json.dumps(
                {
                    "task": t,
                    "run": run,
                    "terminal_state": terminal_state,
                    "timestamp_unix": int(time.time()),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    Path("reports/eval_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("Wrote reports/eval_summary.json and reports/trajectories/*.json")


if __name__ == "__main__":
    main()
