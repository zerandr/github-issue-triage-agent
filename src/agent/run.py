from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from langgraph.types import Command

from src.agent.graph import Graph
from src.agent.state import TriageState


ALLOWED_CLASSIFICATIONS = {
    "bug",
    "feature request",
    "question",
    "documentation",
    "duplicate",
    "unknown",
}


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


def _read_human_classification(interrupt_payload: Any) -> dict[str, str]:
    display_payload = interrupt_payload

    if isinstance(interrupt_payload, list) and interrupt_payload:
        first = interrupt_payload[0]
        display_payload = getattr(first, "value", first)

    print("\n[human-in-the-loop] Review requested.", file=sys.stderr)
    print(
        json.dumps(make_json_safe(display_payload), ensure_ascii=False, indent=2),
        file=sys.stderr,
    )
    print(
        "Enter classification "
        "(bug | feature request | question | documentation | duplicate | unknown): ",
        end="",
        file=sys.stderr,
        flush=True,
    )

    answer = input().strip().lower()

    if answer not in ALLOWED_CLASSIFICATIONS:
        answer = "unknown"

    return {"classification": answer}


def run(
    repo: str, issue_number: int, interactive_human: bool = False
) -> dict[str, Any]:
    compiled_graph = Graph().build_graph()
    config = {
        "configurable": {
            "thread_id": f"{repo}#{issue_number}",
        }
    }

    state = TriageState(
        repo=repo,
        issue_number=issue_number,
    )

    result = compiled_graph.invoke(state, config=config)

    if interactive_human and isinstance(result, dict) and result.get("__interrupt__"):
        decision = _read_human_classification(result["__interrupt__"])
        result = compiled_graph.invoke(Command(resume=decision), config=config)

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
    parser.add_argument(
        "--interactive-human",
        action="store_true",
        default=True,
        help="Resume LangGraph human-in-the-loop interrupts from terminal input.",
    )
    parser.add_argument(
        "--no-interactive-human",
        action="store_false",
        dest="interactive_human",
        help="Return pending interrupts instead of asking for terminal input.",
    )

    args = parser.parse_args()

    result = run(args.repo, args.issue, interactive_human=bool(args.interactive_human))

    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
