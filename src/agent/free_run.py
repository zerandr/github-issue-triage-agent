from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from typing import Any

from src.agent.llm import OllamaLLM
from src.agent.mcp_client import github_search_related_issues


REPO_RE = re.compile(r"\b([\w.-]+/[\w.-]+)\b")


@dataclass
class FreeInputPlan:
    mode: str
    raw_input: str
    repo: str | None = None
    issue_number: int | None = None
    query: str = ""
    limit: int = 5
    sort: str | None = None
    order: str = "desc"
    reason: str = ""
    router: str = "rules"


AVAILABLE_AGENT_TOOLS = [
    {
        "tool": "run_issue_triage",
        "description": "Use when the user asks about one concrete GitHub issue.",
        "arguments": {
            "repo": "owner/name",
            "issue_number": 123,
        },
    },
    {
        "tool": "github_search_related_issues",
        "description": (
            "Use when the user asks to find/list/search GitHub issues in a repo."
        ),
        "arguments": {
            "repo": "owner/name",
            "query": "search terms",
            "limit": 5,
            "sort": "created | updated | comments | null",
            "order": "desc | asc",
        },
    },
    {
        "tool": "unable_to_answer",
        "description": "Use when no supported repository or GitHub task is present.",
        "arguments": {
            "reason": "short explanation",
        },
    },
]


