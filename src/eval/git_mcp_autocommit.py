from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any


DEFAULT_GIT_MCP_COMMAND = "npx"
DEFAULT_GIT_MCP_ARGS = ["@cyanheads/git-mcp-server@latest"]


def json_artifacts(directory: Path) -> list[Path]:
    if not directory.exists():
        return []

    return sorted(path for path in directory.rglob("*.json") if path.is_file())


def project_relative(path: Path, repo_root: Path) -> str:
    return path.resolve().relative_to(repo_root.resolve()).as_posix()


def tool_args(schema: dict[str, Any], **values: Any) -> dict[str, Any]:
    properties = schema.get("properties", {})
    args: dict[str, Any] = {}

    aliases = {
        "repo_path": ["repo_path", "repoPath", "repositoryPath", "workingDir", "cwd"],
        "path": ["path", "repoPath", "repositoryPath", "workingDir", "cwd"],
        "files": ["files", "paths", "filePaths", "pathspecs"],
        "message": ["message", "commitMessage"],
        "remote": ["remote", "remoteName"],
        "branch": ["branch", "branchName"],
        "force": ["force", "forcePush"],
        "set_upstream": ["set_upstream", "setUpstream"],
    }

    for value_key, candidates in aliases.items():
        if value_key not in values:
            continue

        if values[value_key] is None:
            continue

        for candidate in candidates:
            if candidate in properties:
                args[candidate] = values[value_key]
                break

    return args


def parse_mcp_content(result: Any) -> Any:
    if not hasattr(result, "content"):
        return result

    content = result.content
    if len(content) != 1:
        return content

    item = content[0]
    text = getattr(item, "text", None)

    if not isinstance(text, str):
        return getattr(item, "data", item)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


class GitMcpClient:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root.resolve()
        self.command = os.getenv("GIT_MCP_COMMAND", DEFAULT_GIT_MCP_COMMAND)
        self.args = os.getenv("GIT_MCP_ARGS", " ".join(DEFAULT_GIT_MCP_ARGS)).split()

    def env(self) -> dict[str, str]:
        env = os.environ.copy()
        env.setdefault("MCP_TRANSPORT_TYPE", "stdio")
        env.setdefault("MCP_RESPONSE_FORMAT", "json")
        env.setdefault("MCP_RESPONSE_VERBOSITY", "minimal")
        env.setdefault("GIT_BASE_DIR", str(self.repo_root))
        env.setdefault("GIT_DEFAULT_PATH", str(self.repo_root))
        env.setdefault("GIT_SIGN_COMMITS", "false")
        return env

    async def run(
        self,
        files: list[str],
        message: str,
        *,
        push: bool,
        remote: str,
        branch: str | None,
    ) -> dict[str, Any]:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        server_params = StdioServerParameters(
            command=self.command,
            args=self.args,
            env=self.env(),
        )

        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                tools_response = await session.list_tools()
                schemas = {
                    tool.name: getattr(tool, "inputSchema", {}) or {}
                    for tool in tools_response.tools
                }

                required = ["git_add", "git_commit"]
                if push:
                    required.append("git_push")

                missing = [tool for tool in required if tool not in schemas]
                if missing:
                    return {
                        "ok": False,
                        "error": f"Git MCP server is missing tools: {missing}",
                        "available_tools": sorted(schemas),
                    }

                if "git_set_working_dir" in schemas:
                    await session.call_tool(
                        "git_set_working_dir",
                        tool_args(
                            schemas["git_set_working_dir"],
                            path=str(self.repo_root),
                            repo_path=str(self.repo_root),
                        ),
                    )

                add_result = await session.call_tool(
                    "git_add",
                    tool_args(
                        schemas["git_add"],
                        repo_path=str(self.repo_root),
                        files=files,
                        force=True,
                    ),
                )

                commit_result = await session.call_tool(
                    "git_commit",
                    tool_args(
                        schemas["git_commit"],
                        repo_path=str(self.repo_root),
                        message=message,
                    ),
                )

                push_result = None
                if push:
                    push_result = await session.call_tool(
                        "git_push",
                        tool_args(
                            schemas["git_push"],
                            repo_path=str(self.repo_root),
                            remote=remote,
                            branch=branch,
                            force=False,
                            set_upstream=False,
                        ),
                    )

                return {
                    "ok": True,
                    "files": files,
                    "git_add": parse_mcp_content(add_result),
                    "git_commit": parse_mcp_content(commit_result),
                    "git_push": parse_mcp_content(push_result) if push_result else None,
                }


def commit_json_artifacts(
    directory: Path,
    *,
    repo_root: Path,
    message: str,
    push: bool,
    remote: str = "origin",
    branch: str | None = None,
) -> dict[str, Any]:
    files = [
        project_relative(path, repo_root)
        for path in json_artifacts(directory)
    ]

    if not files:
        return {
            "ok": True,
            "skipped": True,
            "reason": f"No JSON files found in {directory}",
        }

    client = GitMcpClient(repo_root)
    return asyncio.run(
        client.run(
            files,
            message,
            push=push,
            remote=remote,
            branch=branch,
        )
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Commit JSON artifacts through Git MCP.")
    parser.add_argument("--dir", default="runs/main/trajectories")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--message", default="Auto-commit eval JSON artifacts")
    parser.add_argument("--push", action="store_true")
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--branch", default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = commit_json_artifacts(
        Path(args.dir),
        repo_root=Path(args.repo_root),
        message=args.message,
        push=args.push,
        remote=args.remote,
        branch=args.branch,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
