from __future__ import annotations

import argparse
from .graph import build_graph
from .state import TriageState


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--issue", required=True, type=int)
    args = parser.parse_args()

    app = build_graph()
    init = TriageState(repo=args.repo, issue_number=args.issue)
    out = app.invoke(init, config={"configurable": {"thread_id": f"{args.repo}#{args.issue}"}})

    print("=== TRIAGE REPORT ===")
    print(f"repo: {out['repo']}")
    print(f"issue: {out['issue_number']}")
    print(f"classification: {out['classification']}")
    print(f"justification: {out['justification']}")
    print(f"stop_reason: {out['stop_reason']}")


if __name__ == "__main__":
    main()