def _normalize_tool_payload(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload

    if isinstance(payload, str):
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError:
            return {
                "ok": False,
                "error": payload,
            }

        if isinstance(decoded, dict):
            return decoded

    return {
        "ok": False,
        "error": f"Unexpected tool payload: {type(payload).__name__}",
    }


def _normalize_repo(repo: str | None) -> str | None:
    if not repo:
        return None

    stripped = repo.strip()

    if REPO_RE.fullmatch(stripped):
        return stripped

    return None


def _build_router_prompt(text: str) -> str:
    return (
        "You are the planning layer for a GitHub issue triage agent. "
        "Read the user's raw free-form request and choose exactly one available "
        "tool. Return ONLY valid JSON. Do not answer the user directly and do "
        "not invent tool names.\n\n"
        "Available tools:\n"
        f"{json.dumps(AVAILABLE_AGENT_TOOLS, ensure_ascii=False, indent=2)}\n\n"
        "Rules:\n"
        "- If the user asks about one concrete GitHub issue, choose "
        "`run_issue_triage` and provide repo as owner/name plus issue_number.\n"
        "- If the user asks to find/list/search issues in a repository, choose "
        "`github_search_related_issues` and provide repo as owner/name, a search "
        "query, limit, sort, and order.\n"
        "- Infer owner/name from natural language only when it is highly "
        "confident, for example well-known GitHub projects. If uncertain, choose "
        "`unable_to_answer` and ask for an owner/repo repository.\n"
        "- For requests about most discussed/popular issues, prefer sort "
        "`comments` and order `desc`.\n"
        "- For latest/recent requests, prefer sort `created` and order `desc`.\n"
        "- Extract a semantic query that preserves the user's topic. Do not use "
        "empty generic queries unless the user asked for all issues.\n"
        "- Clamp limit to 1..30. Default limit is 5.\n\n"
        "Output schema:\n"
        "{\n"
        '  "tool": "run_issue_triage | github_search_related_issues | '
        'unable_to_answer",\n'
        '  "arguments": {},\n'
        '  "reason": "short reason"\n'
        "}\n\n"
        f"User request: {text}"
    )


def _plan_from_llm_response(text: str, response: dict[str, Any]) -> FreeInputPlan:
    tool = response.get("tool")
    arguments = response.get("arguments", {})
    reason = str(response.get("reason") or "LLM selected tool.")

    if not isinstance(arguments, dict):
        return FreeInputPlan(
            mode="unable_to_parse",
            raw_input=text,
            reason="LLM returned invalid arguments.",
            router="llm",
        )

    if tool == "run_issue_triage":
        repo = _normalize_repo(arguments.get("repo"))
        issue_number = arguments.get("issue_number")

        if repo and isinstance(issue_number, int):
            return FreeInputPlan(
                mode="issue_triage",
                raw_input=text,
                repo=repo,
                issue_number=issue_number,
                reason=reason,
                router="llm",
            )

    if tool == "github_search_related_issues":
        repo = _normalize_repo(arguments.get("repo"))

        if repo:
            limit = arguments.get("limit", 5)

            if not isinstance(limit, int):
                limit = 5

            sort = arguments.get("sort")

            if sort not in {"comments", "created", "updated"}:
                sort = None

            order = arguments.get("order", "desc")

            if order not in {"asc", "desc"}:
                order = "desc"

            query = str(arguments.get("query") or "").strip()

            return FreeInputPlan(
                mode="issue_search",
                raw_input=text,
                repo=repo,
                query=query or "is:issue",
                limit=max(1, min(limit, 30)),
                sort=sort,
                order=order,
                reason=reason,
                router="llm",
            )

    return FreeInputPlan(
        mode="unable_to_parse",
        raw_input=text,
        reason=reason,
        router="llm",
    )


def plan_free_input_with_llm(text: str) -> FreeInputPlan:
    raw_input = text.strip()

    if not raw_input:
        return FreeInputPlan(
            mode="unable_to_parse",
            raw_input=raw_input,
            reason="Input is empty.",
            router="llm",
        )

    prompt = _build_router_prompt(text)
    result = OllamaLLM().generate_json(prompt, timeout_sec=30)

    if not result.get("ok"):
        return FreeInputPlan(
            mode="unable_to_parse",
            raw_input=raw_input,
            reason=f"LLM router unavailable: {result.get('error', 'unknown error')}",
            router="llm",
        )

    output = result.get("result", {})

    if not isinstance(output, dict):
        return FreeInputPlan(
            mode="unable_to_parse",
            raw_input=raw_input,
            reason="LLM router returned invalid JSON shape.",
            router="llm",
        )

    plan = _plan_from_llm_response(text.strip(), output)

    return plan


def _slim_issue(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "number": item.get("number"),
        "title": item.get("title"),
        "state": item.get("state"),
        "url": item.get("html_url"),
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
        "labels": [
            label.get("name")
            for label in item.get("labels", [])
            if isinstance(label, dict) and label.get("name")
        ],
    }


def execute_free_input(
    plan: FreeInputPlan,
    interactive_human: bool = False,
) -> dict[str, Any]:
    if plan.mode == "issue_triage" and plan.repo and plan.issue_number:
        from src.agent.run import run

        return {
            "mode": plan.mode,
            "input": plan.raw_input,
            "parsed": asdict(plan),
            "result": run(
                plan.repo,
                plan.issue_number,
                interactive_human=interactive_human,
            ),
        }

    if plan.mode == "issue_search" and plan.repo:
        payload = _normalize_tool_payload(
            github_search_related_issues(
                plan.repo,
                plan.query,
                limit=plan.limit,
                sort=plan.sort,
                order=plan.order,
            )
        )

        if not payload.get("ok"):
            return {
                "mode": plan.mode,
                "input": plan.raw_input,
                "parsed": asdict(plan),
                "ok": False,
                "error": payload.get("error", "GitHub search failed."),
                "status": payload.get("status"),
            }

        items = payload.get("items", [])

        return {
            "mode": plan.mode,
            "input": plan.raw_input,
            "parsed": asdict(plan),
            "ok": True,
            "total_count": payload.get("total_count", 0),
            "issues": [_slim_issue(item) for item in items if isinstance(item, dict)],
        }

    return {
        "mode": "unable_to_parse",
        "input": plan.raw_input,
        "parsed": asdict(plan),
        "ok": False,
        "error": plan.reason,
        "examples": [
            "https://github.com/pytorch/pytorch/issues/123",
            "pytorch/pytorch#123",
            "find me 5 latest issues about implementation loss functions in pytorch repo",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the triage agent from free-form user text."
    )
    parser.add_argument(
        "--input",
        help="Free-form user request. If omitted, stdin is used.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only parse the input and show the selected mode.",
    )
    parser.add_argument(
        "--interactive-human",
        action="store_true",
        default=True,
        help="Resume human-in-the-loop interrupts from terminal input.",
    )
    parser.add_argument(
        "--no-interactive-human",
        action="store_false",
        dest="interactive_human",
        help="Return pending interrupts instead of asking for terminal input.",
    )
    parser.add_argument(
        "--llm-judge",
        action="store_true",
        help="Ask the local LLM judge to evaluate the free-form run output.",
    )
    parser.add_argument(
        "--judge-timeout-sec",
        type=int,
        default=60,
        help="Timeout for the optional free-form LLM judge call.",
    )

    args = parser.parse_args()
    text = args.input if args.input is not None else sys.stdin.read()
    plan = plan_free_input_with_llm(text)

    output = {
        "parsed": asdict(plan),
    }

    if not args.dry_run:
        output = execute_free_input(
            plan,
            interactive_human=bool(args.interactive_human),
        )

        if args.llm_judge:
            from src.eval.llm_judge import judge_free_run_output

            output["llm_judge"] = judge_free_run_output(
                text,
                output,
                timeout_sec=int(args.judge_timeout_sec),
            )

    print(json.dumps(output, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
