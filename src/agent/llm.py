from __future__ import annotations

import json
import os
from typing import Any

import httpx


def _env_or_default(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip()


OLLAMA_URL = _env_or_default("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = _env_or_default("OLLAMA_MODEL", "qwen2.5:7b-instruct")


SCHEMA_HINT = {
    "classification": "bug | feature request | question | documentation | duplicate | unknown",
    "justification": "short grounded text",
    "probable_code_areas": ["module/path hints"],
    "open_questions": ["string"],
    "decision_needed": "string",
    "current_state_summary": "string",
}


def build_prompt(payload: dict[str, Any]) -> str:
    return (
        "You are a GitHub issue triage assistant. Return ONLY valid JSON.\\n"
        "Never invent facts. If evidence is weak, use 'unknown' and explain uncertainty.\\n"
        f"Output schema hint: {json.dumps(SCHEMA_HINT, ensure_ascii=False)}\\n\\n"
        f"Input:\\n{json.dumps(payload, ensure_ascii=False)}"
    )


def triage_with_ollama(
    payload: dict[str, Any], timeout_sec: int = 60
) -> dict[str, Any]:
    prompt = build_prompt(payload)
    body = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0.1,
        },
    }

    try:
        r = httpx.post(f"{OLLAMA_URL}/api/generate", json=body, timeout=timeout_sec)
    except httpx.TimeoutException as e:
        return {"ok": False, "error": f"ollama timeout: {e}", "status": 408}
    except httpx.RequestError as e:
        return {"ok": False, "error": f"ollama request error: {e}", "status": 503}

    if r.status_code >= 400:
        return {"ok": False, "error": r.text[:1000], "status": r.status_code}

    data = r.json()
    raw = data.get("response", "")

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {
            "ok": False,
            "error": "ollama returned non-json response",
            "status": 422,
            "raw": raw[:1200],
        }

    return {
        "ok": True,
        "result": parsed,
        "usage": {"eval_count": data.get("eval_count", 0)},
    }
