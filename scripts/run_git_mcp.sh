#!/usr/bin/env bash
set -euo pipefail

# Run from project root:
# ./scripts/run_git_mcp.sh

if ! command -v npx >/dev/null 2>&1; then
  echo "Error: npx is not installed. Install Node.js/npm first." >&2
  exit 1
fi

export MCP_TRANSPORT_TYPE="${MCP_TRANSPORT_TYPE:-stdio}"
export MCP_RESPONSE_FORMAT="${MCP_RESPONSE_FORMAT:-json}"
export MCP_RESPONSE_VERBOSITY="${MCP_RESPONSE_VERBOSITY:-minimal}"
export GIT_BASE_DIR="${GIT_BASE_DIR:-$(pwd)}"
export GIT_SIGN_COMMITS="${GIT_SIGN_COMMITS:-false}"

npx @cyanheads/git-mcp-server@latest
