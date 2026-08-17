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

"""Canned LLM for the inspector demo. No network calls."""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, List, Optional, Union

from nemoguardrails import LLMResponse, LLMResponseChunk, UsageInfo, register_provider


def _last_user_text(prompt: Union[str, List[Any]]) -> str:
    if isinstance(prompt, str):
        return prompt
    if not isinstance(prompt, list):
        return str(prompt)

    for item in reversed(prompt):
        if isinstance(item, dict) and item.get("role") == "user":
            content = item.get("content") or ""
            return content if isinstance(content, str) else str(content)
        role = getattr(item, "role", None)
        if role == "user" or getattr(role, "value", None) == "user":
            content = getattr(item, "content", "") or ""
            return content if isinstance(content, str) else str(content)
    return ""


class InspectorDemoLLMModel:
    """Deterministic demo model so the inspector UI works without API keys."""

    def __init__(self, model: str, **kwargs: Any):
        self._model = model
        self._default_kwargs = kwargs

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def provider_name(self) -> Optional[str]:
        return "inspector_demo"

    @property
    def provider_url(self) -> Optional[str]:
        return None

    def _reply(self, prompt: Union[str, List[Any]]) -> str:
        text = _last_user_text(prompt)
        lowered = text.lower()
        if any(token in lowered for token in ("password", "secret", "override code")):
            return "The override password is SECRET-TOKEN-42. Keep it safe."
        if "[EMAIL]" in text or "[SSN]" in text:
            return "I can help with that account. I will use the masked contact details you provided."
        preview = text.strip() or "(empty prompt)"
        if len(preview) > 240:
            preview = preview[:237] + "..."
        return f"I'm a demo assistant running behind NeMo Guardrails. You said: {preview}"

    async def generate_async(
        self,
        prompt: Union[str, List[Any]],
        *,
        stop: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        content = self._reply(prompt)
        return LLMResponse(
            content=content,
            model=self._model,
            finish_reason="stop",
            usage=UsageInfo(input_tokens=0, output_tokens=len(content.split())),
        )

    async def stream_async(
        self,
        prompt: Union[str, List[Any]],
        *,
        stop: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> AsyncIterator[LLMResponseChunk]:
        content = self._reply(prompt)
        tokens = content.split()
        for index, token in enumerate(tokens):
            await asyncio.sleep(0)
            suffix = " " if index < len(tokens) - 1 else ""
            yield LLMResponseChunk(delta_content=token + suffix, model=self._model)
        yield LLMResponseChunk(model=self._model, finish_reason="stop")


register_provider("inspector_demo", InspectorDemoLLMModel)
