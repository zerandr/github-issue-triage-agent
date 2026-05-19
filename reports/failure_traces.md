# Annotated Failure Traces

These traces were selected from machine-readable trajectory JSON files.

## 1. t25 - Human review interrupt pending

- Source: `runs/main/trajectories/t25.json`
- Task: `code_area` for `scikit-learn/scikit-learn#33558`
- Score: `3`
- Tool-selection accuracy: `1.0`
- Unnecessary tool calls: `0`
- Stop reason: `human_interrupt_pending`
- Expected tools: `['github_get_issue', 'github_search_related_issues']`
- Used tools: `['classification_heuristic', 'github_get_issue', 'github_search_related_issues', 'triage_cache_get']`

### What happened
The automated eval correctly reached the human-in-the-loop gate, but the interrupt was not resumed by a reviewer, so the trace ends with a pending human decision.

### Evidence and symptoms
- Final classification: `unknown`
- Evidence count shown: `5`
- Related issues found: `3`

### Suggested fix
During live demo, resume the interrupt with a reviewer classification; for automated eval, keep this explicit terminal state instead of an implicit missing stop reason.

## 2. adv_001 - Nonexistent issue path

- Source: `runs/main/trajectories/adv_001.json`
- Task: `adversarial_nonexistent_issue` for `pandas-dev/pandas#99999999`
- Score: `3`
- Tool-selection accuracy: `1.0`
- Unnecessary tool calls: `0`
- Stop reason: `tool_error_non_retriable`
- Expected tools: `['github_get_issue']`
- Used tools: `['github_get_issue']`

### What happened
The agent correctly avoided fabrication, but the trajectory ends as a non-completion 404 path instead of a normal completed not-found report.

### Evidence and symptoms
- Error: `github_get_issue failed: status=404; error={"message":"Not Found","documentation_url":"https://docs.github.com/rest/issues/issues#get-an-issue","status":"404"}`
- Final classification: `unknown`
- Evidence count shown: `1`
- Related issues found: `0`

### Suggested fix
Map issue-level 404s into a completed not-found triage report instead of using the same terminal state as unexpected tool failures.

## 3. t29 - Unnecessary extra tool calls

- Source: `runs/main/trajectories/t29.json`
- Task: `classify` for `jax-ml/jax#37251`
- Score: `3`
- Tool-selection accuracy: `1.0`
- Unnecessary tool calls: `2`
- Stop reason: `completed`
- Expected tools: `['github_get_issue']`
- Used tools: `['classification_heuristic', 'github_get_issue', 'github_get_issue_timeline', 'github_search_related_issues', 'heuristic_area_inference', 'ollama_qwen_triage', 'triage_cache_get']`

### What happened
The trajectory used additional GitHub tool classes beyond the rubric's expected set ['github_get_issue']. Recorded tool classes: ['classification_heuristic', 'github_get_issue', 'github_get_issue_timeline', 'github_search_related_issues', 'heuristic_area_inference', 'ollama_qwen_triage', 'triage_cache_get'].

### Evidence and symptoms
- Final classification: `bug`
- Evidence count shown: `5`
- Related issues found: `3`

### Suggested fix
Route task-specific workflows more tightly so simple classification tasks can stop after issue retrieval unless duplicate or stale-state evidence is needed.
