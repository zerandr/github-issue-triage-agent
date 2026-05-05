# Track C - GitHub Issue Triage Agent (LangGraph + MCP)

Implementation scaffold aligned with the assignment requirements:
- explicit LangGraph `StateGraph`
- conditional routing edges
- checkpointed state
- human-in-the-loop interrupt
- custom MCP server in separate process
- eval + trajectory logging + ablation scaffolding

## Project layout
- `src/agent/` - state schema, graph, CLI runner
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

Start custom MCP server (separate process):
```bash
python -m src.mcp_custom.server
```

Run one triage:
```bash
python -m src.agent.run --repo owner/repo --issue 123
```

Run evaluation:
```bash
python -m src.eval.run_eval --tasks data/eval_tasks.jsonl --model gpt-5-mini
```

Outputs:
- `reports/eval_summary.json`
- `reports/trajectories/*.json`
- cache DB: `data/cache/triage_cache.sqlite`

## Notes
- Replace placeholder repos/issues in `data/eval_tasks.jsonl` with the official fixed 5-repo list once published.
- The graph currently uses deterministic heuristics for classification and area inference; you can drop in your chosen LLM call node while keeping the same state/tool contracts.
