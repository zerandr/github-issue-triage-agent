import os
import json
import httpx
import random

from typing import Any

from src.config.config import Config


class Builder:
    def __init__(self) -> None:
        self.config = Config()

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

    def fetch_issues(self, repo: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for page in range(1, 6):
            response = httpx.get(
                f"{self.config.github_api}/repos/{repo}/issues",
                headers=self.headers(),
                params={"state": "all", "per_page": 100, "page": page},
                timeout=30,
            )
            response.raise_for_status()
            items = response.json()
            if not items:
                break
            out.extend([x for x in items if "pull_request" not in x])
        return out

    def build_tasks(
        self, repos: list[str], n_tasks: int, seed: int = 42
    ) -> list[dict[str, Any]]:
        rnd = random.Random(seed)
        pool: list[tuple[str, int, str]] = []
        for repo in repos:
            issues = self.fetch_issues(repo)
            numbers = [
                int(x["number"]) for x in issues if isinstance(x.get("number"), int)
            ]
            if not numbers:
                continue
            open_numbers = [
                int(x["number"])
                for x in issues
                if x.get("state") == "open" and isinstance(x.get("number"), int)
            ]
            rnd.shuffle(numbers)
            base = numbers[: min(20, len(numbers))]
            for n in base[:6]:
                pool.append((repo, n, "classify"))
            for n in base[6:10]:
                pool.append((repo, n, "duplicates"))
            for n in base[10:14]:
                pool.append((repo, n, "code_area"))
            rnd.shuffle(open_numbers)
            for n in open_numbers[:3]:
                pool.append((repo, n, "old_issue_summary"))
            for n in base[14:16]:
                pool.append((repo, n, "ambiguous_escalate"))

        rubric = {
            "3": "Correct, grounded, concise",
            "2": "Partially correct or weak grounding",
            "1": "Incorrect or hallucinated",
        }
        expected = {
            "classify": ["github_get_issue"],
            "duplicates": ["github_get_issue", "github_search_related_issues"],
            "code_area": ["github_get_issue", "github_search_related_issues"],
            "old_issue_summary": ["github_get_issue", "github_get_issue_timeline"],
            "ambiguous_escalate": ["github_get_issue"],
        }

        rnd.shuffle(pool)
        tasks = []
        for i, (repo, issue_number, task_type) in enumerate(pool[:n_tasks], start=1):
            tasks.append(
                {
                    "task_id": f"t{i:02d}",
                    "repo": repo,
                    "issue_number": issue_number,
                    "task_type": task_type,
                    "success_criteria": "Grounded and policy-compliant triage",
                    "expected_tool_classes": expected[task_type],
                    "forbidden_behaviors": [
                        "fabricated facts",
                        "ungrounded claims",
                        "cross-repo duplicate suggestions",
                    ],
                    "rubric": rubric,
                }
            )

        return tasks

    @staticmethod
    def write_tasks(tasks: list[dict[str, Any]], out_path: str) -> None:
        with open(out_path, "w", encoding="utf-8") as file:
            for task in tasks:
                file.write(json.dumps(task, ensure_ascii=False) + "\n")
