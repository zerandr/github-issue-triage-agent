from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel, Field


IssueType = Literal[
    "bug", "feature request", "question", "documentation", "duplicate", "unknown"
]


class ToolEvent(BaseModel):
    tool: str
    ok: bool
    retriable: bool = False
    latency_ms: int = 0
    error: Optional[str] = None


class TriageState(BaseModel):
    repo: str
    issue_number: int
    issue_url: Optional[str] = None

    # durable artifacts
    issue_snapshot: dict = Field(default_factory=dict)
    related_issues: list[dict] = Field(default_factory=list)
    probable_code_areas: list[str] = Field(default_factory=list)
    classification: IssueType = "unknown"
    justification: str = ""
    open_questions: list[str] = Field(default_factory=list)
    decision_needed: str = ""

    # controls/caps
    step_count: int = 0
    tool_calls: int = 0
    budget_tokens_used: int = 0
    stop_reason: Optional[str] = None

    # traceability
    evidence_ids: list[str] = Field(default_factory=list)
    tool_events: list[ToolEvent] = Field(default_factory=list)

    # transient scratchpad
    scratchpad: str = ""
    needs_human_review: bool = False
