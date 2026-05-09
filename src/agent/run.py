import json
import argparse

from typing import Any
from pydantic import BaseModel

from src.agent.graph import Graph
from src.agent.state import TriageState


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump()
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--issue", required=True, type=int)
    args = parser.parse_args()

    graph = Graph()
    app = graph.build_graph()
    init = TriageState(repo=args.repo, issue_number=args.issue)
    out = app.invoke(
        init, config={"configurable": {"thread_id": f"{args.repo}#{args.issue}"}}
    )
    out = _jsonable(out)

    report = {
        "repo": out["repo"],
        "issue_number": out["issue_number"],
        "classification": out["classification"],
        "justification": out["justification"],
        "related_issues": [
            {
                "number": x.get("number"),
                "title": x.get("title"),
                "url": x.get("html_url"),
            }
            for x in out["related_issues"]
        ],
        "probable_code_areas": out["probable_code_areas"],
        "current_state_summary": out["current_state_summary"],
        "open_questions": out["open_questions"],
        "decision_needed": out["decision_needed"],
        "evidence_ids": out["evidence_ids"],
        "stop_reason": out["stop_reason"],
        "tool_events": out["tool_events"],
    }

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
