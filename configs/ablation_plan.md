# Ablation Study

Run with:

```bash
make ablations
```

The runner keeps `data/eval_tasks.jsonl` fixed and writes:

- `reports/ablations/ablation_results.json`
- `reports/ablations/ablation_study.md`
- per-variant outputs under `runs/ablations/`

Variants:

- Baseline: primary model, strict grounding prompt, baseline graph.
- Model ablation: same graph/prompt with the secondary model.
- Prompt/tool-description ablation: same graph/model with a permissive prompt.
- Graph ablation: same model/prompt with `human_gate` bypassed.
