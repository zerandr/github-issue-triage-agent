# Agent Spec (Track C)

## Target user and scenario
A maintainer triaging issues in one of the 5 fixed evaluation repositories.

## Inputs
- `repo` (owner/name)
- `issue` (URL or number)
- optional reviewer intervention at HITL gate

## Outputs
Structured triage report JSON:
- `classification`
- `justification` (grounded in evidence ids)
- `related_issues` (<=3)
- `probable_code_areas`
- `current_state_summary` (for old issues)
- `outstanding_questions`
- `decision_needed`

## Tools
- Third-party MCP: filesystem (read/write local artifacts)
- Custom MCP:
  - `github_get_issue(repo, issue_number)`
  - `github_search_related_issues(repo, query, limit)`
  - `github_get_issue_timeline(repo, issue_number, per_page)`
  - `triage_cache_get(key, max_age_sec)` / `triage_cache_put(key, value_json)`

## Side effects and cost
- External API calls to GitHub REST (rate-limited)
- Local SQLite cache mutations

## Stopping criteria
- Success: required report fields completed with evidence
- Stop caps: token budget, max tool calls, wall-clock timeout, step cap
- Refusal: insufficient evidence / inaccessible repository / malformed issue id

## Expected failure modes
- 403 rate limit
- 404 issue not found/deleted
- ambiguous duplicates
- linked artifacts unavailable

## Successful trajectory
Correct routing + grounded tool use + explicit uncertainty when evidence is weak.
