# Agent Spec (Track C)

## Target user and scenario
Maintainer triaging issues in one of the fixed evaluation repositories (Track C list).

## Inputs
- `repo` (`owner/name`)
- `issue_number` (int)
- optional reviewer action at human-in-the-loop gate

## Outputs
Structured triage report JSON:
- `classification`: one of `bug|feature request|question|documentation|duplicate|unknown`
- `justification`: short evidence-grounded rationale
- `related_issues`: up to 3 likely duplicates/related items
- `probable_code_areas`: paths/modules hypothesis
- `current_state_summary`: for old/open issues
- `open_questions`
- `decision_needed`
- `evidence_ids`, `tool_events`, `stop_reason`

## Architecture choice
Chosen: single LangGraph agent with tool loop + HITL gate.

Considered and rejected:
- Supervisor + workers: higher coordination overhead for this course scope.
- Planner + executor: adds complexity but limited gains on short triage traces.

Reason for choice: simple, debuggable trajectories with explicit conditional routing and one mandatory interrupt point.

## Tool contract
### Third-party MCP servers
1. Filesystem MCP (`@modelcontextprotocol/server-filesystem`)
- Purpose: local file access for evaluation artifacts and reports.
- Tools: `read_file`, `write_file`, `list_directory`.
- Side effects: bounded local filesystem reads/writes inside the project directory.

2. Git MCP (`@cyanheads/git-mcp-server`)
- Purpose: version generated JSON evaluation artifacts after an eval run.
- Tools used by eval: `git_add`, `git_commit`, `git_push`.
- Side effects: stages JSON artifacts, creates a commit, and optionally pushes to the configured remote.

### Custom MCP server (`src/mcp_custom/server.py`)
1. `github_get_issue(repo: str, issue_number: int)`
- Purpose: fetch issue payload from GitHub REST.
- Returns: `{ok:true, issue}` or error envelope.
- Side effects: external network call.

2. `github_search_related_issues(repo: str, query: str, limit: int=10)`
- Purpose: find duplicates/related issues.
- Returns: `{ok, total_count, items}` or error envelope.
- Side effects: external network call.

3. `github_get_issue_timeline(repo: str, issue_number: int, per_page: int=50)`
- Purpose: summarize stale issues.
- Returns: `{ok, events}` or error envelope.
- Side effects: external network call.

4. `triage_cache_get(key: str, max_age_sec: int=86400)`
- Purpose: local read-through cache.
- Returns: `{ok, hit, value_json?, stale?, ts?}`.
- Side effects: local SQLite read.

5. `triage_cache_put(key: str, value_json: str)`
- Purpose: persist JSON tool payloads.
- Returns: `{ok, key}` or validation error.
- Side effects: local SQLite write.

## Error policy
- Retriable: `408, 429, 500, 502, 503, 504` and request/timeout failures.
- Non-retriable: malformed args (`400`), permissions (`401/403` non-rate-limit), not found (`404`).
- Agent behavior: bounded retries (`max_retries_per_tool`), then graceful stop with `stop_reason`.

## Stopping criteria
- Success: required report fields completed with at least one evidence id.
- Safety stop: `max_steps`, `max_tool_calls`, `max_wall_clock_sec`.
- Refusal/stop: invalid issue, deleted repo/issue, or insufficient evidence.

## Successful trajectory
Correct tool class usage, grounded output, explicit uncertainty, and HITL escalation on ambiguity.
