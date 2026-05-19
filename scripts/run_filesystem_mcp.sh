#!/usr/bin/env bash
set -euo pipefail

# Run from project root:
# ./scripts/run_filesystem_mcp.sh

if ! command -v npx >/dev/null 2>&1; then
  echo "Error: npx is not installed. Install Node.js first." >&2
  exit 1
fi

# Restrict filesystem MCP access to the current project directory.
npx -y @modelcontextprotocol/server-filesystem "$(pwd)"
