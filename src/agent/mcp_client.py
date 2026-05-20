"""
Small MCP client wrapper used by the LangGraph agent.

The agent should import GitHub/cache tools from this module instead of importing
functions directly from src.mcp_custom.server. This makes the MCP boundary clear.

For classroom/demo reliability this supports:
1. MCP stdio mode via python -m src.mcp_custom.server
2. Local fallback mode if MCP setup fails
"""

from __future__ import annotations

import asyncio
import os
import sys
import warnings
from typing import Any, Dict, Optional


USE_MCP = os.getenv("USE_MCP", "1") not in {"0", "false", "False", "no", "NO"}
MCP_SERVER_COMMAND = os.getenv("MCP_SERVER_COMMAND", sys.executable)
MCP_SERVER_ARGS = os.getenv("MCP_SERVER_ARGS", "-m src.mcp_custom.server").split()


async def _call_mcp_tool_async(tool_name: str, arguments: Dict[str, Any]) -> Any:
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except Exception as exc:
        raise RuntimeError(
            "MCP Python SDK is not installed or has incompatible imports. "
            "Install it with `pip install mcp`, or set USE_MCP=0 for local fallback."
        ) from exc

    server_params = StdioServerParameters(
        command=MCP_SERVER_COMMAND,
        args=MCP_SERVER_ARGS,
        env=os.environ.copy(),
    )

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)

            if hasattr(result, "content"):
                content = result.content

                if len(content) == 1:
                    item = content[0]

                    if hasattr(item, "text"):
                        return item.text

                    if hasattr(item, "data"):
                        return item.data

                return content

            return result


def _call_mcp_tool(tool_name: str, arguments: Dict[str, Any]) -> Any:
    try:
        return asyncio.run(_call_mcp_tool_async(tool_name, arguments))
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_call_mcp_tool_async(tool_name, arguments))
        finally:
            loop.close()


def _call_local_tool(tool_name: str, arguments: Dict[str, Any]) -> Any:
    from src.mcp_custom import server as local_server

    mapping = {
        "github_get_issue": getattr(local_server, "github_get_issue", None),
        "github_get_issue_timeline": getattr(
            local_server, "github_get_issue_timeline", None
        ),
        "github_search_related_issues": getattr(
            local_server, "github_search_related_issues", None
        ),
        "triage_cache_get": getattr(local_server, "triage_cache_get", None),
        "triage_cache_put": getattr(local_server, "triage_cache_put", None),
    }

    fn = mapping.get(tool_name)
    if fn is None:
        raise ValueError(f"Unknown local fallback tool: {tool_name}")

    return fn(**arguments)


def call_tool(tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> Any:
    arguments = arguments or {}

    if USE_MCP:
        try:
            if tool_name.startswith("github_"):
                print(f"[mcp] GitHub tool via MCP: {tool_name}", file=sys.stderr)

            return _call_mcp_tool(tool_name, arguments)
        except Exception as exc:
            warnings.warn(
                f"MCP call failed for tool `{tool_name}`. "
                f"Falling back to local function call. Error: {exc}",
                RuntimeWarning,
            )

    return _call_local_tool(tool_name, arguments)


def github_get_issue(repo: str, issue_number: int) -> Any:
    return call_tool(
        "github_get_issue",
        {
            "repo": repo,
            "issue_number": issue_number,
        },
    )


def github_get_issue_timeline(repo: str, issue_number: int) -> Any:
    return call_tool(
        "github_get_issue_timeline",
        {
            "repo": repo,
            "issue_number": issue_number,
        },
    )


def github_search_related_issues(
    repo: str,
    query: str,
    limit: int = 5,
    sort: str | None = None,
    order: str = "desc",
) -> Any:
    arguments: dict[str, Any] = {
        "repo": repo,
        "query": query,
        "limit": limit,
    }

    if sort is not None:
        arguments["sort"] = sort
        arguments["order"] = order

    return call_tool(
        "github_search_related_issues",
        arguments,
    )


def triage_cache_get(key: str, max_age_sec: int = 86400) -> Any:
    return call_tool(
        "triage_cache_get",
        {
            "key": key,
            "max_age_sec": max_age_sec,
        },
    )


def triage_cache_put(key: str, value_json: str) -> Any:
    return call_tool(
        "triage_cache_put",
        {
            "key": key,
            "value_json": value_json,
        },
    )
