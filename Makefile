.PHONY: install mcp-custom mcp-filesystem mcp-git run-one eval eval-git-mcp ablations failure-traces clean

PYTHON ?= ./venv/bin/python

install:
	pip install -r requirements.txt

mcp-custom:
	$(PYTHON) -m src.mcp_custom.server

mcp-filesystem:
	./scripts/run_filesystem_mcp.sh

mcp-git:
	./scripts/run_git_mcp.sh

run-one:
	$(PYTHON) -m src.agent.run --repo "$(REPO)" --issue "$(ISSUE)"

eval:
	$(PYTHON) -m src.eval.run_eval --tasks data/eval_tasks.jsonl --out runs/main

eval-git-mcp:
	$(PYTHON) -m src.eval.run_eval --tasks data/eval_tasks.jsonl --out runs/main --git-mcp-autocommit --git-mcp-push --git-mcp-required

ablations:
	$(PYTHON) -m src.eval.run_ablations --tasks data/eval_tasks.jsonl

failure-traces:
	$(PYTHON) -m src.eval.analyze_failure_traces --trajectories runs/main/trajectories

clean:
	rm -rf runs/ .cache/ __pycache__/
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
