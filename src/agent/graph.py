import json
import os
import time
from typing import Any, Literal

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from src.agent.filesystem_mcp_client import write_audit_record
from src.agent.llm import OllamaLLM
from src.agent.mcp_client import (
    call_tool,
    github_get_issue,
    github_get_issue_timeline,
    github_search_related_issues,
)
from src.agent.state import EvidenceItem, ToolEvent, TriageState


RETRIABLE_HTTP = {408, 429, 500, 502, 503, 504}


class Graph:
    def __init__(self):
        self.llm = OllamaLLM()

    @staticmethod
    def _normalize_tool_result(result: Any) -> dict[str, Any]:
        """
        MCP servers sometimes return dicts directly, and sometimes return JSON strings.
        This helper makes the rest of the graph work with both formats.
        """
        if isinstance(result, dict):
            return result

        if isinstance(result, str):
            try:
                parsed = json.loads(result)
                if isinstance(parsed, dict):
                    return parsed
                return {"ok": True, "data": parsed}
            except json.JSONDecodeError:
                return {"ok": True, "text": result}

        return {"ok": True, "data": result}

    @staticmethod
    def _cache_get(key: str, max_age_sec: int = 86400) -> dict[str, Any]:
        result = call_tool(
            "triage_cache_get",
            {
                "key": key,
                "max_age_sec": max_age_sec,
            },
        )
        return Graph._normalize_tool_result(result)

    @staticmethod
    def _cache_put(key: str, value_json: str) -> dict[str, Any]:
        result = call_tool(
            "triage_cache_put",
            {
                "key": key,
                "value_json": value_json,
            },
        )
        return Graph._normalize_tool_result(result)

    @staticmethod
    def _add_evidence(state: TriageState, source_tool: str, summary: str) -> None:
        idx = len(state.evidence) + 1
        evidence_id = f"E{idx}"

        state.evidence.append(
            EvidenceItem(
                evidence_id=evidence_id,
                source_tool=source_tool,
                summary=summary,
            )
        )
        state.evidence_ids.append(evidence_id)

    @staticmethod
    def _record_trajectory_event(
        state: TriageState,
        event_type: str,
        name: str,
        *,
        input_payload: dict[str, Any] | None = None,
        output_payload: dict[str, Any] | None = None,
        latency_ms: int = 0,
    ) -> None:
        state.trajectory_events.append(
            {
                "step": state.step_count,
                "event_type": event_type,
                "name": name,
                "input": input_payload or {},
                "output": output_payload or {},
                "latency_ms": latency_ms,
            }
        )

    @staticmethod
    def _record_tool(
        state: TriageState,
        tool: str,
        arguments: dict[str, Any],
        result: dict[str, Any],
        latency_ms: int,
    ) -> None:
        ok = bool(result.get("ok", False))
        status = int(result.get("status", 0) or 0)
        retriable = not ok and status in RETRIABLE_HTTP

        state.tool_events.append(
            ToolEvent(
                step=state.step_count,
                tool=tool,
                status=status,
                ok=ok,
                retriable=retriable,
                latency_ms=latency_ms,
                error=str(result.get("error") or ""),
            )
        )
        state.tool_calls += 1
        Graph._record_trajectory_event(
            state,
            "tool_call",
            tool,
            input_payload={"arguments": arguments},
            output_payload=result,
            latency_ms=latency_ms,
        )

    @staticmethod
    def _call_with_cache(
        state: TriageState,
        cache_key: str,
        producer_args: dict[str, Any],
        producer,
    ) -> dict[str, Any]:
        """
        Reads a cached tool result first.
        If cache miss, calls producer(), records the tool event, and stores result.
        """
        cache_result = Graph._cache_get(cache_key, max_age_sec=86400)

        if cache_result.get("hit"):
            try:
                payload = json.loads(cache_result["value_json"])
                Graph._record_trajectory_event(
                    state,
                    "cache_hit",
                    cache_key.split(":", 1)[0],
                    input_payload={
                        "cache_key": cache_key,
                        "max_age_sec": 86400,
                    },
                    output_payload=payload,
                )
                Graph._add_evidence(
                    state,
                    "triage_cache_get",
                    f"Cache hit for {cache_key}",
                )
                return payload
            except Exception:
                pass

        tries = 0
        payload: dict[str, Any] = {
            "ok": False,
            "status": 500,
            "error": "tool was not called",
        }

        while tries <= state.max_retries_per_tool:
            tries += 1
            started = time.time()

            raw_payload = producer()
            payload = Graph._normalize_tool_result(raw_payload)

            tool_name = cache_key.split(":")[0]
            Graph._record_tool(
                state,
                tool_name,
                producer_args,
                payload,
                int((time.time() - started) * 1000),
            )

            if payload.get("ok"):
                Graph._cache_put(
                    cache_key,
                    json.dumps(payload, ensure_ascii=False),
                )
                return payload

            status = int(payload.get("status", 0) or 0)
            if status not in RETRIABLE_HTTP:
                return payload

        return payload

    @staticmethod
    def bootstrap(state: TriageState) -> TriageState:
        state.step_count += 1

        if state.started_at_unix <= 0:
            state.started_at_unix = time.time()

        return state

    @staticmethod
    def fetch_issue(state: TriageState) -> TriageState:
        state.step_count += 1

        cache_key = f"github_get_issue:{state.repo}:{state.issue_number}"

        result = Graph._call_with_cache(
            state,
            cache_key,
            {"repo": state.repo, "issue_number": state.issue_number},
            lambda: github_get_issue(state.repo, state.issue_number),
        )

        if not result.get("ok"):
            status = result.get("status")
            error = result.get("error", "")

            state.fatal_error = (
                f"github_get_issue failed: status={status}; error={error}"
            )
            state.stop_reason = "tool_error_non_retriable"

            Graph._add_evidence(
                state,
                "github_get_issue",
                f"Could not load issue #{state.issue_number}. Status: {status}",
            )
            return state

        raw_issue = result.get("issue", {})

        issue = {
            "number": raw_issue.get("number"),
            "title": raw_issue.get("title"),
            "body": raw_issue.get("body"),
            "state": raw_issue.get("state"),
            "labels": [
                {"name": label.get("name")}
                for label in raw_issue.get("labels", [])
                if isinstance(label, dict)
            ],
            "created_at": raw_issue.get("created_at"),
            "updated_at": raw_issue.get("updated_at"),
            "html_url": raw_issue.get("html_url"),
        }

        state.issue_snapshot = issue

        Graph._add_evidence(
            state,
            "github_get_issue",
            f"Loaded issue #{state.issue_number}: {issue.get('title', '')[:120]}",
        )

        return state

    @staticmethod
    def gather_related(state: TriageState) -> TriageState:
        state.step_count += 1

        title = (state.issue_snapshot.get("title") or "").strip()
        body = (state.issue_snapshot.get("body") or "").strip()

        queries: list[str] = []

        if title:
            queries.append(title[:80])

        lower_body = body.lower()

        if any(
            token in lower_body
            for token in ["error", "exception", "traceback", "crash"]
        ):
            queries.append("error exception traceback crash")

        labels = [
            label.get("name")
            for label in state.issue_snapshot.get("labels", [])
            if isinstance(label, dict) and label.get("name")
        ]

        if labels:
            queries.append(" ".join(labels[:3]))

        if not queries:
            queries.append(str(state.issue_number))

        related: list[dict[str, Any]] = []

        for query in queries[:3]:
            cache_key = f"github_search_related_issues:{state.repo}:{query}"

            result = Graph._call_with_cache(
                state,
                cache_key,
                {"repo": state.repo, "query": query, "limit": 8},
                lambda query=query: github_search_related_issues(
                    state.repo,
                    query,
                    limit=8,
                ),
            )

            if not result.get("ok"):
                continue

            items = result.get("items", [])
            if isinstance(items, list):
                related.extend(items)

        unique: dict[int, dict[str, Any]] = {}

        for item in related:
            number = item.get("number")

            if isinstance(number, int) and number != state.issue_number:
                unique[number] = {
                    "number": item.get("number"),
                    "title": item.get("title"),
                    "state": item.get("state"),
                    "html_url": item.get("html_url"),
                }

        state.related_issues = list(unique.values())[:3]

        if state.related_issues:
            Graph._add_evidence(
                state,
                "github_search_related_issues",
                f"Found {len(state.related_issues)} likely related issues",
            )
        else:
            Graph._add_evidence(
                state,
                "github_search_related_issues",
                "No strong related issue candidates found",
            )

        return state

    @staticmethod
    def classify_issue(state: TriageState) -> TriageState:
        state.step_count += 1

        title = (state.issue_snapshot.get("title") or "").lower()
        body = (state.issue_snapshot.get("body") or "").lower()
        text = f"{title}\n{body}"

        if state.related_issues and ("duplicate" in text or "same as" in text):
            classification = "duplicate"
        elif "duplicate" in title:
            classification = "duplicate"
        elif (
            any(token in title for token in ["how", "why", "question"]) or "?" in title
        ):
            classification = "question"
        elif any(token in text for token in ["doc", "documentation", "readme", "docs"]):
            classification = "documentation"
        elif any(
            token in text for token in ["feature", "enhancement", "proposal", "request"]
        ):
            classification = "feature request"
        elif any(
            token in text
            for token in ["bug", "error", "crash", "exception", "traceback", "fail"]
        ):
            classification = "bug"
        else:
            classification = "unknown"

        state.classification = classification  # type: ignore[assignment]

        if classification == "unknown":
            state.needs_human_review = True

        related_note = ""
        if state.related_issues:
            related_numbers = [issue.get("number") for issue in state.related_issues]
            related_note = f" Related candidates: {related_numbers}."

        state.justification = (
            f"Classification inferred from issue title/body and available GitHub evidence."
            f"{related_note}"
        )

        Graph._add_evidence(
            state,
            "classification_heuristic",
            f"Initial classification: {classification}",
        )

        return state

    @staticmethod
    def infer_code_areas(state: TriageState) -> TriageState:
        state.step_count += 1

        text = (
            f"{state.issue_snapshot.get('title', '')}\n"
            f"{state.issue_snapshot.get('body', '')}"
        ).lower()

        hints: list[str] = []

        mapping = {
            "auth": "auth/*",
            "login": "auth/*",
            "token": "auth/*",
            "api": "api/*",
            "server": "server/*",
            "cli": "cli/*",
            "command": "cli/*",
            "ui": "frontend/*",
            "frontend": "frontend/*",
            "component": "frontend/*",
            "readme": "README.md",
            "doc": "docs/*",
            "documentation": "docs/*",
            "test": "tests/*",
            "database": "db/*",
            "migration": "db/*",
            "sql": "db/*",
            "install": "installation/setup",
            "dependency": "package/dependencies",
        }

        for token, area in mapping.items():
            if token in text and area not in hints:
                hints.append(area)

        if hints:
            state.probable_code_areas = hints[:5]
        else:
            state.probable_code_areas = ["unknown (insufficient evidence)"]

        Graph._add_evidence(
            state,
            "heuristic_area_inference",
            f"Probable areas: {state.probable_code_areas}",
        )

        return state

    @staticmethod
    def summarize_issue_state(state: TriageState) -> TriageState:
        state.step_count += 1

        cache_key = f"github_get_issue_timeline:{state.repo}:{state.issue_number}"

        result = Graph._call_with_cache(
            state,
            cache_key,
            {"repo": state.repo, "issue_number": state.issue_number},
            lambda: github_get_issue_timeline(
                state.repo,
                state.issue_number,
            ),
        )

        if result.get("ok"):
            events = result.get("events", [])

            if isinstance(events, list):
                state.current_state_summary = (
                    f"Timeline events reviewed: {len(events)}. "
                    f"Latest state should be validated by maintainer."
                )

                Graph._add_evidence(
                    state,
                    "github_get_issue_timeline",
                    f"Fetched {len(events)} timeline events",
                )
            else:
                state.current_state_summary = "Timeline returned unexpected format."
        else:
            state.current_state_summary = "Timeline unavailable due to API error."

        if state.issue_snapshot.get("state") == "open":
            state.open_questions = [
                "Is the reproducer still valid on the latest main branch?",
                "Is there an agreed owner for implementation or review?",
            ]
            state.decision_needed = (
                "Close as stale, ask for updated reproduction, or assign an owner "
                "with a concrete next milestone."
            )

        return state

    def llm_triage(self, state: TriageState) -> TriageState:
        state.step_count += 1

        payload = {
            "repo": state.repo,
            "issue_number": state.issue_number,
            "issue": {
                "title": state.issue_snapshot.get("title"),
                "body": state.issue_snapshot.get("body"),
                "state": state.issue_snapshot.get("state"),
                "labels": [
                    label.get("name")
                    for label in state.issue_snapshot.get("labels", [])
                    if isinstance(label, dict)
                ],
            },
            "related_issues": [
                {
                    "number": issue.get("number"),
                    "title": issue.get("title"),
                    "state": issue.get("state"),
                    "url": issue.get("html_url"),
                }
                for issue in state.related_issues
            ],
            "current_fields": {
                "classification": state.classification,
                "justification": state.justification,
                "probable_code_areas": state.probable_code_areas,
                "open_questions": state.open_questions,
                "decision_needed": state.decision_needed,
                "current_state_summary": state.current_state_summary,
            },
            "instruction": (
                "Use retrieved GitHub data as evidence. Do not invent issue numbers, "
                "code paths, labels, or conclusions that are not supported by the data."
            ),
        }

        started = time.time()
        result = self.llm.run(payload)

        Graph._record_tool(
            state,
            "ollama_qwen_triage",
            {"payload": payload},
            result,
            int((time.time() - started) * 1000),
        )

        if not result.get("ok"):
            Graph._add_evidence(
                state,
                "ollama_qwen_triage",
                "LLM unavailable; fallback heuristics kept.",
            )
            return state

        output = result.get("result", {})

        if not isinstance(output, dict):
            Graph._add_evidence(
                state,
                "ollama_qwen_triage",
                "LLM returned unexpected format; fallback heuristics kept.",
            )
            return state

        usage = result.get("usage", {})
        if isinstance(usage, dict):
            state.token_count += int(usage.get("eval_count", 0) or 0)

        classification = output.get("classification")

        if classification in {
            "bug",
            "feature request",
            "question",
            "documentation",
            "duplicate",
            "unknown",
        }:
            state.classification = classification

        justification = output.get("justification")
        if isinstance(justification, str) and justification.strip():
            state.justification = justification.strip()

        probable_code_areas = output.get("probable_code_areas")
        if isinstance(probable_code_areas, list):
            cleaned = [str(area) for area in probable_code_areas][:5]
            if cleaned:
                state.probable_code_areas = cleaned

        open_questions = output.get("open_questions")
        if isinstance(open_questions, list):
            state.open_questions = [str(question) for question in open_questions][:5]

        decision_needed = output.get("decision_needed")
        if isinstance(decision_needed, str) and decision_needed.strip():
            state.decision_needed = decision_needed.strip()

        current_state_summary = output.get("current_state_summary")
        if isinstance(current_state_summary, str) and current_state_summary.strip():
            state.current_state_summary = current_state_summary.strip()

        Graph._add_evidence(
            state,
            "ollama_qwen_triage",
            "LLM triage refinement applied.",
        )

        return state

    @staticmethod
    def human_gate(state: TriageState) -> TriageState:
        labels = [
            label.get("name")
            for label in state.issue_snapshot.get("labels", [])
            if isinstance(label, dict) and label.get("name")
        ]

        decision = interrupt(
            {
                "reason": "Ambiguous classification or low evidence",
                "repo": state.repo,
                "issue_number": state.issue_number,
                "issue": {
                    "title": state.issue_snapshot.get("title"),
                    "body": (state.issue_snapshot.get("body") or "")[:1200],
                    "state": state.issue_snapshot.get("state"),
                    "labels": labels,
                    "url": state.issue_snapshot.get("html_url"),
                },
                "related_issues": [
                    {
                        "number": issue.get("number"),
                        "title": issue.get("title"),
                        "state": issue.get("state"),
                        "url": issue.get("html_url"),
                    }
                    for issue in state.related_issues[:3]
                ],
                "current_classification": state.classification,
                "current_justification": state.justification,
                "question": (
                    "Approve this classification or override it. "
                    "Return {'classification': 'bug'} or similar if overriding."
                ),
            }
        )

        if isinstance(decision, dict) and decision.get("classification"):
            override = str(decision["classification"])

            if override in {
                "bug",
                "feature request",
                "question",
                "documentation",
                "duplicate",
                "unknown",
            }:
                state.classification = override  # type: ignore[assignment]
                Graph._add_evidence(
                    state,
                    "human_review",
                    f"Human reviewer overrode classification to {override}",
                )

        state.needs_human_review = False
        return state

    @staticmethod
    def finalize(state: TriageState) -> TriageState:
        if not state.stop_reason:
            state.stop_reason = "completed"

        if state.fatal_error and not state.current_state_summary:
            state.current_state_summary = state.fatal_error

        if state.fatal_error and (
            not state.justification
            or state.justification == "No grounded justification generated."
        ):
            state.justification = (
                "The issue could not be verified from GitHub evidence, so the agent "
                "does not classify it or invent related details."
            )

        if not state.justification:
            state.justification = "No grounded justification generated."

        audit_result = write_audit_record(
            {
                "repo": state.repo,
                "issue_number": state.issue_number,
                "classification": state.classification,
                "justification": state.justification,
                "stop_reason": state.stop_reason,
                "current_state_summary": state.current_state_summary,
                "related_issues": state.related_issues,
                "probable_code_areas": state.probable_code_areas,
                "evidence_ids": state.evidence_ids,
            }
        )
        Graph._record_trajectory_event(
            state,
            "filesystem_mcp_audit_write",
            "write_file",
            input_payload={"audit_dir": "audit/triage_results"},
            output_payload=audit_result,
        )

        return state

    @staticmethod
    def route_after_fetch(state: TriageState) -> Literal["finalize", "gather_related"]:
        if state.stop_reason:
            return "finalize"

        return "gather_related"

    @staticmethod
    def route_after_classify(
        state: TriageState,
    ) -> Literal["human_gate", "infer_code_areas", "finalize"]:
        if state.tool_calls >= state.max_tool_calls:
            state.stop_reason = "tool_call_cap_hit"
            return "finalize"

        if time.time() - state.started_at_unix > state.max_wall_clock_sec:
            state.stop_reason = "wall_clock_timeout"
            return "finalize"

        if state.token_count >= state.max_token_budget:
            state.stop_reason = "token_budget_cap_hit"
            return "finalize"

        if state.step_count >= state.max_steps:
            state.stop_reason = "step_cap_hit"
            return "finalize"

        graph_variant = os.getenv("TRIAGE_GRAPH_VARIANT", "baseline").lower()

        if state.needs_human_review and graph_variant != "no_human_gate":
            return "human_gate"

        return "infer_code_areas"

    def build_graph(self):
        graph = StateGraph(TriageState)

        graph.add_node("bootstrap", Graph.bootstrap)
        graph.add_node("fetch_issue", Graph.fetch_issue)
        graph.add_node("gather_related", Graph.gather_related)
        graph.add_node("classify_issue", Graph.classify_issue)
        graph.add_node("human_gate", Graph.human_gate)
        graph.add_node("infer_code_areas", Graph.infer_code_areas)
        graph.add_node("summarize_issue_state", Graph.summarize_issue_state)
        graph.add_node("llm_triage", self.llm_triage)
        graph.add_node("finalize", Graph.finalize)

        graph.set_entry_point("bootstrap")

        graph.add_edge("bootstrap", "fetch_issue")

        graph.add_conditional_edges(
            "fetch_issue",
            Graph.route_after_fetch,
            {
                "finalize": "finalize",
                "gather_related": "gather_related",
            },
        )

        graph.add_edge("gather_related", "classify_issue")

        graph.add_conditional_edges(
            "classify_issue",
            Graph.route_after_classify,
            {
                "human_gate": "human_gate",
                "infer_code_areas": "infer_code_areas",
                "finalize": "finalize",
            },
        )

        graph.add_edge("human_gate", "infer_code_areas")
        graph.add_edge("infer_code_areas", "summarize_issue_state")
        graph.add_edge("summarize_issue_state", "llm_triage")
        graph.add_edge("llm_triage", "finalize")
        graph.add_edge("finalize", END)

        return graph.compile(checkpointer=MemorySaver())
