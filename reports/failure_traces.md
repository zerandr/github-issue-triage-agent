# Annotated Failure Traces

These traces were selected from machine-readable trajectory JSON files.

## 1. adv_001 - Non-completion stop reason

- Source: `runs/main/trajectories/adv_001.json`
- Task: `adversarial_nonexistent_repo` for `not-a-real-owner/not-a-real-repo#1`
- Score: `3`
- Tool-selection accuracy: `1.0`
- Stop reason: `tool_error_non_retriable`
- Expected tools: `['github_get_issue']`
- Used tools: `['github_get_issue']`

### What happened
The trajectory stopped with `tool_error_non_retriable` instead of a normal completion.

### Evidence and symptoms
- Error: `github_get_issue failed: status=404; error={"message":"Not Found","documentation_url":"https://docs.github.com/rest/issues/issues#get-an-issue","status":"404"}`
- Final classification: `unknown`
- Evidence count shown: `1`
- Related issues found: `0`

### Suggested fix
Treat GitHub rate-limit responses as retriable when the response body indicates rate limiting, and prefer authenticated requests during eval.

## 2. adv_002 - Non-completion stop reason

- Source: `runs/main/trajectories/adv_002.json`
- Task: `adversarial_nonexistent_issue` for `langchain-ai/langgraph#99999999`
- Score: `3`
- Tool-selection accuracy: `1.0`
- Stop reason: `tool_error_non_retriable`
- Expected tools: `['github_get_issue']`
- Used tools: `['github_get_issue']`

### What happened
The trajectory stopped with `tool_error_non_retriable` instead of a normal completion.

### Evidence and symptoms
- Error: `github_get_issue failed: status=404; error={"message":"Not Found","documentation_url":"https://docs.github.com/rest/issues/issues#get-an-issue","status":"404"}`
- Final classification: `unknown`
- Evidence count shown: `1`
- Related issues found: `0`

### Suggested fix
Treat GitHub rate-limit responses as retriable when the response body indicates rate limiting, and prefer authenticated requests during eval.

## 3. t29 - Residual trajectory risk

- Source: `runs/main/trajectories/t29.json`
- Task: `classify` for `jax-ml/jax#37251`
- Score: `3`
- Tool-selection accuracy: `1.0`
- Stop reason: `completed`
- Expected tools: `['github_get_issue']`
- Used tools: `['classification_heuristic', 'github_get_issue', 'github_get_issue_timeline', 'github_search_related_issues', 'heuristic_area_inference', 'ollama_qwen_triage', 'triage_cache_get']`

### What happened
This trajectory did not fail the rule-based rubric, but is included to provide the requested third annotated trace and document residual risk.

### Evidence and symptoms
- Final classification: `bug`
- Evidence count shown: `5`
- Related issues found: `3`

### Suggested fix
Inspect the trajectory and add a targeted regression task for this failure mode.
