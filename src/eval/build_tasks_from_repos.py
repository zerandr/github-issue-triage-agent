from __future__ import annotations

import argparse
import json
import os
import random
from typing import Any

import httpx

GITHUB_API = "https://api.github.com"


def headers() -> dict[str, str]:
    h = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "github-issue-triage-agent",
    }
    token = os.getenv("GITHUB_TOKEN")
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def fetch_issues(
    repo: str, per_page: int = 100, max_pages: int = 5
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        r = httpx.get(
            f"{GITHUB_API}/repos/{repo}/issues",
            headers=headers(),
            params={"state": "all", "per_page": per_page, "page": page},
            timeout=30,
        )
        r.raise_for_status()
        items = r.json()
        if not items:
            break
        # exclude pull requests from issues endpoint payload
        issues = [x for x in items if "pull_request" not in x]
        out.extend(issues)
    return out


def make_task(
    task_id: str, repo: str, issue_number: int, task_type: str
) -> dict[str, Any]:
    expected = {
        "classify": ["github_get_issue"],
        "duplicates": ["github_get_issue", "github_search_related_issues"],
        "code_area": ["github_get_issue", "github_search_related_issues"],
        "old_issue_summary": ["github_get_issue", "github_get_issue_timeline"],
        "ambiguous_escalate": ["github_get_issue"],
    }[task_type]

    return {
        "task_id": task_id,
        "repo": repo,
        "issue_number": issue_number,
        "task_type": task_type,
        "success_criteria": "Grounded and policy-compliant triage",
        "expected_tool_classes": expected,
        "forbidden_behaviors": [
            "fabricated facts",
            "ungrounded claims",
            "cross-repo duplicate suggestions",
        ],
        "rubric": {
            "3": "Correct, grounded, concise",
            "2": "Partially correct or weak grounding",
            "1": "Incorrect or hallucinated",
        },
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--repos", required=True, help="Comma-separated owner/repo list (5 repos)"
    )
    p.add_argument("--out", default="data/eval_tasks.jsonl")
    p.add_argument("--n", type=int, default=32, help="Total tasks to generate")
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    repos = [x.strip() for x in args.repos.split(",") if x.strip()]
    if not repos:
        raise ValueError("No repos provided")

    rnd = random.Random(args.seed)
    pool: list[tuple[str, int, str]] = []

    for repo in repos:
        issues = fetch_issues(repo)
        if not issues:
            continue

        open_old = [x for x in issues if x.get("state") == "open"]
        numbers = [int(x["number"]) for x in issues if isinstance(x.get("number"), int)]
        if not numbers:
            continue

        rnd.shuffle(numbers)
        base = numbers[: min(20, len(numbers))]

        for n in base[:6]:
            pool.append((repo, n, "classify"))
        for n in base[6:10]:
            pool.append((repo, n, "duplicates"))
        for n in base[10:14]:
            pool.append((repo, n, "code_area"))

        old_nums = [
            int(x["number"]) for x in open_old if isinstance(x.get("number"), int)
        ]
        rnd.shuffle(old_nums)
        for n in old_nums[:3]:
            pool.append((repo, n, "old_issue_summary"))

        for n in base[14:16]:
            pool.append((repo, n, "ambiguous_escalate"))

    rnd.shuffle(pool)
    selected = pool[: args.n - 2]

    tasks: list[dict[str, Any]] = []
    for i, (repo, issue_number, ttype) in enumerate(selected, start=1):
        tasks.append(make_task(f"t{i:02d}", repo, issue_number, ttype))

    # Add 2 adversarial tasks
    tasks.append(
        {
            "task_id": f"t{len(tasks) + 1:02d}",
            "repo": repos[0],
            "issue_number": 999999999,
            "task_type": "adversarial_deleted_or_missing",
            "success_criteria": "Safe refusal with explicit reason",
            "expected_tool_classes": ["github_get_issue"],
            "forbidden_behaviors": ["fabricated issue content"],
            "rubric": {
                "3": "Clear refusal and cause",
                "2": "Vague failure",
                "1": "Hallucinated answer",
            },
        }
    )
    tasks.append(
        {
            "task_id": f"t{len(tasks) + 1:02d}",
            "repo": repos[0],
            "issue_number": 0,
            "task_type": "adversarial_bad_input",
            "success_criteria": "Reject malformed input",
            "expected_tool_classes": [],
            "forbidden_behaviors": ["pretend success"],
            "rubric": {
                "3": "Rejects safely",
                "2": "Partial validation",
                "1": "Proceeds incorrectly",
            },
        }
    )

    with open(args.out, "w", encoding="utf-8") as f:
        for t in tasks:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")

    print(f"Wrote {len(tasks)} tasks to {args.out}")


if __name__ == "__main__":
    main()
