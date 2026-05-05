```mermaid
graph TD
  A[bootstrap] --> B[fetch_issue]
  B -->|tool_error| I[finalize]
  B -->|ok| C[gather_related]
  C --> D[classify_issue]
  D -->|unknown/ambiguous| E[human_gate interrupt]
  D -->|confident| F[infer_code_areas]
  E --> F
  F --> G[summarize_old_issue]
  G --> H[llm_triage (Qwen via Ollama)]
  H --> I[finalize]
```
