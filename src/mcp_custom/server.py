import json
import os
import sqlite3
import time
from typing import Any

import httpx
from fastmcp import FastMCP


class Server:
    CACHE_PATH = os.getenv("TRIAGE_CACHE_PATH", "data/cache/triage_cache.sqlite")
    GITHUB_API = "https://api.github.com"
    RETRIABLE_HTTP = {408, 429, 500, 502, 503, 504}

    @staticmethod
    def db() -> sqlite3.Connection:
        cache_dir = os.path.dirname(Server.CACHE_PATH)

        if cache_dir:
            os.makedirs(cache_dir, exist_ok=True)

        conn = sqlite3.connect(Server.CACHE_PATH)

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS kv_cache (
                k TEXT PRIMARY KEY,
                v TEXT NOT NULL,
                ts INTEGER NOT NULL
            )
            """
        )

        return conn

    @staticmethod
    def headers() -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "github-issue-triage-agent",
        }

        token = os.getenv("GITHUB_TOKEN")

        if token:
            headers["Authorization"] = f"Bearer {token}"

        return headers

    @staticmethod
    def http_get(
        url: str,
        *,
        params: dict[str, Any] | None = None,
        timeout_sec: int = 25,
    ) -> dict[str, Any]:
        try:
            response = httpx.get(
                url,
                headers=Server.headers(),
                params=params,
                timeout=timeout_sec,
            )
        except httpx.TimeoutException as exc:
            return {
                "ok": False,
                "status": 408,
                "retriable": True,
                "error": f"timeout: {exc}",
            }
        except httpx.RequestError as exc:
            return {
                "ok": False,
                "status": 503,
                "retriable": True,
                "error": f"network_error: {exc}",
            }

        if response.status_code >= 400:
            return {
                "ok": False,
                "status": response.status_code,
                "retriable": response.status_code in Server.RETRIABLE_HTTP,
                "error": response.text[:1000],
            }

        return {
            "ok": True,
            "status": response.status_code,
            "retriable": False,
            "data": response.json(),
        }

    @staticmethod
    def triage_cache_put(key: str, value_json: str) -> dict[str, Any]:
        try:
            json.loads(value_json)
        except json.JSONDecodeError:
            return {
                "ok": False,
                "status": 400,
                "retriable": False,
                "error": "value_json is not valid JSON",
            }

        conn = Server.db()

        conn.execute(
            """
            INSERT INTO kv_cache(k, v, ts)
            VALUES(?, ?, ?)
            ON CONFLICT(k)
            DO UPDATE SET v=excluded.v, ts=excluded.ts
            """,
            (key, value_json, int(time.time())),
        )

        conn.commit()
        conn.close()

        return {
            "ok": True,
            "key": key,
        }

    @staticmethod
    def triage_cache_get(key: str, max_age_sec: int = 86400) -> dict[str, Any]:
        conn = Server.db()

        row = conn.execute(
            "SELECT v, ts FROM kv_cache WHERE k = ?",
            (key,),
        ).fetchone()

        conn.close()

        if not row:
            return {
                "ok": True,
                "hit": False,
            }

        value_json, ts = row
        stale = int(time.time()) - int(ts) > max_age_sec

        if stale:
            return {
                "ok": True,
                "hit": False,
                "stale": True,
                "ts": ts,
            }

        return {
            "ok": True,
            "hit": True,
            "value_json": value_json,
            "ts": ts,
        }

    @staticmethod
    def github_get_issue(repo: str, issue_number: int) -> dict[str, Any]:
        url = f"{Server.GITHUB_API}/repos/{repo}/issues/{issue_number}"

        result = Server.http_get(url, timeout_sec=20)

        if not result.get("ok"):
            return result

        return {
            "ok": True,
            "issue": result["data"],
        }

    @staticmethod
    def github_search_related_issues(
        repo: str,
        query: str,
        limit: int = 10,
        sort: str | None = None,
        order: str = "desc",
    ) -> dict[str, Any]:
        if limit < 1 or limit > 30:
            return {
                "ok": False,
                "status": 400,
                "retriable": False,
                "error": "limit must be in [1, 30]",
            }

        if sort is not None and sort not in {"comments", "created", "updated"}:
            return {
                "ok": False,
                "status": 400,
                "retriable": False,
                "error": "sort must be one of comments, created, updated",
            }

        if order not in {"asc", "desc"}:
            return {
                "ok": False,
                "status": 400,
                "retriable": False,
                "error": "order must be one of asc, desc",
            }

        q = f"repo:{repo} is:issue {query}"
        url = f"{Server.GITHUB_API}/search/issues"

        params: dict[str, Any] = {
            "q": q,
            "per_page": limit,
        }

        if sort is not None:
            params["sort"] = sort
            params["order"] = order

        result = Server.http_get(
            url,
            params=params,
            timeout_sec=25,
        )

        if not result.get("ok"):
            return result

        payload = result["data"]

        return {
            "ok": True,
            "total_count": payload.get("total_count", 0),
            "items": payload.get("items", []),
        }

    @staticmethod
    def github_get_issue_timeline(
        repo: str,
        issue_number: int,
        per_page: int = 50,
    ) -> dict[str, Any]:
        if per_page < 1 or per_page > 100:
            return {
                "ok": False,
                "status": 400,
                "retriable": False,
                "error": "per_page must be in [1, 100]",
            }

        url = f"{Server.GITHUB_API}/repos/{repo}/issues/{issue_number}/timeline"

        result = Server.http_get(
            url,
            params={"per_page": per_page},
            timeout_sec=25,
        )

        if not result.get("ok"):
            return result

        return {
            "ok": True,
            "events": result["data"],
        }


mcp = FastMCP("github-triage-mcp")


@mcp.tool()
def triage_cache_put(key: str, value_json: str) -> dict[str, Any]:
    """Store JSON string in local SQLite cache for deterministic repeated runs."""
    return Server.triage_cache_put(key, value_json)


@mcp.tool()
def triage_cache_get(key: str, max_age_sec: int = 86400) -> dict[str, Any]:
    """Read value from local SQLite cache if not stale."""
    return Server.triage_cache_get(key, max_age_sec)


@mcp.tool()
def github_get_issue(repo: str, issue_number: int) -> dict[str, Any]:
    """Get issue metadata by repo and issue number from GitHub REST API."""
    return Server.github_get_issue(repo, issue_number)


@mcp.tool()
def github_search_related_issues(
    repo: str,
    query: str,
    limit: int = 10,
    sort: str | None = None,
    order: str = "desc",
) -> dict[str, Any]:
    """Search issues in the same repo to find likely duplicates or related issues."""
    return Server.github_search_related_issues(repo, query, limit, sort, order)


@mcp.tool()
def github_get_issue_timeline(
    repo: str,
    issue_number: int,
    per_page: int = 50,
) -> dict[str, Any]:
    """Get timeline events for issue triage state summarization."""
    return Server.github_get_issue_timeline(repo, issue_number, per_page)


if __name__ == "__main__":
    mcp.run()
