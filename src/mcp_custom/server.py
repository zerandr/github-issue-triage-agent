import os
import re
import json
import time
import httpx
import sqlite3

from typing import Any
from fastmcp import FastMCP

CACHE_PATH = "data/cache/triage_cache.sqlite"
GITHUB_API = "https://api.github.com"
RETRIABLE_HTTP = {408, 429, 500, 502, 503, 504}

mcp = FastMCP("github-triage-mcp")


def _db() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    conn = sqlite3.connect(CACHE_PATH)
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


def _headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "github-issue-triage-agent",
    }
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _http_get(
    url: str, *, params: dict[str, Any] | None = None, timeout_sec: int = 25
) -> dict[str, Any]:
    try:
        r = httpx.get(url, headers=_headers(), params=params, timeout=timeout_sec)
    except httpx.TimeoutException as e:
        return {"ok": False, "status": 408, "retriable": True, "error": f"timeout: {e}"}
    except httpx.RequestError as e:
        return {
            "ok": False,
            "status": 503,
            "retriable": True,
            "error": f"network_error: {e}",
        }

    if r.status_code >= 400:
        return {
            "ok": False,
            "status": r.status_code,
            "retriable": r.status_code in RETRIABLE_HTTP,
            "error": r.text[:1000],
        }

    return {"ok": True, "status": r.status_code, "retriable": False, "data": r.json()}


@mcp.tool()
def parse_issue_reference(issue_ref: str) -> dict[str, Any]:
    """Parse issue URL or owner/repo#number into structured repo + issue_number."""
    issue_ref = issue_ref.strip()

    short = re.match(r"^([\w.-]+/[\w.-]+)#(\d+)$", issue_ref)
    if short:
        return {"ok": True, "repo": short.group(1), "issue_number": int(short.group(2))}

    m = re.match(r"^https?://github\.com/([^/]+/[^/]+)/issues/(\d+)", issue_ref)
    if m:
        return {"ok": True, "repo": m.group(1), "issue_number": int(m.group(2))}

    return {
        "ok": False,
        "status": 400,
        "error": "Invalid issue reference format",
        "retriable": False,
    }


@mcp.tool()
def triage_cache_put(key: str, value_json: str) -> dict[str, Any]:
    """Store JSON string in local SQLite cache for deterministic repeated runs."""
    try:
        json.loads(value_json)
    except json.JSONDecodeError:
        return {
            "ok": False,
            "status": 400,
            "retriable": False,
            "error": "value_json is not valid JSON",
        }

    conn = _db()
    conn.execute(
        "INSERT INTO kv_cache(k, v, ts) VALUES(?, ?, ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v, ts=excluded.ts",
        (key, value_json, int(time.time())),
    )
    conn.commit()
    conn.close()
    return {"ok": True, "key": key}


@mcp.tool()
def triage_cache_get(key: str, max_age_sec: int = 86400) -> dict[str, Any]:
    """Read value from local SQLite cache if not stale."""
    conn = _db()
    row = conn.execute("SELECT v, ts FROM kv_cache WHERE k = ?", (key,)).fetchone()
    conn.close()
    if not row:
        return {"ok": True, "hit": False}
    v, ts = row
    stale = int(time.time()) - int(ts) > max_age_sec
    if stale:
        return {"ok": True, "hit": False, "stale": True, "ts": ts}
    return {"ok": True, "hit": True, "value_json": v, "ts": ts}


@mcp.tool()
def github_get_issue(repo: str, issue_number: int) -> dict[str, Any]:
    """Get issue or PR-thread metadata by repo and issue number from GitHub REST API."""
    url = f"{GITHUB_API}/repos/{repo}/issues/{issue_number}"
    res = _http_get(url, timeout_sec=20)
    if not res.get("ok"):
        return res
    return {"ok": True, "issue": res["data"]}


@mcp.tool()
def github_search_related_issues(
    repo: str, query: str, limit: int = 10
) -> dict[str, Any]:
    """Search issues in the same repo to find likely duplicates/related items."""
    if limit < 1 or limit > 30:
        return {
            "ok": False,
            "status": 400,
            "retriable": False,
            "error": "limit must be in [1, 30]",
        }

    q = f"repo:{repo} is:issue {query}"
    url = f"{GITHUB_API}/search/issues"
    res = _http_get(url, params={"q": q, "per_page": limit}, timeout_sec=25)
    if not res.get("ok"):
        return res
    payload = res["data"]
    return {
        "ok": True,
        "total_count": payload.get("total_count", 0),
        "items": payload.get("items", []),
    }


@mcp.tool()
def github_get_issue_timeline(
    repo: str, issue_number: int, per_page: int = 50
) -> dict[str, Any]:
    """Get timeline events for issue triage state summarization."""
    if per_page < 1 or per_page > 100:
        return {
            "ok": False,
            "status": 400,
            "retriable": False,
            "error": "per_page must be in [1, 100]",
        }

    url = f"{GITHUB_API}/repos/{repo}/issues/{issue_number}/timeline"
    res = _http_get(url, params={"per_page": per_page}, timeout_sec=25)
    if not res.get("ok"):
        return res
    return {"ok": True, "events": res["data"]}


if __name__ == "__main__":
    mcp.run()
