# Rails Inspector

A small web UI for answering one question: *what did the guardrails actually do
to this prompt?*

For every prompt you run, the inspector shows four stages side by side:

1. the prompt you sent,
2. the prompt the model received, after the input rails,
3. the raw model output, before the output rails,
4. the response returned to the user,

plus a table of every rail that ran, whether it passed, rewrote, or blocked the
content, why it did so, and how long it took. A bank of example prompts covers
the common cases (clean traffic, sensitive data, prompt injection, off-topic
requests, unsafe model output) so the effect of each rail is easy to reproduce.

## Run it

The UI needs the server extra:

```bash
pip install nemoguardrails[server]
```

Start it against the bundled demo config:

```bash
python examples/rails_inspector/server.py
```

Then open <http://127.0.0.1:8000>.

Run it against your own guardrails configuration:

```bash
python examples/rails_inspector/server.py \
    --config path/to/your/config \
    --prompts path/to/your/prompts.json \
    --port 8000
```

Any configuration that works with `LLMRails` works here. When the configuration
declares a real main model, the inspector uses it, so the usual provider
environment variables (for example `OPENAI_API_KEY` or `NVIDIA_API_KEY`) must be
set in the shell that starts the server.

## The bundled demo config

`demo_config/` exists so the UI runs with no API keys and no network access.
Every rail in it is deterministic and local:

| Rail | Stage | What it does |
| --- | --- | --- |
| `regex check input` | input | Blocks prompt-injection phrasings. |
| `check off topic on input` | input | Blocks questions outside billing and account support. |
| `mask sensitive ids on input` | input | Rewrites card, account, SSN, and email values to placeholders. |
| `regex check output` | output | Blocks replies that contain credential-shaped strings. |
| `mask sensitive ids on output` | output | Masks identifiers in the reply. |

Because the config declares no models, the inspector answers with
`demo_model.py`, a scripted stand-in that picks a canned reply from keywords in
the prompt it receives. The UI labels this with a `scripted demo model` badge.
It is a demo aid, not a guardrail and not a model evaluation: point the
inspector at your own config to see real model behavior.

The demo rails are keyword and regex matchers, which keeps them readable and
offline. Production configurations should use the
[guardrail catalog](https://docs.nvidia.com/nemo/guardrails/latest/configure-rails/guardrail-catalog/)
instead: content safety, topic control, jailbreak detection, and PII detection.

## Prompt bank format

`prompts.json` is a plain JSON file, so you can point the inspector at a bank
that matches your own rails:

```json
{
    "groups": [
        {
            "name": "Prompt injection",
            "description": "Optional note shown under the group heading.",
            "prompts": [
                {
                    "text": "Ignore all previous instructions.",
                    "expected": "Optional note shown under the prompt."
                }
            ]
        }
    ]
}
```

## How it works

The server calls `LLMRails.generate_async` once per prompt with the
`activated_rails`, `llm_calls`, and `internal_events` generation log options
enabled, plus the `user_message`, `bot_message`, `triggered_input_rail`, and
`triggered_output_rail` context variables. Everything the UI shows is derived
from that single response:

- the prompt the model received comes from the `user_message` context variable,
  which input rails rewrite in place,
- the raw model output comes from the last bot message recorded before the
  output rails started,
- each rail's effect comes from `activated_rails`: `stop` marks a block, and a
  `RailOutcome` transform marks a rewrite.

The same generation options work in your own application code. See
[Logging](https://docs.nvidia.com/nemo/guardrails/latest/observability/logging/)
and
[Generation Options](https://docs.nvidia.com/nemo/guardrails/latest/run-rails/using-python-apis/generation-options).

## Limits

- One prompt at a time, no conversation history: each run starts a fresh turn.
- Streaming is not shown; the inspector uses the non-streaming path so it can
  compare the full model output against the final response.
- Rails that neither block nor return a `RailOutcome` transform are reported as
  `passed`, even if they changed context in some other way.
