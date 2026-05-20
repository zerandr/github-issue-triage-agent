# Track C – GitHub Issue Triage Agent (LangGraph + MCP)

Implementation scaffold aligned with the assignment requirements:
- explicit LangGraph `StateGraph`
- conditional routing edges
- checkpointed state
- human-in-the-loop interrupt
- custom MCP server in a separate process
- third-party Git MCP artifact commit/push
- eval + trajectory logging + ablation runner
- LLM refinement node via local Ollama (Qwen 2.5)

## Project layout
- `src/agent/` - state schema, graph, CLI runner, LLM adapter
- `src/mcp_custom/` - custom MCP server (GitHub + cache tools)
- `src/eval/` - evaluation runner and machine-readable trajectory outputs
- `data/eval_tasks.jsonl` - 33 task definitions with rubric and constraints across the 5 fixed Track C repositories
- `reports/` - agent spec, graph diagram, summaries

## Quick start
Use the existing local virtual environment or create one, then install dependencies:

```bash
./venv/bin/pip install -r requirements.txt
```

Optional env vars:
- `GITHUB_TOKEN` to increase GitHub API rate limits
- `OLLAMA_URL` (default: `http://127.0.0.1:11434`)
- `OLLAMA_MODEL` (default: `qwen2.5:7b-instruct`)
- `TRIAGE_PROMPT_VARIANT` (`strict` or `permissive`, used for ablation)
- `TRIAGE_GRAPH_VARIANT` (`baseline` or `no_human_gate`, used for ablation)

## Run Ollama + Qwen
Install Ollama, then pull the model:

```bash
ollama serve
```

```bash
ollama pull qwen2.5:7b-instruct
```

## Auto-build eval tasks from real repositories
```bash
python -m src.eval.build_tasks_from_repos \
  --repos "pandas-dev/pandas,numpy/numpy,jax-ml/jax,pytorch/pytorch,scikit-learn/scikit-learn" \
  --n 32 \
  --out data/eval_tasks.jsonl
```

## Start a custom MCP server (separate process)
```bash
make mcp-custom
```

## Start the third-party Git MCP server
```bash
make mcp-git
```

## Run one triage
```bash
make run-one REPO=owner/repo ISSUE=123
```

If the baseline graph reaches a human-in-the-loop interrupt, this command asks
for a terminal classification and resumes the graph. To return pending
interrupts without asking for input:

```bash
make run-one-noninteractive REPO=owner/repo ISSUE=123
```

## Run from free-form input
```bash
make free-run INPUT="pytorch/pytorch#123"
make free-run INPUT="find me 5 latest issues about implementation loss functions in pytorch repo"
```

This mode is implemented separately in `src/agent/free_run.py`. It accepts
natural-language input, asks the local LLM to choose one of the available agent
tools, then either reuses the normal triage graph for a concrete issue or calls
the GitHub MCP search tool for broader repository issue-search requests.
Deterministic parsing is still available as a fallback with `--router rules`.

For concrete-issue free-form requests, `make free-run` also resumes human review
interrupts interactively by default. Use `make free-run-noninteractive INPUT="..."`
to return pending interrupts without terminal input.

## Run evaluation
```bash
make eval
```

## Run evaluation with LLM-as-a-judge
```bash
make eval-llm-judge
```

This keeps the deterministic metrics and adds per-trajectory judge fields under
`llm_judge` plus aggregate `llm_judge` summary metrics.

Outputs:
- `reports/eval_summary.json`
- `runs/main/trajectories/*.json`
- `audit/triage_results/*.json` with finalize-time classification and justification records written through Filesystem MCP when available
- cache DB: `data/cache/triage_cache.sqlite`

Each trajectory JSON includes ordered `trajectory_events` for cache hits,
GitHub/MCP tool arguments and results, and the local LLM triage payload/result.

## Run evaluation with Git MCP artifact commit
```bash
make eval-git-mcp
```

This runs the eval, then uses the third-party Git MCP server to add, commit,
and push generated JSON artifacts under `runs/main`.

## Run ablation study
```bash
make ablations
```

Outputs:
- `reports/ablations/ablation_results.json`
- `reports/ablations/ablation_study.md`
- `runs/ablations/<variant>/`

## Generate annotated failure traces
```bash
make failure-traces
```

Outputs:
- `reports/failure_traces.json`
- `reports/failure_traces.md`

The analyzer reports concrete trajectory-level risks such as not-found terminal
paths and unnecessary extra GitHub tool calls.

## Notes
- The evaluation set is constrained to 5 Track C repositories: `pandas-dev/pandas`, `numpy/numpy`, `jax-ml/jax`, `pytorch/pytorch`, and `scikit-learn/scikit-learn`.
- No model training is required: this is inference-time agentic triage with tool calls.
