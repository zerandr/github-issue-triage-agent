from __future__ import annotations

from typing import Literal

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import interrupt

from .state import TriageState


def ingest_issue(state: TriageState) -> TriageState:
    state.step_count += 1
    state.scratchpad = "Issue ingested"
    return state


def classify_or_route(state: TriageState) -> TriageState:
    state.step_count += 1
    title = (state.issue_snapshot.get("title") or "").lower()
    body = (state.issue_snapshot.get("body") or "").lower()

    if "duplicate" in title or "duplicate" in body:
        state.classification = "duplicate"
    elif "how" in title or "question" in body:
        state.classification = "question"
    elif "doc" in title or "documentation" in body:
        state.classification = "documentation"
    elif "feature" in title or "enhancement" in body:
        state.classification = "feature request"
    elif "error" in body or "bug" in title:
        state.classification = "bug"
    else:
        state.classification = "unknown"

    if state.classification == "unknown":
        state.needs_human_review = True
    return state


def decide_next(state: TriageState) -> Literal["human_gate", "analyze", "finalize"]:
    if state.needs_human_review:
        return "human_gate"
    if state.step_count > 10:
        state.stop_reason = "step_cap_hit"
        return "finalize"
    return "analyze"


def human_gate(state: TriageState) -> TriageState:
    decision = interrupt(
        {
            "reason": "Low confidence classification",
            "classification": state.classification,
            "question": "Approve auto-triage or force question/bug/documentation/feature/duplicate?",
        }
    )
    if isinstance(decision, dict) and decision.get("classification"):
        state.classification = decision["classification"]
    state.needs_human_review = False
    return state


def analyze(state: TriageState) -> TriageState:
    state.step_count += 1
    state.justification = "Based on issue text and related issue search evidence."
    return state


def finalize(state: TriageState) -> TriageState:
    if not state.stop_reason:
        state.stop_reason = "completed"
    return state


def build_graph():
    g = StateGraph(TriageState)
    g.add_node("ingest_issue", ingest_issue)
    g.add_node("classify_or_route", classify_or_route)
    g.add_node("human_gate", human_gate)
    g.add_node("analyze", analyze)
    g.add_node("finalize", finalize)

    g.set_entry_point("ingest_issue")
    g.add_edge("ingest_issue", "classify_or_route")
    g.add_conditional_edges(
        "classify_or_route",
        decide_next,
        {
            "human_gate": "human_gate",
            "analyze": "analyze",
            "finalize": "finalize",
        },
    )
    g.add_edge("human_gate", "analyze")
    g.add_edge("analyze", "finalize")
    g.add_edge("finalize", END)

    return g.compile(checkpointer=MemorySaver())
