from __future__ import annotations

import asyncio
import json
import os
import time
import warnings
from pathlib import Path
from typing import Any


FILESYSTEM_MCP_COMMAND = os.getenv("FILESYSTEM_MCP_COMMAND", "npx")
FILESYSTEM_MCP_ARGS = os.getenv(
    "FILESYSTEM_MCP_ARGS",
    "-y @modelcontextprotocol/server-filesystem .",
).split()
USE_FILESYSTEM_MCP = os.getenv("USE_FILESYSTEM_MCP", "1") not in {
    "0",
    "false",
    "False",
    "no",
    "NO",
}


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value)


def audit_path(repo: str, issue_number: int, audit_dir: str = "audit/triage_results") -> str:
    repo_name = _safe_name(repo.replace("/", "__"))
    timestamp_ms = int(time.time() * 1000)
    return f"{audit_dir}/{timestamp_ms}_{repo_name}_{issue_number}.json"


async def _write_via_filesystem_mcp(path: str, content: str) -> Any:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    server_params = StdioServerParameters(
        command=FILESYSTEM_MCP_COMMAND,
        args=FILESYSTEM_MCP_ARGS,
        env=os.environ.copy(),
    )

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            available = {tool.name for tool in tools.tools}

            if "create_directory" in available:
                await session.call_tool(
                    "create_directory",
                    {"path": str(Path(path).parent)},
                )

            return await session.call_tool(
                "write_file",
                {
                    "path": path,
                    "content": content,
                },
            )


def _write_local(path: str, content: str) -> dict[str, Any]:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {"ok": True, "path": path, "fallback": "local"}


def write_audit_record(payload: dict[str, Any]) -> dict[str, Any]:
    path = audit_path(
        repo=str(payload.get("repo", "unknown")),
        issue_number=int(payload.get("issue_number", 0) or 0),
    )
    content = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

    if USE_FILESYSTEM_MCP:
        try:
            asyncio.run(_write_via_filesystem_mcp(path, content))
            return {"ok": True, "path": path, "via": "filesystem_mcp"}
        except Exception as exc:
            warnings.warn(
                "Filesystem MCP audit write failed. Falling back to local write. "
                f"Error: {exc}",
                RuntimeWarning,
            )

    return _write_local(path, content)
