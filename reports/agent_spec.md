# Agent Spec (Track C)

## Target user and scenario
Maintainer triaging issues in one of the fixed evaluation repositories (Track C list).

## Inputs
- default structured mode: `repo` (`owner/name`) and `issue_number` (int)
- free-form mode (`src/agent/free_run.py`): arbitrary user text, such as a GitHub issue URL, `owner/repo#123`, or a broader request like "find me 5 latest issues about implementation loss functions in pytorch repo". The LLM sees the available tools and chooses which one to call; deterministic parsing is retained as a fallback.
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
- Purpose: local file access for evaluation artifacts, reports, and finalize-time audit records.
- Tools: `read_file`, `write_file`, `list_directory`.
- Arguments: project-relative paths bounded by the configured filesystem root.
- Returns: file text, directory entries, or write confirmation depending on tool.
- Errors: missing paths, permission errors, paths outside the configured root.
- Side effects: bounded local filesystem reads/writes inside the project directory, including audit JSON files under `audit/triage_results/`.

2. Git MCP (`@cyanheads/git-mcp-server`)
- Purpose: version generated JSON evaluation artifacts after an eval run.
- Tools used by eval: `git_add`, `git_commit`, `git_push`.
- Arguments: working directory/path plus tool-specific fields such as file list,
  commit message, remote, and branch.
- Returns: staged file count, commit hash, push result, or structured error.
- Errors: dirty/unresolved repository state, invalid remote credentials, rejected push.
- Side effects: stages JSON artifacts, creates a commit, and optionally pushes to the configured remote.

### Custom MCP server (`src/mcp_custom/server.py`)
1. `github_get_issue(repo: str, issue_number: int)`
- Purpose: fetch issue payload from GitHub REST.
- Arguments: `repo` in `owner/name` form and integer `issue_number`.
- Returns: `{ok:true, issue}` or error envelope.
- Errors: `404` for missing repo/issue, `401/403` for auth/rate-limit/permission,
  `408/5xx` for retriable network/server failures.
- Side effects: external network call.

2. `github_search_related_issues(repo: str, query: str, limit: int=10, sort: str|None=None, order: str="desc")`
- Purpose: find duplicates/related issues and support free-form repository issue search.
- Arguments: same-repo search query, `limit` in `[1, 30]`, optional GitHub search `sort` (`comments|created|updated`), and `order` (`asc|desc`).
- Returns: `{ok, total_count, items}` or error envelope.
- Errors: `400` for invalid limit/sort/order, GitHub REST/search errors otherwise.
- Side effects: external network call.

3. `github_get_issue_timeline(repo: str, issue_number: int, per_page: int=50)`
- Purpose: summarize stale issues.
- Arguments: repo, issue number, and `per_page` in `[1, 100]`.
- Returns: `{ok, events}` or error envelope.
- Errors: `400` for invalid `per_page`, GitHub REST errors otherwise.
- Side effects: external network call.

4. `triage_cache_get(key: str, max_age_sec: int=86400)`
- Purpose: local read-through cache.
- Arguments: request-derived cache key and maximum age in seconds.
- Returns: `{ok, hit, value_json?, stale?, ts?}`.
- Errors: SQLite read/open failures.
- Side effects: local SQLite read.

5. `triage_cache_put(key: str, value_json: str)`
- Purpose: persist JSON tool payloads.
- Arguments: request-derived cache key and JSON string payload.
- Returns: `{ok, key}` or validation error.
- Errors: `400` when `value_json` is not valid JSON, SQLite write failures.
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

## LLM-as-a-judge evaluation
Optional LAAJ scoring is implemented in `src/eval/llm_judge.py` and enabled
through `python -m src.eval.run_eval --llm-judge` or `make eval-llm-judge`.
The judge receives the task rubric, compact final state, evidence snippets, tool
events, and deterministic metrics. It returns JSON fields for `score_3pt`,
`groundedness`, `tool_use`, `hallucination_risk`, and `rationale`, which are
stored in trajectory artifacts and summarized in the aggregate eval summary.
