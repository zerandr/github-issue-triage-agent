#!/usr/bin/env bash
set -euo pipefail

# Run from project root:
# ./scripts/run_custom_mcp.sh

export PYTHONPATH="${PYTHONPATH:-}:$(pwd)"

if [ -f ".env" ]; then
  set -a
  source .env
  set +a
fi

python -m src.mcp_custom.server