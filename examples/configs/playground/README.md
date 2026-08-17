# Playground demo

Local, no-API-key configuration for the server prompt playground.

It uses catalog regex rails, a PII mask action, and a canned `playground_echo` model:

- Input rails block jailbreak phrasing and a few harmful requests.
- The `mask pii` rail rewrites SSN and email values instead of blocking them.
- Output rails block the word `confidential`.
- The echo model answers normally, except when the prompt asks it to include `confidential`.

Start the server from the repository root:

```bash
nemoguardrails server --config examples/configs --default-config-id playground
```

Open `http://localhost:8000/playground`. The playground keeps the configuration's main model, so the request does not replace `playground_echo` with the server's `MAIN_MODEL_ENGINE`.
