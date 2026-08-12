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

"""Cross-engine equivalence for catalog rails that rewrite input or output.

Complements the block-only suites: those prove allow/block parity, and these prove that a
TRANSFORM verdict becomes the same rewritten content on both engines — via ``generate_async``
for output rails and ``check_async`` for input rails (where the rewrite is not visible in the
assistant reply).
"""

from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass
from typing import Any, Optional
from unittest.mock import AsyncMock, patch

import pytest

from nemoguardrails.guardrails.iorails import IORails
from nemoguardrails.guardrails.model_engine import ModelEngine
from nemoguardrails.http import HTTPResponse
from nemoguardrails.rails.llm.config import RailsConfig
from nemoguardrails.rails.llm.options import RailStatus
from nemoguardrails.testing import RecordingHTTPClient
from nemoguardrails.types import LLMResponse
from tests.guardrails.test_data import NEMOGUARDS_CONFIG
from tests.utils import TestChat

USER_INPUT = "hello Alice"
MAIN_OUTPUT = "Hello Alice, how can I help?"
MASKED_USER = "hello [NAME_1]"
MASKED_BOT = "Hello [NAME_1], how can I help?"

PRIVATEAI_CONFIG = {
    "privateai": {
        "server_endpoint": "http://privateai.example/process",
        "input": {"entities": ["NAME"]},
        "output": {"entities": ["NAME"]},
    }
}
GLINER_CONFIG = {
    "gliner": {
        "server_endpoint": "http://gliner.example/v1/extract",
        "input": {"entities": ["person"]},
        "output": {"entities": ["person"]},
    }
}
POLYGRAF_CONFIG = {
    "polygraf": {
        "server_endpoint": "http://polygraf.example/v1/pii/text-detect",
        "input": {"entities": ["Person"]},
        "output": {"entities": ["Person"]},
    }
}
PROMPT_SECURITY_ENV = {
    "PS_PROTECT_URL": "http://prompt-security.example/api/protect",
    "PS_APP_ID": "test-app",
}
PANGEA_ENV = {"PANGEA_API_TOKEN": "test-token"}
CROWDSTRIKE_ENV = {"CS_AIDR_TOKEN": "test-token"}


@dataclass(frozen=True)
class TransformVendorRail:
    """One HTTP-backed transform rail with the canned reply that rewrites content."""

    rail_id: str
    flow: str
    direction: str
    transform_payload: Any
    expected_text: str
    rails_config: Optional[dict] = None
    env: Optional[dict] = None


def _privateai_mask_payload(text: str) -> list[dict]:
    return [{"processed_text": text, "entities_present": ["NAME"]}]


def _gliner_mask_payload(text: str, value: str = "Alice") -> dict:
    start = text.index(value)
    return {
        "entities": [
            {
                "value": value,
                "suggested_label": "person",
                "start_position": start,
                "end_position": start + len(value),
                "score": 0.99,
            }
        ],
        "total_entities": 1,
        "tagged_text": text,
    }


def _polygraf_mask_payload(text: str, value: str = "Alice") -> dict:
    start = text.index(value)
    return {
        "entities": [
            {
                "entity_type": "Person",
                "start": start,
                "end": start + len(value),
                "entity_text": value,
            }
        ]
    }


