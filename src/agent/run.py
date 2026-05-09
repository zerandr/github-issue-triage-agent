from src.eval.run_eval import EvalRunner


def run(repo: str, issue_number: int) -> dict:
    runner = EvalRunner(model_name="single-run")
    return runner.run_single(
        repo=repo,
        issue_number=issue_number,
        thread_id=f"{repo}#{issue_number}",
    )


if __name__ == "__main__":
    import json
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--issue", required=True, type=int)
    args = parser.parse_args()
    print(json.dumps(run(args.repo, args.issue), ensure_ascii=False, indent=2))
