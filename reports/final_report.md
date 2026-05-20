# Final Report - GitHub Issue Triage Agent

## Track and Goal
This project implements Track C: a GitHub issue triage agent. The agent can receive either a structured repository/issue pair or free-form user text, retrieves GitHub evidence through MCP tools, and produces a structured triage state with classification, related issues, likely code areas, open questions, decision needed, evidence ids, tool events, and stop reason.

## Agent Specification
Target user: a repository maintainer reviewing incoming or stale GitHub issues.

Inputs:
- structured mode: `repo` in `owner/name` form and `issue_number`.
- free-form mode: arbitrary text handled by `src/agent/free_run.py`, including issue URLs, `owner/repo#123`, and broader repository searches such as "find me 5 latest issues about implementation loss functions in pytorch repo". The LLM receives the available tool list and selects the action to execute; deterministic parsing is kept as a fallback.
- optional human reviewer decision at the interrupt gate.

Outputs:
- `classification`: `bug`, `feature request`, `question`, `documentation`, `duplicate`, or `unknown`.
- `justification`: evidence-grounded rationale.
- `related_issues`: up to 3 related or duplicate candidates.
- `probable_code_areas`: likely modules or paths.
- `current_state_summary`, `open_questions`, `decision_needed`.
- `evidence_ids`, `tool_events`, `stop_reason`.

Success means the trajectory uses the expected tool classes, grounds claims in retrieved evidence, avoids cross-repository duplicate suggestions, and escalates uncertainty instead of inventing details.

## Architecture
The chosen architecture is a single LangGraph `StateGraph` with a bounded tool loop and a human-in-the-loop gate. A supervisor/worker setup was considered, but rejected because the triage tasks are short and benefit more from transparent state transitions than from extra coordination.

```mermaid
graph TD
  A[bootstrap] --> B[fetch_issue]
  B -->|tool_error| I[finalize]
  B -->|ok| C[gather_related]
  C --> D[classify_issue]
  D -->|unknown/ambiguous| E[human_gate interrupt]
  D -->|confident| F[infer_code_areas]
  E --> F
  F --> G[summarize_issue_state]
  G --> H[llm_triage]
  H --> I[finalize]
```

Implementation references:
- State schema: `src/agent/state.py`
- Graph: `src/agent/graph.py`
- LLM adapter: `src/agent/llm.py`
- Free-form input router: `src/agent/free_run.py`

## MCP Tooling
Custom MCP server: `src/mcp_custom/server.py`
- `github_get_issue(repo, issue_number)`: fetches issue metadata from GitHub REST.
- `github_search_related_issues(repo, query, limit, sort, order)`: searches same-repo issues for related or duplicate candidates and supports free-form "latest issues" search.
- `github_get_issue_timeline(repo, issue_number, per_page)`: fetches issue timeline events.
- `triage_cache_get(key, max_age_sec)`: reads cached JSON from SQLite.
- `triage_cache_put(key, value_json)`: writes JSON to SQLite cache.

Third-party MCP servers:
- Filesystem MCP: writes finalize-time audit JSON records under `audit/triage_results/` with the run classification, justification, stop reason, evidence ids, and related triage fields.
- Git MCP (`@cyanheads/git-mcp-server`): used by eval to `git_add`, `git_commit`, and `git_push` generated JSON artifacts.

The custom MCP server runs out-of-process and wraps the primary Track C data source. It also performs local bookkeeping through SQLite caching.

## Evaluation Set
The evaluation set contains 33 tasks in `data/eval_tasks.jsonl` across exactly 5 fixed Track C repositories: `pandas-dev/pandas`, `numpy/numpy`, `jax-ml/jax`, `pytorch/pytorch`, and `scikit-learn/scikit-learn`. It includes classification, duplicate search, ambiguous escalation, stale issue summarization, code-area inference, and 3 adversarial tasks:
- nonexistent issue references inside fixed repositories,
- prompt-injection-style instruction handling with issue content treated as untrusted data.

Each task includes expected tool classes, forbidden behaviors, and a 3-point rubric.

## Baseline Results
Baseline summary from `reports/eval_summary.json`:

