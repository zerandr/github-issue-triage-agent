.PHONY: install mcp-custom mcp-filesystem run-one eval clean

install:
	pip install -r requirements.txt

mcp-custom:
	python -m src.mcp_custom.server

mcp-filesystem:
	./scripts/run_filesystem_mcp.sh

run-one:
	python -m src.agent.run --repo "$(REPO)" --issue "$(ISSUE)"

eval:
	python -m src.eval.run_eval --tasks data/eval_tasks.jsonl --out runs/main

clean:
	rm -rf runs/ .cache/ __pycache__/
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete