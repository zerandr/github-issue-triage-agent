from __future__ import annotations

import argparse
import json
import time
from pathlib import Path


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--tasks", required=True)
    p.add_argument("--model", required=True)
    args = p.parse_args()

    tasks = [
        json.loads(x) for x in Path(args.tasks).read_text().splitlines() if x.strip()
    ]

    out_dir = Path("reports/trajectories")
    out_dir.mkdir(parents=True, exist_ok=True)

    summary = {"model": args.model, "n_tasks": len(tasks), "runs": []}
    for t in tasks:
        t0 = time.time()
        # Placeholder: wire to actual graph invocation + grading
        run = {
            "task_id": t["task_id"],
            "latency_sec": round(time.time() - t0, 3),
            "score_3pt": 1,
            "tool_selection_ok": False,
            "unnecessary_tool_calls": 0,
            "hallucinated_tool_args": 0,
            "ungrounded_claims": 0,
        }
        summary["runs"].append(run)

    Path("reports/eval_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2)
    )
    print("Wrote reports/eval_summary.json")


if __name__ == "__main__":
    main()
