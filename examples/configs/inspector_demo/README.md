# Inspector demo

Offline guardrails configuration for the rail inspector UI.

The demo uses keyword input and output rails plus a canned model, so it does
not call a live LLM or require API keys.

## Rails

- `check jailbreak input` blocks jailbreak-style phrasing.
- `check content safety input` blocks a small set of harmful-request phrases.
- `mask pii on input` replaces emails and SSNs with `[EMAIL]` / `[SSN]`.
- `check content safety output` blocks replies that leak `SECRET-TOKEN-42`.
- `mask pii on output` masks the same PII patterns in the model reply.

## Run

```bash
nemoguardrails server --config examples/configs/inspector_demo
```

Open http://localhost:8000/inspect and use the example prompt bank.
Each prompt is labeled with the rail impact you should see.