TRANSFORM_VENDOR_RAILS = [
    TransformVendorRail(
        rail_id="privateai_mask_input",
        flow="mask pii on input",
        direction="input",
        transform_payload=_privateai_mask_payload(MASKED_USER),
        expected_text=MASKED_USER,
        rails_config=PRIVATEAI_CONFIG,
        env={"PAI_API_KEY": "test-key"},
    ),
    TransformVendorRail(
        rail_id="privateai_mask_output",
        flow="mask pii on output",
        direction="output",
        transform_payload=_privateai_mask_payload(MASKED_BOT),
        expected_text=MASKED_BOT,
        rails_config=PRIVATEAI_CONFIG,
        env={"PAI_API_KEY": "test-key"},
    ),
    TransformVendorRail(
        rail_id="gliner_mask_input",
        flow="gliner mask pii on input",
        direction="input",
        transform_payload=_gliner_mask_payload(USER_INPUT),
        expected_text="hello [PERSON]",
        rails_config=GLINER_CONFIG,
    ),
    TransformVendorRail(
        rail_id="gliner_mask_output",
        flow="gliner mask pii on output",
        direction="output",
        transform_payload=_gliner_mask_payload(MAIN_OUTPUT),
        expected_text="Hello [PERSON], how can I help?",
        rails_config=GLINER_CONFIG,
    ),
    TransformVendorRail(
        rail_id="polygraf_mask_input",
        flow="polygraf mask pii on input",
        direction="input",
        transform_payload=_polygraf_mask_payload(USER_INPUT),
        expected_text="hello <Person>",
        rails_config=POLYGRAF_CONFIG,
        env={"POLYGRAF_API_KEY": "test-key"},
    ),
    TransformVendorRail(
        rail_id="polygraf_mask_output",
        flow="polygraf mask pii on output",
        direction="output",
        transform_payload=_polygraf_mask_payload(MAIN_OUTPUT),
        expected_text="Hello <Person>, how can I help?",
        rails_config=POLYGRAF_CONFIG,
        env={"POLYGRAF_API_KEY": "test-key"},
    ),
    TransformVendorRail(
        rail_id="prompt_security_input",
        flow="protect prompt",
        direction="input",
        transform_payload={"result": {"action": "modify", "prompt": {"modified_text": MASKED_USER}}},
        expected_text=MASKED_USER,
        env=PROMPT_SECURITY_ENV,
    ),
    TransformVendorRail(
        rail_id="prompt_security_output",
        flow="protect response",
        direction="output",
        transform_payload={"result": {"action": "modify", "response": {"modified_text": MASKED_BOT}}},
        expected_text=MASKED_BOT,
        env=PROMPT_SECURITY_ENV,
    ),
    TransformVendorRail(
        rail_id="pangea_input",
        flow="pangea ai guard input",
        direction="input",
        transform_payload={
            "result": {
                "blocked": False,
                "transformed": True,
                "prompt_messages": [{"role": "user", "content": MASKED_USER}],
            }
        },
        expected_text=MASKED_USER,
        env=PANGEA_ENV,
    ),
    TransformVendorRail(
        rail_id="pangea_output",
        flow="pangea ai guard output",
        direction="output",
        transform_payload={
            "result": {
                "blocked": False,
                "transformed": True,
                "prompt_messages": [{"role": "assistant", "content": MASKED_BOT}],
            }
        },
        expected_text=MASKED_BOT,
        env=PANGEA_ENV,
    ),
    TransformVendorRail(
        rail_id="crowdstrike_input",
        flow="crowdstrike aidr guard input",
        direction="input",
        transform_payload={
            "result": {
                "blocked": False,
                "transformed": True,
                "guard_output": {"messages": [{"role": "user", "content": MASKED_USER}]},
            }
        },
        expected_text=MASKED_USER,
        env=CROWDSTRIKE_ENV,
    ),
    TransformVendorRail(
        rail_id="crowdstrike_output",
        flow="crowdstrike aidr guard output",
        direction="output",
        transform_payload={
            "result": {
                "blocked": False,
                "transformed": True,
                "guard_output": {"messages": [{"role": "assistant", "content": MASKED_BOT}]},
            }
        },
        expected_text=MASKED_BOT,
        env=CROWDSTRIKE_ENV,
    ),
]


def _http_response(payload: Any) -> HTTPResponse:
    return HTTPResponse(
        status_code=200,
        headers={"content-type": "application/json"},
        content=json.dumps(payload).encode(),
    )


def _vendor_config(rail: TransformVendorRail) -> dict:
    rails: dict = {rail.direction: {"flows": [rail.flow]}}
    if rail.rails_config:
        rails["config"] = copy.deepcopy(rail.rails_config)
    return {"models": [copy.deepcopy(NEMOGUARDS_CONFIG["models"][0])], "rails": rails}


def _assistant_content(response: object) -> str:
    assert isinstance(response, dict), f"expected a message dict, got {type(response).__name__}"
    return response["content"]


async def _llmrails_generate(config_dict: dict, client: RecordingHTTPClient) -> str:
    config = RailsConfig.from_content(config=config_dict)
    chat = TestChat(config, llm_completions=[MAIN_OUTPUT])
    chat.app.register_action_param("http_client", client)
    response = await chat.app.generate_async(messages=[{"role": "user", "content": USER_INPUT}])
    return _assistant_content(response)


async def _iorails_generate(config_dict: dict, client: RecordingHTTPClient, monkeypatch) -> str:
    monkeypatch.setattr(
        "nemoguardrails.guardrails.rails_manager.create_http_client",
        lambda *args, **kwargs: client,
    )
    with patch.dict(os.environ, {"NVIDIA_API_KEY": "test-key"}):
        iorails = IORails(RailsConfig.from_content(config=config_dict))

    async with iorails:
        main = iorails.engine_registry._engines["main"]
        assert isinstance(main, ModelEngine)
        main.chat_completion = AsyncMock(return_value=LLMResponse(content=MAIN_OUTPUT))
        response = await iorails.generate_async(messages=[{"role": "user", "content": USER_INPUT}])
        return _assistant_content(response)


async def _llmrails_check(config_dict: dict, client: RecordingHTTPClient, messages: list[dict]):
    config = RailsConfig.from_content(config=config_dict)
    chat = TestChat(config, llm_completions=[MAIN_OUTPUT])
    chat.app.register_action_param("http_client", client)
    return await chat.app.check_async(messages)


