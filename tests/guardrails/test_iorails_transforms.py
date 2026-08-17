"""IORails-specific transform apply coverage (speculative retry, streaming)."""

import copy
from unittest.mock import AsyncMock

import pytest

from nemoguardrails.guardrails.guardrails_types import RailDirection
from nemoguardrails.guardrails.iorails import IORails
from nemoguardrails.guardrails.model_engine import ModelEngine
from nemoguardrails.types import LLMResponse, LLMResponseChunk
from tests.guardrails.async_helpers import started_iorails
from tests.guardrails.test_cross_engine_rail_equivalence import (
    MAIN_OUTPUT,
    REDACTED_INPUT,
    REDACTED_OUTPUT,
    SECRET_INPUT,
    SECRET_OUTPUT,
    _install_iorails_action,
    _mask_input_config,
    _mask_output_config,
    _redact_bot,
    _redact_user,
)


def _mask_input_speculative_config() -> dict:
    """Input-masking config with speculative generation enabled."""
    config = copy.deepcopy(_mask_input_config())
    config["rails"]["input"]["speculative_generation"] = True
    return config


def _mask_output_streaming_config() -> dict:
    """Output-masking config with streaming output rails enabled."""
    config = copy.deepcopy(_mask_output_config())
    config["rails"]["output"]["streaming"] = {
        "enabled": True,
        "chunk_size": 4,
        "context_size": 2,
        "stream_first": True,
    }
    return config


def _mask_both_streaming_config() -> dict:
    """Input and output masking, with streaming output rails enabled."""
    config = copy.deepcopy(_mask_input_config())
    config["rails"]["output"] = {
        "flows": ["mask sensitive data on output"],
        "streaming": {
            "enabled": True,
            "chunk_size": 4,
            "context_size": 2,
            "stream_first": True,
        },
    }
    config["rails"]["config"]["sensitive_data_detection"]["output"] = {"entities": ["PERSON"]}
    return config


def _stub_main_chat(iorails: IORails, content: str) -> None:
    """Replace the main model's chat completion with a fixed response."""
    for name, engine in iorails.engine_registry._engines.items():
        if isinstance(engine, ModelEngine) and name == "main":
            engine.chat_completion = AsyncMock(return_value=LLMResponse(content=content))


@pytest.mark.asyncio
async def test_speculative_retries_main_model_after_input_rewrite():
    """A user-turn TRANSFORM discards the speculative call and regenerates on the rewrite."""
    calls: list[list[dict]] = []

    async def _capture(_model_type, sent, **_kwargs):
        calls.append(sent)
        if SECRET_INPUT in sent[-1]["content"]:
            return LLMResponse(content="from original")
        return LLMResponse(content="from rewritten")

    async with started_iorails(_mask_input_speculative_config()) as iorails:
        _install_iorails_action(iorails, "mask sensitive data on input", RailDirection.INPUT, _redact_user)
        iorails.engine_registry.model_call = AsyncMock(side_effect=_capture)
        result = await iorails.generate_async(messages=[{"role": "user", "content": SECRET_INPUT}])

    assert result["content"] == "from rewritten"
    assert calls, "main model was not called"
    assert calls[-1][-1]["content"] == REDACTED_INPUT
    assert any(call[-1]["content"] == REDACTED_INPUT for call in calls)


@pytest.mark.asyncio
async def test_streaming_applies_input_rewrite_before_model_call():
    """stream_async rewrites the user turn before the main model stream starts."""
    seen: list[list[dict]] = []

    async def _stream(_model_type, messages, **_kwargs):
        seen.append(messages)
        yield LLMResponseChunk(delta_content="ok")

    async with started_iorails(_mask_input_config()) as iorails:
        _install_iorails_action(iorails, "mask sensitive data on input", RailDirection.INPUT, _redact_user)
        iorails.engine_registry.stream_model_call = _stream
        chunks = [chunk async for chunk in iorails.stream_async(messages=[{"role": "user", "content": SECRET_INPUT}])]

    assert "".join(chunk for chunk in chunks if isinstance(chunk, str)) == "ok"
    assert seen[0][-1]["content"] == REDACTED_INPUT


@pytest.mark.asyncio
async def test_streaming_does_not_rewrite_already_emitted_output():
    """Streaming output rails leave already-emitted chunks unchanged on TRANSFORM."""
    async def _stream(_model_type, messages, **_kwargs):
        yield LLMResponseChunk(delta_content=SECRET_OUTPUT)

    async with started_iorails(_mask_output_streaming_config()) as iorails:
        _install_iorails_action(iorails, "mask sensitive data on output", RailDirection.OUTPUT, _redact_bot)
        iorails.engine_registry.stream_model_call = _stream
        chunks = [chunk async for chunk in iorails.stream_async(messages=[{"role": "user", "content": "hi"}])]

    text = "".join(chunk for chunk in chunks if isinstance(chunk, str))
    assert SECRET_OUTPUT in text
    assert "[REDACTED]" not in text


@pytest.mark.asyncio
async def test_streaming_output_rails_see_the_rewritten_user_turn():
    """After an input TRANSFORM, streaming output rails are handed the rewritten user turn."""
    seen: list[str] = []

    async def _stream(_model_type, messages, **_kwargs):
        yield LLMResponseChunk(delta_content=MAIN_OUTPUT)

    async with started_iorails(_mask_both_streaming_config()) as iorails:
        _install_iorails_action(iorails, "mask sensitive data on input", RailDirection.INPUT, _redact_user)
        _install_iorails_action(iorails, "mask sensitive data on output", RailDirection.OUTPUT, _redact_bot)
        original = iorails.rails_manager.is_output_safe

        async def _spy(messages, response, *, enabled=True):
            seen.append(messages[-1]["content"] if messages else "")
            return await original(messages, response, enabled=enabled)

        iorails.rails_manager.is_output_safe = _spy
        iorails.engine_registry.stream_model_call = _stream
        async for _chunk in iorails.stream_async(messages=[{"role": "user", "content": SECRET_INPUT}]):
            pass

    assert seen == [REDACTED_INPUT]


@pytest.mark.asyncio
async def test_generate_applies_output_rewrite_to_the_returned_assistant_text():
    """generate_async returns the rewritten assistant text after an output TRANSFORM."""
    async with started_iorails(_mask_output_config()) as iorails:
        _stub_main_chat(iorails, SECRET_OUTPUT)
        _install_iorails_action(iorails, "mask sensitive data on output", RailDirection.OUTPUT, _redact_bot)
        result = await iorails.generate_async(messages=[{"role": "user", "content": "hi"}])

    assert result["content"] == REDACTED_OUTPUT
