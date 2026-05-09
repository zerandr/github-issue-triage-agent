import json
import time
from typing import Any, Literal

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from src.mcp_custom.server import (
    github_get_issue,
    github_get_issue_timeline,
    github_search_related_issues,
    triage_cache_get,
    triage_cache_put,
)
from src.agent.llm import OllamaLLM
from src.agent.state import EvidenceItem, ToolEvent, TriageState

RETRIABLE_HTTP = {408, 429, 500, 502, 503, 504}


class Graph:
    def __init__(self):
        self.llm = OllamaLLM()

    @staticmethod
    def _add_evidence(state: TriageState, source_tool: str, summary: str) -> None:
        idx = len(state.evidence) + 1
        eid = f"E{idx}"
        state.evidence.append(
            EvidenceItem(evidence_id=eid, source_tool=source_tool, summary=summary)
        )
        state.evidence_ids.append(eid)

    @staticmethod
    def _record_tool(
        state: TriageState, tool: str, result: dict[str, Any], latency_ms: int
    ) -> None:
        ok = bool(result.get("ok", False))
        status = int(result.get("status", 0) or 0)
        retriable = not ok and status in RETRIABLE_HTTP
        state.tool_events.append(
            ToolEvent(
                tool=tool,
                ok=ok,
                retriable=retriable,
                latency_ms=latency_ms,
                error=str(result.get("error") or ""),
            )
        )
        state.tool_calls += 1

    @staticmethod
    def _call_with_cache(
        state: TriageState, cache_key: str, producer
    ) -> dict[str, Any]:
        hit = triage_cache_get(cache_key, max_age_sec=86400)
        if hit.get("hit"):
            try:
                payload = json.loads(hit["value_json"])
                Graph._add_evidence(
                    state, "triage_cache_get", f"Cache hit for {cache_key}"
                )
                return payload
            except Exception:
                pass

        tries = 0
        while tries <= state.max_retries_per_tool:
            tries += 1
            t0 = time.time()
            payload = producer()
            Graph._record_tool(
                state, cache_key.split(":")[0], payload, int((time.time() - t0) * 1000)
            )
            if payload.get("ok"):
                triage_cache_put(cache_key, json.dumps(payload, ensure_ascii=False))
                return payload
            if int(payload.get("status", 0) or 0) not in RETRIABLE_HTTP:
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
        key = f"github_get_issue:{state.repo}:{state.issue_number}"
        result = Graph._call_with_cache(
            state, key, lambda: github_get_issue(state.repo, state.issue_number)
        )
        if not result.get("ok"):
            state.fatal_error = f"github_get_issue failed: {result.get('status')}"
            state.stop_reason = "tool_error_non_retriable"
            return state

        issue = result["issue"]
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
        queries = [title[:80]] if title else [f"{state.issue_number}"]

        err_tokens = [
            x
            for x in ["error", "exception", "traceback"]
            if x in (state.issue_snapshot.get("body") or "").lower()
        ]
        if err_tokens:
            queries.append(" ".join(err_tokens))

        related: list[dict] = []
        for q in queries[:2]:
            key = f"github_search_related_issues:{state.repo}:{q}"
            result = Graph._call_with_cache(
                state,
                key,
                lambda q=q: github_search_related_issues(state.repo, q, limit=8),
            )
            if not result.get("ok"):
                continue
            related.extend(result.get("items", []))

        uniq: dict[int, dict] = {}
        for item in related:
            num = item.get("number")
            if isinstance(num, int) and num != state.issue_number:
                uniq[num] = item

        state.related_issues = list(uniq.values())[:3]
        if state.related_issues:
            Graph._add_evidence(
                state,
                "github_search_related_issues",
                f"Found {len(state.related_issues)} likely related issues",
            )
        return state

    @staticmethod
    def classify_issue(state: TriageState) -> TriageState:
        state.step_count += 1
        title = (state.issue_snapshot.get("title") or "").lower()
        body = (state.issue_snapshot.get("body") or "").lower()

        if "duplicate" in title or "duplicate" in body:
            cls = "duplicate"
        elif any(k in title for k in ["how", "why", "question"]) or "?" in title:
            cls = "question"
        elif any(k in title + " " + body for k in ["doc", "documentation", "readme"]):
            cls = "documentation"
        elif any(
            k in title + " " + body for k in ["feature", "enhancement", "proposal"]
        ):
            cls = "feature request"
        elif any(
            k in title + " " + body for k in ["bug", "error", "crash", "exception"]
        ):
            cls = "bug"
        else:
            cls = "unknown"

        state.classification = cls  # type: ignore[assignment]
        if cls == "unknown":
            state.needs_human_review = True

        rel_note = ""
        if state.related_issues:
            rel_note = f" Related candidates: {[x.get('number') for x in state.related_issues]}"
        state.justification = (
            f"Classification inferred from issue title/body patterns.{rel_note}"
        )
        return state

    @staticmethod
    def infer_code_areas(state: TriageState) -> TriageState:
        state.step_count += 1
        text = f"{state.issue_snapshot.get('title', '')}\n{state.issue_snapshot.get('body', '')}".lower()
        hints: list[str] = []
        mapping = {
            "auth": "auth/*",
            "login": "auth/*",
            "api": "api/*",
            "cli": "cli/*",
            "ui": "frontend/*",
            "readme": "README.md",
            "doc": "docs/*",
            "test": "tests/*",
            "database": "db/*",
            "sql": "db/*",
        }
        for token, area in mapping.items():
            if token in text and area not in hints:
                hints.append(area)

        state.probable_code_areas = (
            hints[:5] if hints else ["unknown (insufficient evidence)"]
        )
        Graph._add_evidence(
            state,
            "heuristic_area_inference",
            f"Probable areas: {state.probable_code_areas}",
        )
        return state

    @staticmethod
    def summarize_old_issue(state: TriageState) -> TriageState:
        state.step_count += 1
        key = f"github_get_issue_timeline:{state.repo}:{state.issue_number}"
        timeline = Graph._call_with_cache(
            state,
            key,
            lambda: github_get_issue_timeline(
                state.repo, state.issue_number, per_page=50
            ),
        )
        if timeline.get("ok"):
            events = timeline.get("events", [])
            state.current_state_summary = f"Timeline events reviewed: {len(events)}; latest state should be validated by maintainer."
            Graph._add_evidence(
                state,
                "github_get_issue_timeline",
                f"Fetched {len(events)} timeline events",
            )
        else:
            state.current_state_summary = "Timeline unavailable due to API error."

        if state.issue_snapshot.get("state") == "open":
            state.open_questions = [
                "Is reproducer still valid on latest main branch?",
                "Is there an agreed owner for implementation/review?",
            ]
            state.decision_needed = (
                "Close as stale, or assign owner with concrete next milestone."
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
                    x.get("name") for x in state.issue_snapshot.get("labels", [])
                ],
            },
            "related_issues": [
                {
                    "number": x.get("number"),
                    "title": x.get("title"),
                    "state": x.get("state"),
                    "url": x.get("html_url"),
                }
                for x in state.related_issues
            ],
            "current_fields": {
                "classification": state.classification,
                "justification": state.justification,
                "probable_code_areas": state.probable_code_areas,
                "open_questions": state.open_questions,
                "decision_needed": state.decision_needed,
                "current_state_summary": state.current_state_summary,
            },
        }

        t0 = time.time()
        out = self.llm.run(payload)
        Graph._record_tool(
            state, "ollama_qwen_triage", out, int((time.time() - t0) * 1000)
        )
        if not out.get("ok"):
            Graph._add_evidence(
                state,
                "ollama_qwen_triage",
                "LLM unavailable; fallback heuristics kept.",
            )
            return state

        result = out.get("result", {})
        cls = result.get("classification")
        if cls in {
            "bug",
            "feature request",
            "question",
            "documentation",
            "duplicate",
            "unknown",
        }:
            state.classification = cls
        if (
            isinstance(result.get("justification"), str)
            and result["justification"].strip()
        ):
            state.justification = result["justification"].strip()
        if isinstance(result.get("probable_code_areas"), list):
            state.probable_code_areas = [str(x) for x in result["probable_code_areas"]][
                :5
            ] or state.probable_code_areas
        if isinstance(result.get("open_questions"), list):
            state.open_questions = [str(x) for x in result["open_questions"]][:5]
        if (
            isinstance(result.get("decision_needed"), str)
            and result["decision_needed"].strip()
        ):
            state.decision_needed = result["decision_needed"].strip()
        if (
            isinstance(result.get("current_state_summary"), str)
            and result["current_state_summary"].strip()
        ):
            state.current_state_summary = result["current_state_summary"].strip()

        Graph._add_evidence(
            state, "ollama_qwen_triage", "LLM triage refinement applied."
        )
        return state

    @staticmethod
    def human_gate(state: TriageState) -> TriageState:
        decision = interrupt(
            {
                "reason": "Ambiguous classification or low evidence",
                "current_classification": state.classification,
                "question": "Approve class or override? Provide classification field if overriding.",
            }
        )
        if isinstance(decision, dict) and decision.get("classification"):
            state.classification = str(decision["classification"])  # type: ignore[assignment]
        state.needs_human_review = False
        return state

    @staticmethod
    def finalize(state: TriageState) -> TriageState:
        if not state.stop_reason:
            state.stop_reason = "completed"
        if not state.justification:
            state.justification = "No grounded justification generated."
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
        if state.step_count >= state.max_steps:
            state.stop_reason = "step_cap_hit"
            return "finalize"
        if state.needs_human_review:
            return "human_gate"
        return "infer_code_areas"

    def build_graph(self):
        g = StateGraph(TriageState)

        g.add_node("bootstrap", Graph.bootstrap)
        g.add_node("fetch_issue", Graph.fetch_issue)
        g.add_node("gather_related", Graph.gather_related)
        g.add_node("classify_issue", Graph.classify_issue)
        g.add_node("human_gate", Graph.human_gate)
        g.add_node("infer_code_areas", Graph.infer_code_areas)
        g.add_node("summarize_old_issue", Graph.summarize_old_issue)
        g.add_node("llm_triage", self.llm_triage)
        g.add_node("finalize", Graph.finalize)

        g.set_entry_point("bootstrap")
        g.add_edge("bootstrap", "fetch_issue")
        g.add_conditional_edges(
            "fetch_issue",
            Graph.route_after_fetch,
            {"finalize": "finalize", "gather_related": "gather_related"},
        )
        g.add_edge("gather_related", "classify_issue")
        g.add_conditional_edges(
            "classify_issue",
            Graph.route_after_classify,
            {
                "human_gate": "human_gate",
                "infer_code_areas": "infer_code_areas",
                "finalize": "finalize",
            },
        )
        g.add_edge("human_gate", "infer_code_areas")
        g.add_edge("infer_code_areas", "summarize_old_issue")
        g.add_edge("summarize_old_issue", "llm_triage")
        g.add_edge("llm_triage", "finalize")
        g.add_edge("finalize", END)

        return g.compile(checkpointer=MemorySaver())
