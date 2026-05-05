from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

IssueType = Literal[
    "bug", "feature request", "question", "documentation", "duplicate", "unknown"
]


class ToolEvent(BaseModel):
    tool: str
    ok: bool
    retriable: bool = False
    latency_ms: int = 0
    error: str = ""


class EvidenceItem(BaseModel):
    evidence_id: str
    source_tool: str
    summary: str


class TriageState(BaseModel):
    repo: str
    issue_number: int
    issue_url: str | None = None

    issue_snapshot: dict = Field(default_factory=dict)
    related_issues: list[dict] = Field(default_factory=list)
    probable_code_areas: list[str] = Field(default_factory=list)
    classification: IssueType = "unknown"
    justification: str = ""
    open_questions: list[str] = Field(default_factory=list)
    decision_needed: str = ""
    current_state_summary: str = ""

    evidence: list[EvidenceItem] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    tool_events: list[ToolEvent] = Field(default_factory=list)

    step_count: int = 0
    tool_calls: int = 0
    budget_tokens_used: int = 0
    started_at_unix: float = 0.0
    stop_reason: str | None = None

    max_steps: int = 16
    max_tool_calls: int = 12
    max_wall_clock_sec: int = 45
    max_retries_per_tool: int = 2

    scratchpad: str = ""
    needs_human_review: bool = False
    fatal_error: str = ""
