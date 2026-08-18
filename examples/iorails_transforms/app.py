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
``[REDACTED]``, matching ``tests/guardrails/test_cross_engine_rail_equivalence.py``
and ``tests/guardrails/test_iorails_transforms.py``. No Presidio, and no live
model calls.
"""

from __future__ import annotations

import asyncio
import copy
import os
from pathlib import Path
from typing import Any, Literal
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from nemoguardrails.actions.rail_outcome import RailOutcome, TransformTarget
from nemoguardrails.guardrails.guardrails_types import RailDirection
from nemoguardrails.guardrails.iorails import IORails
from nemoguardrails.guardrails.model_engine import ModelEngine
from nemoguardrails.rails.llm.config import RailsConfig
from nemoguardrails.testing.chat_harness import TestChat
from nemoguardrails.types import LLMResponse, LLMResponseChunk

HERE = Path(__file__).resolve().parent
INDEX = HERE / "static" / "index.html"

MAIN_MODEL = {"type": "main", "engine": "nim", "model": "meta/llama-3.3-70b-instruct"}
SAFE_REPLY = "Hello! How can I help?"
SECRET_INPUT = "my token is SECRET"
REDACTED_INPUT = "my token is [REDACTED]"
SECRET_OUTPUT = "here is SECRET"
REDACTED_OUTPUT = "here is [REDACTED]"

CASES: list[dict[str, Any]] = [
    {
        "id": "input-check",
        "label": "Input rewrite on check()",
        "api": "check",
        "mode": "input",
        "text": SECRET_INPUT,
        "bot_stub": SAFE_REPLY,
        "expect": "Both engines return status=modified and content='my token is [REDACTED]'.",
        "tests": [
            "tests/guardrails/test_cross_engine_rail_equivalence.py::TestTransformsAgreeAcrossEngines::test_input_check_returns_the_same_modified_content",
            "tests/guardrails/test_iorails_check.py::TestCheckAsyncAutoDetect::test_input_modified",
        ],
    },
    {
        "id": "output-check",
        "label": "Output rewrite on check()",
        "api": "check",
        "mode": "output",
        "text": SECRET_OUTPUT,
        "bot_stub": SECRET_OUTPUT,
        "expect": "Both engines return status=modified and content='here is [REDACTED]'.",
        "tests": [
            "tests/guardrails/test_cross_engine_rail_equivalence.py::TestTransformsAgreeAcrossEngines::test_output_check_returns_the_same_modified_content",
            "tests/guardrails/test_iorails_check.py::TestCheckAsyncAutoDetect::test_output_modified",
        ],
    },
    {
        "id": "input-generate",
        "label": "Input rewrite on generate()",
        "api": "generate",
        "mode": "input",
        "text": SECRET_INPUT,
        "bot_stub": SAFE_REPLY,
        "expect": "Both engines return the same assistant text. IORails prompt_sent_to_model is redacted.",
        "tests": [
            "tests/guardrails/test_cross_engine_rail_equivalence.py::TestTransformsAgreeAcrossEngines::test_input_generate_hides_the_secret_from_both_main_models",
        ],
    },
    {
        "id": "output-generate",
        "label": "Output rewrite on generate()",
        "api": "generate",
        "mode": "output",
        "text": "hello there",
        "bot_stub": SECRET_OUTPUT,
        "expect": "Both engines return 'here is [REDACTED]' as the assistant response.",
        "tests": [
            "tests/guardrails/test_cross_engine_rail_equivalence.py::TestTransformsAgreeAcrossEngines::test_output_generate_returns_the_same_rewritten_assistant_text",
            "tests/guardrails/test_iorails_transforms.py::test_generate_applies_output_rewrite_to_the_returned_assistant_text",
        ],
    },
    {
        "id": "stream-input",
        "label": "Streaming input rewrite",
        "api": "stream",
        "mode": "input",
        "text": SECRET_INPUT,
        "bot_stub": SECRET_OUTPUT,
        "expect": "The model sees the redacted user turn. Streamed chunks are not rewritten.",
        "tests": [
            "tests/guardrails/test_iorails_transforms.py::test_streaming_applies_input_rewrite_before_model_call",
            "tests/guardrails/test_iorails_transforms.py::test_streaming_does_not_rewrite_already_emitted_output",
        ],
    },
]


def _config(*, input_rails: bool, output_rails: bool, streaming: bool = False) -> dict:
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
        output: dict[str, Any] = {"flows": ["mask sensitive data on output"]}
        if streaming:
            output["streaming"] = {
                "enabled": True,
                "chunk_size": 4,
                "context_size": 2,
                "stream_first": True,
            }
        rails["output"] = output
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
    }


def _assistant_content(generated: Any) -> str:
    if isinstance(generated, dict):
        return str(generated.get("content", ""))
    return str(generated)


def _last_user(messages: list[dict]) -> str | None:
    for message in reversed(messages):
        if message.get("role") == "user":
            content = message.get("content")
            return content if isinstance(content, str) else None
    return None


class CompareRequest(BaseModel):
    text: str = Field(..., min_length=1)
    mode: Literal["input", "output", "both"]
    api: Literal["check", "generate", "stream"] = "check"
    engine: Literal["llmrails", "iorails", "both"] = "both"
    bot_stub: str = Field(default=SECRET_OUTPUT, min_length=1)


app = FastAPI(title="IORails transform playground")


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return INDEX.read_text(encoding="utf-8")


@app.get("/api/cases")
async def cases() -> dict[str, Any]:
    return {
        "cases": CASES,
        "secret_input": SECRET_INPUT,
        "redacted_input": REDACTED_INPUT,
        "secret_output": SECRET_OUTPUT,
        "redacted_output": REDACTED_OUTPUT,
    }


@app.post("/api/compare")
async def compare(req: CompareRequest) -> dict[str, Any]:
    if req.api == "stream":
        if req.engine == "llmrails":
            raise HTTPException(status_code=400, detail="Streaming comparison is IORails-only in this playground.")
        return await _run_stream(req)

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
        results.append(await _run_llmrails(config, messages, req.api, req.text, bot_stub))

    if req.engine in {"iorails", "both"}:
        results.append(
            await _run_iorails(config_dict, messages, req.api, req.text, bot_stub, input_rails, output_rails)
        )

    agreement = _agreement(req.api, results)
    return {
        "mode": req.mode,
        "api": req.api,
        "text": req.text,
        "messages": messages,
        "bot_stub": bot_stub,
        "can_handle": IORails.can_handle(config),
        "results": results,
        "agreement": agreement,
    }


def _agreement(api: str, results: list[dict[str, Any]]) -> dict[str, Any] | None:
    if len(results) != 2:
        return None
    if api == "check":
        compared = ["status", "content"]
        left = {key: results[0].get(key) for key in compared}
        right = {key: results[1].get(key) for key in compared}
    else:
        compared = ["assistant_response"]
        left = {key: results[0].get(key) for key in compared}
        right = {key: results[1].get(key) for key in compared}
    return {"equal": left == right, "compared": compared, "left": left, "right": right}


async def _run_llmrails(
    config: RailsConfig, messages: list[dict], api: str, text: str, bot_stub: str
) -> dict[str, Any]:
    chat = TestChat(config, llm_completions=[bot_stub])
    chat.app.register_action(_redact, "mask_sensitive_data")
    if api == "check":
        result = await chat.app.check_async(messages)
        return {"engine": "llmrails", "api": "check", **_serialize_check(result)}
    generated = await chat.app.generate_async(messages=messages)
    return {
        "engine": "llmrails",
        "api": "generate",
        "submitted": text,
        "assistant_response": _assistant_content(generated),
    }


async def _run_iorails(
    config_dict: dict,
    messages: list[dict],
    api: str,
    text: str,
    bot_stub: str,
    input_rails: bool,
    output_rails: bool,
) -> dict[str, Any]:
    model_prompts: list[list[dict]] = []
    with patch.dict(os.environ, {"NVIDIA_API_KEY": os.environ.get("NVIDIA_API_KEY") or "test-key"}):
        iorails = IORails(RailsConfig.from_content(config=config_dict))
    async with iorails:
        if input_rails:
            _install_iorails_action(iorails, "mask sensitive data on input", RailDirection.INPUT)
        if output_rails:
            _install_iorails_action(iorails, "mask sensitive data on output", RailDirection.OUTPUT)
        _stub_main_chat(iorails, bot_stub, model_prompts)
        if api == "check":
            result = await iorails.check_async(messages)
            return {"engine": "iorails", "api": "check", **_serialize_check(result)}
        generated = await iorails.generate_async(messages=messages)
        return {
            "engine": "iorails",
            "api": "generate",
            "submitted": text,
            "prompt_sent_to_model": _last_user(model_prompts[-1]) if model_prompts else None,
            "assistant_response": _assistant_content(generated),
        }


async def _run_stream(req: CompareRequest) -> dict[str, Any]:
    config_dict = _config(input_rails=True, output_rails=True, streaming=True)
    messages = [{"role": "user", "content": req.text}]
    seen: list[list[dict]] = []
    chunks: list[str] = []

    async def _fake_stream(_model_type, sent, **_kwargs):
        seen.append(copy.deepcopy(sent))
        for piece in ("here ", "is ", "SECRET"):
            yield LLMResponseChunk(delta_content=piece)
            await asyncio.sleep(0)

    with patch.dict(os.environ, {"NVIDIA_API_KEY": os.environ.get("NVIDIA_API_KEY") or "test-key"}):
        iorails = IORails(RailsConfig.from_content(config=config_dict))
    async with iorails:
        _install_iorails_action(iorails, "mask sensitive data on input", RailDirection.INPUT)
        _install_iorails_action(iorails, "mask sensitive data on output", RailDirection.OUTPUT)
        iorails.engine_registry.stream_model_call = _fake_stream
        async for chunk in iorails.stream_async(messages=messages):
            if isinstance(chunk, str):
                chunks.append(chunk)

    prompt = _last_user(seen[-1]) if seen else None
    joined = "".join(chunks)
    result = {
        "engine": "iorails",
        "api": "stream",
        "submitted": req.text,
        "prompt_sent_to_model": prompt,
        "chunks": chunks,
        "joined": joined,
        "input_rewritten": prompt is not None and "SECRET" not in prompt,
        "output_chunks_still_contain_secret": "SECRET" in joined,
    }
    return {
        "mode": req.mode,
        "api": "stream",
        "text": req.text,
        "messages": messages,
        "bot_stub": req.bot_stub,
        "can_handle": True,
        "results": [result],
        "agreement": None,
    }


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8765, reload=False)


if __name__ == "__main__":
    main()
