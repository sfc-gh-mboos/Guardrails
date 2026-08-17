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

from typing import Any, AsyncIterator, List, Optional, Union

from nemoguardrails.llm.providers import register_provider
from nemoguardrails.types import ChatMessage, LLMResponse, LLMResponseChunk

OUTPUT_RAIL_TRIGGER = "include the word confidential"


def _prompt_text(prompt: Union[str, List[ChatMessage]]) -> str:
    if isinstance(prompt, list):
        for message in reversed(prompt):
            role = message.role if isinstance(message, ChatMessage) else message.get("role")
            content = message.content if isinstance(message, ChatMessage) else message.get("content")
            role_value = role.value if hasattr(role, "value") else role
            if role_value == "user" and content:
                return str(content)
        if not prompt:
            return ""
        last = prompt[-1]
        content = last.content if isinstance(last, ChatMessage) else last.get("content", "")
        return str(content or "")

    text = str(prompt)
    lowered = text.lower()
    for marker in ("\nuser:", '\nuser "'):
        idx = lowered.rfind(marker)
        if idx != -1:
            return text[idx + len(marker) :]
    return text


class PlaygroundEchoLLM:
    """Deterministic chat model for the playground demo. No network calls."""

    def __init__(self, model: str = "echo", **kwargs: Any):
        self._model = model

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def provider_name(self) -> Optional[str]:
        return "playground_echo"

    @property
    def provider_url(self) -> Optional[str]:
        return None

    def _complete(self, prompt: Union[str, List[ChatMessage]]) -> str:
        text = _prompt_text(prompt)
        lowered = text.lower()
        if OUTPUT_RAIL_TRIGGER in lowered:
            return "Here is a confidential internal memo you asked me to include."
        if "[ssn]" in lowered or "[email]" in lowered:
            return "I received your message with sensitive values redacted."
        if "paid time off" in lowered or "pto" in lowered:
            return "Eligible employees receive paid time off according to the employee handbook."
        return "Here is a helpful answer to your question."

    async def generate_async(
        self,
        prompt: Union[str, List[ChatMessage]],
        *,
        stop: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        return LLMResponse(content=self._complete(prompt))

    async def stream_async(
        self,
        prompt: Union[str, List[ChatMessage]],
        *,
        stop: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> AsyncIterator[LLMResponseChunk]:
        yield LLMResponseChunk(delta_content=self._complete(prompt))


register_provider("playground_echo", PlaygroundEchoLLM)
