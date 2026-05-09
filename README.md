# Track C – GitHub Issue Triage Agent (LangGraph + MCP)

Implementation scaffold aligned with the assignment requirements:
- explicit LangGraph `StateGraph`
- conditional routing edges
- checkpointed state
- human-in-the-loop interrupt
- custom MCP server in a separate process
- eval + trajectory logging + ablation scaffolding
- LLM refinement node via local Ollama (Qwen 2.5)

## Project layout
- `src/agent/` - state schema, graph, CLI runner, LLM adapter
- `src/mcp_custom/` - custom MCP server (GitHub + cache tools)
- `src/eval/` - evaluation runner and machine-readable trajectory outputs
- `data/eval_tasks.jsonl` - 30+ task definitions with rubric and constraints
- `reports/` - agent spec, graph diagram, summaries

## Quick start
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Optional env vars:
- `GITHUB_TOKEN` to increase GitHub API rate limits
- `OLLAMA_URL` (default: `http://127.0.0.1:11434`)
- `OLLAMA_MODEL` (default: `qwen2.5:14b-instruct`)

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
python -m src.mcp_custom.server
```

## Run one triage
```bash
python -m src.agent.run --repo owner/repo --issue 123
```

## Run evaluation
```bash
python -m src.eval.run_eval --tasks data/eval_tasks.jsonl --model qwen2.5-7b-instruct
```

Outputs:
- `reports/eval_summary.json`
- `reports/trajectories/*.json`
- cache DB: `data/cache/triage_cache.sqlite`

## Notes
- Replace placeholder repos/issues in `data/eval_tasks.jsonl` with the official fixed 5-repo list once published.
- No model training is required: this is inference-time agentic triage with tool calls.
