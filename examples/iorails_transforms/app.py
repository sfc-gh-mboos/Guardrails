# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Playground to compare LLMRails vs IORails input/output transforms.

Run from the repo root:

    uv run --locked python examples/iorails_transforms/app.py

Then open http://127.0.0.1:8765

The catalog ``mask sensitive data`` rails are stubbed so ``SECRET`` becomes
``[REDACTED]``, matching ``tests/guardrails/test_cross_engine_rail_equivalence.py``.
No Presidio, and no live model calls.
"""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any, Literal
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from nemoguardrails.actions.rail_outcome import RailOutcome, TransformTarget
from nemoguardrails.guardrails.guardrails_types import RailDirection
from nemoguardrails.guardrails.iorails import IORails
from nemoguardrails.guardrails.model_engine import ModelEngine
from nemoguardrails.rails.llm.config import RailsConfig
from nemoguardrails.testing.chat_harness import TestChat
from nemoguardrails.types import LLMResponse

HERE = Path(__file__).resolve().parent
INDEX = HERE / "static" / "index.html"

MAIN_MODEL = {"type": "main", "engine": "nim", "model": "meta/llama-3.3-70b-instruct"}
SAFE_REPLY = "Safe reply."
SECRET_OUTPUT = "here is SECRET"


def _config(*, input_rails: bool, output_rails: bool) -> dict:
    """Catalog mask-rail config both engines load."""
    rails: dict[str, Any] = {
        "config": {
            "sensitive_data_detection": {
                "input": {"entities": ["PERSON"]},
                "output": {"entities": ["PERSON"]},
            }
        }
    }
    if input_rails:
        rails["input"] = {"flows": ["mask sensitive data on input"]}
    if output_rails:
        rails["output"] = {"flows": ["mask sensitive data on output"]}
    return {"models": [copy.deepcopy(MAIN_MODEL)], "rails": rails}


async def _redact(source: str, text: str, config: Any, **kwargs: Any) -> RailOutcome:
    """Catalog-shaped mask action: rewrite SECRET in the bound turn."""
    if "SECRET" not in text:
        return RailOutcome.allow()
    rewritten = text.replace("SECRET", "[REDACTED]")
    target = TransformTarget.USER_MESSAGE if source == "input" else TransformTarget.BOT_MESSAGE
    return RailOutcome.transform([(target, rewritten)])


def _install_iorails_action(iorails: IORails, flow: str, direction: RailDirection) -> None:
    """Replace the compiled catalog action so the playground does not call Presidio."""
    iorails.rails_manager._rails[(direction, flow)]._action = _redact


def _stub_main_chat(iorails: IORails, content: str, seen: list[list[dict]]) -> None:
    """Replace the main model's chat completion and record the messages it received."""

    async def _chat(messages, **_kwargs):
        seen.append(copy.deepcopy(messages))
        return LLMResponse(content=content)

    for name, engine in iorails.engine_registry._engines.items():
        if isinstance(engine, ModelEngine) and name == "main":
            engine.chat_completion = AsyncMock(side_effect=_chat)


def _serialize_check(result: Any) -> dict[str, Any]:
    return {
        "status": result.status.value,
        "content": result.content,
        "rail": result.rail,
        "transformed_content": result.content if result.status.value == "modified" else None,
    }


class CompareRequest(BaseModel):
    text: str = Field(..., min_length=1)
    mode: Literal["input", "output", "both"]
    api: Literal["check", "generate"] = "check"
    engine: Literal["llmrails", "iorails", "both"] = "both"
    bot_stub: str = Field(default=SECRET_OUTPUT, min_length=1)


app = FastAPI(title="IORails transform playground")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return INDEX.read_text(encoding="utf-8")


@app.post("/api/compare")
async def compare(req: CompareRequest) -> dict[str, Any]:
    input_rails = req.mode in {"input", "both"}
    output_rails = req.mode in {"output", "both"}
    if req.api == "check" and req.mode == "both":
        raise HTTPException(
            status_code=400,
            detail=(
                "check() with both surfaces needs a user turn and an assistant turn; "
                "use generate(), or pick input or output."
            ),
        )
    config_dict = _config(input_rails=input_rails, output_rails=output_rails)
    config = RailsConfig.from_content(config=config_dict)
    bot_stub = req.bot_stub if req.mode in {"output", "both"} else SAFE_REPLY

    if req.api == "check" and output_rails and not input_rails:
        messages = [{"role": "assistant", "content": req.text}]
    else:
        messages = [{"role": "user", "content": req.text}]

    results: list[dict[str, Any]] = []

    if req.engine in {"llmrails", "both"}:
        chat = TestChat(config, llm_completions=[bot_stub])
        chat.app.register_action(_redact, "mask_sensitive_data")
        if req.api == "check":
            result = await chat.app.check_async(messages)
            results.append({"engine": "llmrails", "api": "check", **_serialize_check(result)})
        else:
            generated = await chat.app.generate_async(messages=messages)
            results.append(
                {
                    "engine": "llmrails",
                    "api": "generate",
                    "submitted": req.text,
                    "assistant_response": generated.get("content") if isinstance(generated, dict) else generated,
                    "response": generated,
                }
            )

    if req.engine in {"iorails", "both"}:
        model_prompts: list[list[dict]] = []
        with patch.dict(os.environ, {"NVIDIA_API_KEY": os.environ.get("NVIDIA_API_KEY") or "test-key"}):
            iorails = IORails(RailsConfig.from_content(config=config_dict))
        async with iorails:
            if input_rails:
                _install_iorails_action(iorails, "mask sensitive data on input", RailDirection.INPUT)
            if output_rails:
                _install_iorails_action(iorails, "mask sensitive data on output", RailDirection.OUTPUT)
            _stub_main_chat(iorails, bot_stub, model_prompts)
            if req.api == "check":
                result = await iorails.check_async(messages)
                results.append({"engine": "iorails", "api": "check", **_serialize_check(result)})
            else:
                generated = await iorails.generate_async(messages=messages)
                prompt_to_model = None
                if model_prompts:
                    last_user = next(
                        (m.get("content") for m in reversed(model_prompts[-1]) if m.get("role") == "user"),
                        None,
                    )
                    prompt_to_model = last_user
                results.append(
                    {
                        "engine": "iorails",
                        "api": "generate",
                        "submitted": req.text,
                        "prompt_sent_to_model": prompt_to_model,
                        "assistant_response": generated.get("content") if isinstance(generated, dict) else generated,
                        "response": generated,
                    }
                )

    return {
        "mode": req.mode,
        "api": req.api,
        "text": req.text,
        "messages": messages,
        "bot_stub": bot_stub,
        "can_handle": IORails.can_handle(config),
        "results": results,
    }


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8765, reload=False)


if __name__ == "__main__":
    main()
