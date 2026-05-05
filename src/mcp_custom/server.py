from __future__ import annotations

import os
import time
import sqlite3
from typing import Any

import httpx
from fastmcp import FastMCP

CACHE_PATH = "data/cache/triage_cache.sqlite"
GITHUB_API = "https://api.github.com"

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
    headers = {"Accept": "application/vnd.github+json"}
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


@mcp.tool()
def triage_cache_put(key: str, value_json: str) -> dict[str, Any]:
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
    conn = _db()
    row = conn.execute("SELECT v, ts FROM kv_cache WHERE k = ?", (key,)).fetchone()
    conn.close()
    if not row:
        return {"hit": False}
    v, ts = row
    if int(time.time()) - int(ts) > max_age_sec:
        return {"hit": False, "stale": True}
    return {"hit": True, "value_json": v, "ts": ts}


@mcp.tool()
def github_get_issue(repo: str, issue_number: int) -> dict[str, Any]:
    url = f"{GITHUB_API}/repos/{repo}/issues/{issue_number}"
    r = httpx.get(url, headers=_headers(), timeout=20)
    if r.status_code >= 400:
        return {"ok": False, "status": r.status_code, "error": r.text}
    return {"ok": True, "issue": r.json()}


@mcp.tool()
def github_search_related_issues(
    repo: str, query: str, limit: int = 10
) -> dict[str, Any]:
    q = f"repo:{repo} is:issue {query}"
    url = f"{GITHUB_API}/search/issues"
    r = httpx.get(
        url, headers=_headers(), params={"q": q, "per_page": limit}, timeout=25
    )
    if r.status_code >= 400:
        return {"ok": False, "status": r.status_code, "error": r.text}
    payload = r.json()
    items = payload.get("items", [])
    return {"ok": True, "total_count": payload.get("total_count", 0), "items": items}


@mcp.tool()
def github_get_issue_timeline(
    repo: str, issue_number: int, per_page: int = 50
) -> dict[str, Any]:
    url = f"{GITHUB_API}/repos/{repo}/issues/{issue_number}/timeline"
    headers = _headers()
    headers["Accept"] = "application/vnd.github+json"
    r = httpx.get(url, headers=headers, params={"per_page": per_page}, timeout=25)
    if r.status_code >= 400:
        return {"ok": False, "status": r.status_code, "error": r.text}
    return {"ok": True, "events": r.json()}


if __name__ == "__main__":
    mcp.run()
