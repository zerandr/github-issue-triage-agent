# Track C — GitHub Issue Triage Agent (LangGraph + MCP)

Starter implementation for the assignment requirements.

## What is included

- LangGraph `StateGraph` with:
  - conditional routing
  - persistent checkpointing
  - human-in-the-loop interrupt
- Custom MCP server (separate process) with 4 tools:
  - `github_get_issue`
  - `github_search_related_issues`
  - `github_get_issue_timeline`
  - `triage_cache_put` / `triage_cache_get`
- Third-party MCP server integration (filesystem MCP)
- Evaluation scaffolding for 30+ tasks, trajectories, and ablations

## Quick start

1. Create environment and install deps:
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Set env vars:

```bash
cp .env.example .env
# edit .env and set OPENAI_API_KEY (and optional GITHUB_TOKEN)
```

3. Start custom MCP server (separate process):

```bash
python -m src.mcp_custom.server
```

4. Run agent on one issue:

```bash
python -m src.agent.run --repo owner/repo --issue 123
```

5. Run eval:

```bash
python -m src.eval.run_eval --tasks data/eval_tasks.jsonl --model gpt-5-mini
```

## Notes
- Designed for public repos from the fixed assignment list.
- Caching is in `data/cache/triage_cache.sqlite`.
