# Playground demo

Local, no-API-key configuration for the server prompt playground.

It uses catalog regex rails plus a canned `playground_echo` model:

- Input rails block jailbreak phrasing, SSN-like numbers, and a few harmful requests.
- Output rails block the word `confidential`.
- The echo model answers normally, except when the prompt asks it to include `confidential`.

Start the server from the repository root:

```bash
nemoguardrails server --config examples/configs --default-config-id playground
```

Open `http://localhost:8000/playground`. Keep **Use the configuration's main model** checked so the request does not replace `playground_echo` with the server's `MAIN_MODEL_ENGINE`.
