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
- `data/eval_tasks.jsonl` - 30+ task definitions with rubric and constraints
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

## Run evaluation
```bash
make eval
```

Outputs:
- `reports/eval_summary.json`
- `runs/main/trajectories/*.json`
- cache DB: `data/cache/triage_cache.sqlite`

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

## Notes
- Replace placeholder repos/issues in `data/eval_tasks.jsonl` with the official fixed 5-repo list once published.
- No model training is required: this is inference-time agentic triage with tool calls.
