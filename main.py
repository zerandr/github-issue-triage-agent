import argparse

from src.eval.build_tasks_from_repos import Builder
from src.eval.run_eval import EvalRunner, load_tasks


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--repos", default="pandas-dev/pandas,numpy/numpy,jax-ml/jax,pytorch/pytorch,scikit-learn/scikit-learn")
    parser.add_argument("--tasks", default="data/eval_tasks.jsonl")
    parser.add_argument("--out", default="data/eval_tasks.jsonl")
    parser.add_argument("--n", type=int, default=32)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--model", default="qwen2.5:7b-instruct")
    args = parser.parse_args()

    tasks_path = args.tasks

    if args.build:
        repos = [x.strip() for x in args.repos.split(",") if x.strip()]
        if not repos:
            raise ValueError("--build requires --repos with at least one owner/repo")
        builder = Builder()
        tasks = builder.build_tasks(repos=repos, n_tasks=args.n, seed=args.seed)
        builder.write_tasks(tasks=tasks, out_path=args.out)
        tasks_path = args.out

    tasks = load_tasks(tasks_path)
    runner = EvalRunner(model_name=args.model)
    runner.evaluate(tasks)
    print("Wrote reports/eval_summary.json and reports/trajectories/*.json")


if __name__ == "__main__":
    main()
