from __future__ import annotations

import argparse
import json
from typing import Any

from src.agent.graph import Graph
from src.agent.state import TriageState


def make_json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, list):
        return [make_json_safe(item) for item in value]

    if isinstance(value, tuple):
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


def run(repo: str, issue_number: int) -> dict[str, Any]:
    compiled_graph = Graph().build_graph()

    state = TriageState(
        repo=repo,
        issue_number=issue_number,
    )

    result = compiled_graph.invoke(
        state,
        config={
            "configurable": {
                "thread_id": f"{repo}#{issue_number}",
            }
        },
    )

    converted = make_json_safe(result)

    if isinstance(converted, dict):
        return converted

    return {"result": converted}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one GitHub issue triage.")
    parser.add_argument(
        "--repo",
        required=True,
        help="Repository in owner/name format, e.g. pandas-dev/pandas",
    )
    parser.add_argument(
        "--issue",
        required=True,
        type=int,
        help="GitHub issue number",
    )

    args = parser.parse_args()

    result = run(args.repo, args.issue)

    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