| Metric | Value |
| --- | ---: |
| Tasks | 33 |
| Mean score / 3 | 3.0 |
| Score counts | 33 at 3 |
| Tool-selection accuracy | 1.0 |
| Mean steps | 6.424 |
| Mean tool calls | 0.909 |
| Mean latency seconds | 17.347 |
| Total tokens | 3631 |
| Estimated USD cost | 0.0 for local Ollama |
| Ungrounded claims | 0 |
| Hallucinated tool args | 0 |
| Unnecessary GitHub tool calls | 44 |

Stop reasons:
- `completed`: 28
- `human_interrupt_pending`: 3
- `tool_error_non_retriable`: 2

## Trajectory Analysis
Machine-readable trajectories are written under `runs/main/trajectories`. Each trajectory contains the task, ordered `trajectory_events`, final state, evidence, tool events, and metrics. The ordered events include cache hits, tool-call arguments/results, and LLM payload/result records for the triage refinement step.

Optional LLM-as-a-judge evaluation is implemented in `src/eval/llm_judge.py` and enabled with:

```bash
make eval-llm-judge
```

The judge receives the task rubric, compact final state, evidence, tool events, and deterministic rule metrics. It returns JSON with `score_3pt`, `groundedness`, `tool_use`, `hallucination_risk`, and a short rationale. These fields are stored in each trajectory under `llm_judge` and summarized under `llm_judge` in the aggregate summary.

Annotated failures are generated with:

```bash
make failure-traces
```

Current failure modes:
- Human review interrupt pending: the agent reaches HITL correctly, but automated eval does not resume the reviewer decision.
- Nonexistent issue path: the agent refuses to fabricate, but should produce a friendlier completed not-found report.
- Unnecessary extra tool calls: simple classification/ambiguous tasks sometimes still run duplicate and timeline lookups.

See `reports/failure_traces.md` for the three annotated examples.

## Ablation Study
The ablation runner is implemented in `src/eval/run_ablations.py` and runs the same eval set under four variants:

- `baseline`: primary model, strict prompt, baseline graph.
- `model_secondary`: secondary model, same prompt and graph.
- `prompt_permissive`: weaker prompt, same model and graph.
- `graph_no_human_gate`: bypasses the HITL gate, same model and prompt.

Run with:

```bash
make ablations
```

Expected outputs:
- `reports/ablations/ablation_results.json`
- `reports/ablations/ablation_study.md`
- `runs/ablations/<variant>/`

A full ablation artifact has been generated in `reports/ablations/ablation_study.md`. The current run uses the same 33-task evaluation set for all variants. The secondary model is `llama3:latest`, while the primary model is `qwen2.5:7b-instruct`; both produced real token and latency metrics. All variants reached mean score 3.0, while the graph ablation increased steps, tool calls, tokens, and unnecessary GitHub tool calls.

Current ablation output:

| Variant | n | Mean score | Tool accuracy | Mean steps | Mean tool calls | Mean latency | Tokens | Unnecessary calls |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline | 33 | 3.0 | 1.0 | 6.424 | 0.909 | 21.286 | 3713 | 44 |
| model_secondary | 33 | 3.0 | 1.0 | 6.424 | 0.909 | 18.857 | 2997 | 44 |
| prompt_permissive | 33 | 3.0 | 1.0 | 6.424 | 0.909 | 20.858 | 3212 | 44 |
| graph_no_human_gate | 33 | 3.0 | 1.0 | 6.697 | 1.0 | 27.534 | 4137 | 47 |

## Cost and Latency Control
Per-run caps are encoded in `TriageState`:
- `max_steps = 16`
- `max_tool_calls = 12`
- `max_wall_clock_sec = 45`
- `max_token_budget = 4000`
- `max_retries_per_tool = 2`

The current model path uses local Ollama/Qwen, so estimated USD cost is reported as `0.0`. Hosted-model experiments should update cost accounting with provider token prices.

## Limitations and Future Work
- Trajectories now capture ordered cache/tool/model events, but a production-grade trace would also store normalized redacted prompts separately from raw issue bodies.
- GitHub rate-limit `403` should be inspected by response body and treated as retriable when appropriate.
- Cache hits count toward expected tool-class usage and are represented as trajectory events.
- A final grounding validator could map every final claim to evidence ids.
