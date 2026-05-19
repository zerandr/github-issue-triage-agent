from dataclasses import dataclass, field
from typing import Any, Literal

IssueType = Literal[
    "bug", "feature request", "question", "documentation", "duplicate", "unknown"
]


@dataclass
class ToolEvent:
    step: int
    tool: str
    status: int
    ok: bool
    retriable: bool = False
    latency_ms: int = 0
    error: str = ""


@dataclass
class EvidenceItem:
    evidence_id: str
    source_tool: str
    summary: str


@dataclass
class TriageState:
    repo: str
    issue_number: int

    issue_snapshot: dict[str, Any] = field(default_factory=dict)
    related_issues: list[dict[str, Any]] = field(default_factory=list)
    probable_code_areas: list[str] = field(default_factory=list)
    classification: IssueType = "unknown"
    justification: str = ""
    open_questions: list[str] = field(default_factory=list)
    decision_needed: str = ""
    current_state_summary: str = ""

    evidence: list[EvidenceItem] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    tool_events: list[ToolEvent] = field(default_factory=list)
    trajectory_events: list[dict[str, Any]] = field(default_factory=list)

    step_count: int = 0
    tool_calls: int = 0
    token_count: int = 0
    started_at_unix: float = 0.0
    stop_reason: str | None = None

    max_steps: int = 16
    max_tool_calls: int = 12
    max_wall_clock_sec: int = 45
    max_token_budget: int = 4000
    max_retries_per_tool: int = 2

    needs_human_review: bool = False
    fatal_error: str = ""
