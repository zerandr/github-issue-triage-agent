# Ablation Study

All variants use the same evaluation set. Each row is generated from the JSON summary written by `src.eval.run_eval`.

| variant | status | n_tasks | mean_score_3pt | tool_selection_accuracy | mean_steps | mean_tool_calls | mean_latency_seconds | total_tokens | total_estimated_usd_cost | total_ungrounded_claims | total_hallucinated_tool_args | total_unnecessary_tool_calls |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| baseline | ok | 33 | 3.0 | 1.0 | 6.424 | 0.909 | 21.286 | 3713 | 0.0 | 0 | 0 | 44 |
| model_secondary | ok | 33 | 3.0 | 1.0 | 6.424 | 0.909 | 18.857 | 2997 | 0.0 | 0 | 0 | 44 |
| prompt_permissive | ok | 33 | 3.0 | 1.0 | 6.424 | 0.909 | 20.858 | 3212 | 0.0 | 0 | 0 | 44 |
| graph_no_human_gate | ok | 33 | 3.0 | 1.0 | 6.697 | 1.0 | 27.534 | 4137 | 0.0 | 0 | 0 | 47 |

## Variants

### baseline
Baseline graph, strict grounding prompt, primary model.

```json
{
  "OLLAMA_MODEL": "qwen2.5:7b-instruct",
  "TRIAGE_PROMPT_VARIANT": "strict",
  "TRIAGE_GRAPH_VARIANT": "baseline"
}
```

### model_secondary
Same graph and prompt, secondary model.

```json
{
  "OLLAMA_MODEL": "llama3:latest",
  "TRIAGE_PROMPT_VARIANT": "strict",
  "TRIAGE_GRAPH_VARIANT": "baseline"
}
```

### prompt_permissive
Same graph and model, materially weaker prompt/tool discipline.

```json
{
  "OLLAMA_MODEL": "qwen2.5:7b-instruct",
  "TRIAGE_PROMPT_VARIANT": "permissive",
  "TRIAGE_GRAPH_VARIANT": "baseline"
}
```

### graph_no_human_gate
Same model and prompt, but ambiguous cases bypass HITL routing.

```json
{
  "OLLAMA_MODEL": "qwen2.5:7b-instruct",
  "TRIAGE_PROMPT_VARIANT": "strict",
  "TRIAGE_GRAPH_VARIANT": "no_human_gate"
}
```
