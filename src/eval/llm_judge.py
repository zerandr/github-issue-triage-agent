from __future__ import annotations

import json
from typing import Any

from src.agent.llm import OllamaLLM


JUDGE_SCHEMA = {
    "score_3pt": "integer 1, 2, or 3",
    "groundedness": "integer 1, 2, or 3",
    "tool_use": "integer 1, 2, or 3",
    "hallucination_risk": "low | medium | high",
    "rationale": "short explanation grounded in the provided trace",
}


def _compact_final_state(final_state: dict[str, Any]) -> dict[str, Any]:
    evidence = final_state.get("evidence", [])

    if isinstance(evidence, list):
        evidence = evidence[:8]

    tool_events = final_state.get("tool_events", [])

    if isinstance(tool_events, list):
        tool_events = tool_events[:12]

    related_issues = final_state.get("related_issues", [])

    if isinstance(related_issues, list):
        related_issues = related_issues[:5]

    return {
        "classification": final_state.get("classification"),
        "justification": final_state.get("justification"),
        "related_issues": related_issues,
        "probable_code_areas": final_state.get("probable_code_areas"),
        "current_state_summary": final_state.get("current_state_summary"),
        "open_questions": final_state.get("open_questions"),
        "decision_needed": final_state.get("decision_needed"),
        "evidence": evidence,
        "tool_events": tool_events,
        "stop_reason": final_state.get("stop_reason"),
        "fatal_error": final_state.get("fatal_error"),
    }


def build_judge_prompt(
    task: dict[str, Any],
    final_state: dict[str, Any],
    rule_metrics: dict[str, Any],
) -> str:
    payload = {
        "task": {
            "task_id": task.get("task_id"),
            "repo": task.get("repo"),
            "issue_number": task.get("issue_number"),
            "task_type": task.get("task_type"),
            "success_criteria": task.get("success_criteria"),
            "expected_tool_classes": task.get(
                "expected_tool_classes",
                task.get("expected_tools", []),
            ),
            "forbidden_behaviors": task.get("forbidden_behaviors", []),
            "rubric": task.get("rubric", {}),
        },
        "agent_output": _compact_final_state(final_state),
        "rule_metrics": rule_metrics,
    }

    return (
        "You are an LLM-as-a-judge evaluator for a GitHub issue triage agent. "
        "Evaluate ONLY the provided trace and task rubric. Do not use outside "
        "knowledge and do not assume facts not present in evidence.\n\n"
        "Scoring guide:\n"
        "- 3: correct, grounded, concise, and uses appropriate tool evidence.\n"
        "- 2: partially correct, weakly grounded, incomplete, or minor tool issue.\n"
        "- 1: incorrect, hallucinated, ungrounded, or unsafe.\n\n"
        "Return ONLY valid JSON matching this schema:\n"
        f"{json.dumps(JUDGE_SCHEMA, ensure_ascii=False, indent=2)}\n\n"
        "Evaluation payload:\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def _coerce_score(value: Any) -> int:
    try:
        score = int(value)
    except (TypeError, ValueError):
        return 0

    return score if score in {1, 2, 3} else 0


def judge_trajectory(
    task: dict[str, Any],
    final_state: dict[str, Any],
    rule_metrics: dict[str, Any],
    timeout_sec: int = 60,
) -> dict[str, Any]:
    prompt = build_judge_prompt(task, final_state, rule_metrics)
    result = OllamaLLM().generate_json(prompt, timeout_sec=timeout_sec)

    if not result.get("ok"):
        return {
            "ok": False,
            "error": result.get("error", "LLM judge failed."),
            "status": result.get("status"),
            "usage": result.get("usage", {}),
        }

    output = result.get("result", {})

    if not isinstance(output, dict):
        return {
            "ok": False,
            "error": "LLM judge returned a non-object JSON value.",
            "usage": result.get("usage", {}),
        }

    score = _coerce_score(output.get("score_3pt"))
    groundedness = _coerce_score(output.get("groundedness"))
    tool_use = _coerce_score(output.get("tool_use"))
    hallucination_risk = str(output.get("hallucination_risk") or "medium")

    if hallucination_risk not in {"low", "medium", "high"}:
        hallucination_risk = "medium"

    return {
        "ok": score > 0,
        "score_3pt": score,
        "groundedness": groundedness,
        "tool_use": tool_use,
        "hallucination_risk": hallucination_risk,
        "rationale": str(output.get("rationale") or "").strip(),
        "usage": result.get("usage", {}),
    }