async def _iorails_check(config_dict: dict, client: RecordingHTTPClient, monkeypatch, messages: list[dict]):
    monkeypatch.setattr(
        "nemoguardrails.guardrails.rails_manager.create_http_client",
        lambda *args, **kwargs: client,
    )
    with patch.dict(os.environ, {"NVIDIA_API_KEY": "test-key"}):
        iorails = IORails(RailsConfig.from_content(config=config_dict))

    async with iorails:
        return await iorails.check_async(messages)


OUTPUT_TRANSFORM_RAILS = [rail for rail in TRANSFORM_VENDOR_RAILS if rail.direction == "output"]
INPUT_TRANSFORM_RAILS = [rail for rail in TRANSFORM_VENDOR_RAILS if rail.direction == "input"]


class TestOutputTransformRailsAgreeAcrossEngines:
    """Output rewrite rails produce the same assistant content on both engines."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("rail", OUTPUT_TRANSFORM_RAILS, ids=[rail.rail_id for rail in OUTPUT_TRANSFORM_RAILS])
    async def test_engines_return_the_same_rewritten_response(self, rail: TransformVendorRail, monkeypatch):
        for name, value in (rail.env or {}).items():
            monkeypatch.setenv(name, value)
        config_dict = _vendor_config(rail)

        llmrails_content = await _llmrails_generate(
            config_dict, RecordingHTTPClient([_http_response(rail.transform_payload)])
        )
        iorails_content = await _iorails_generate(
            config_dict, RecordingHTTPClient([_http_response(rail.transform_payload)]), monkeypatch
        )

        assert llmrails_content == rail.expected_text
        assert iorails_content == rail.expected_text


class TestInputTransformRailsAgreeOnCheck:
    """Input rewrite rails surface the same MODIFIED content through ``check_async``."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("rail", INPUT_TRANSFORM_RAILS, ids=[rail.rail_id for rail in INPUT_TRANSFORM_RAILS])
    async def test_engines_return_the_same_modified_check(self, rail: TransformVendorRail, monkeypatch):
        for name, value in (rail.env or {}).items():
            monkeypatch.setenv(name, value)
        config_dict = _vendor_config(rail)
        messages = [{"role": "user", "content": USER_INPUT}]

        llmrails_result = await _llmrails_check(
            config_dict, RecordingHTTPClient([_http_response(rail.transform_payload)]), messages
        )
        iorails_result = await _iorails_check(
            config_dict, RecordingHTTPClient([_http_response(rail.transform_payload)]), monkeypatch, messages
        )

        assert llmrails_result.status == RailStatus.MODIFIED
        assert iorails_result.status == RailStatus.MODIFIED
        assert llmrails_result.content == rail.expected_text
        assert iorails_result.content == rail.expected_text


class TestTransformRailsAreReachable:
    """A transform rail that works is still unreachable until the enabled tier admits it."""

    @pytest.mark.parametrize("rail", TRANSFORM_VENDOR_RAILS, ids=[rail.rail_id for rail in TRANSFORM_VENDOR_RAILS])
    def test_iorails_accepts_a_config_using_the_rail(self, rail: TransformVendorRail, monkeypatch):
        for name, value in (rail.env or {}).items():
            monkeypatch.setenv(name, value)
        config = RailsConfig.from_content(config=_vendor_config(rail))

        assert IORails.unsupported_reason(config, llm=None) is None


class TestLocalInjectionDetectionTransformAcrossEngines:
    """In-process omit action rewrites bot output the same way on both engines."""

    @pytest.mark.asyncio
    async def test_omit_injection_rewrites_match(self):
        config_dict = {
            "models": [copy.deepcopy(NEMOGUARDS_CONFIG["models"][0])],
            "rails": {
                "output": {"flows": ["injection detection"]},
                "config": {
                    "injection_detection": {
                        "injections": ["sqli"],
                        "action": "omit",
                    }
                },
            },
        }
        sql_injection = "This is a SELECT * FROM users; -- malicious comment in the middle of text"
        expected = "This is a  * FROM usersmalicious comment in the middle of text"

        llmrails = TestChat(RailsConfig.from_content(config=config_dict), llm_completions=[sql_injection])
        llmrails_response = await llmrails.app.generate_async(messages=[{"role": "user", "content": "do a fake query"}])

        with patch.dict(os.environ, {"NVIDIA_API_KEY": "test-key"}):
            iorails = IORails(RailsConfig.from_content(config=config_dict))
        async with iorails:
            main = iorails.engine_registry._engines["main"]
            assert isinstance(main, ModelEngine)
            main.chat_completion = AsyncMock(return_value=LLMResponse(content=sql_injection))
            iorails_response = await iorails.generate_async(messages=[{"role": "user", "content": "do a fake query"}])

        assert _assistant_content(llmrails_response) == expected
        assert _assistant_content(iorails_response) == expected
