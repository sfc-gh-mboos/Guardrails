# IORails transform playground

Local demo for catalog input/output **transform** rails (rewrite/mask), not
block-only `self check` rails.

It uses the same SECRET stub as `tests/guardrails/test_cross_engine_rail_equivalence.py`
and `tests/guardrails/test_iorails_transforms.py`: `SECRET` becomes `[REDACTED]`.
The live Presidio NER path is not invoked.

## Run

From the repository root:

```bash
uv run --locked python examples/iorails_transforms/app.py
```

Then open [http://127.0.0.1:8765](http://127.0.0.1:8765).

## What to verify

The page lists the same cases the automated tests cover:

- Input rewrite on `check` / `check_async` (`status: modified`, `SECRET` → `[REDACTED]`)
- Output rewrite on `check` / `check_async`
- Cross-engine `check` + `generate` parity (LLMRails vs IORails)
- IORails `generate` output rewrite
- Streaming: rewritten prompt reaches the model; already-emitted chunks are not rewritten

Engine agreement is based on `check` status/content and `generate` assistant
text. `prompt_sent_to_model` is IORails-only and is shown for that engine; it
is not used as an equality check against LLMRails.
