"""A scripted, offline stand-in for a real model.

The Rails Inspector uses this model with the bundled demo configuration so the
UI works without API keys or network access. Replies are chosen from keywords in
the prompt the model actually receives, which makes the effect of the input
rails visible: whatever the model echoes back is what survived those rails.

This is a demo aid, not a guardrail. Point the inspector at your own config to
run real models.
"""

from __future__ import annotations

import asyncio
import re
from typing import AsyncIterator, List, Optional, Union

from nemoguardrails.types import ChatMessage, LLMResponse, LLMResponseChunk, Role

# Deliberately fake, syntactically credential-shaped string. The demo output
# rail blocks it, which is the point: the model can produce something the user
# must never see.
_FAKE_CREDENTIAL = "sk-demo-000000000000000000000000"

_CREDENTIAL_REQUEST = re.compile(r"\b(api key|access key|secret|credential|token|password)\b", re.IGNORECASE)
_BILLING_REQUEST = re.compile(r"\b(invoice|refund|charge|receipt|bill|billing|payment|subscription)\b", re.IGNORECASE)


def _last_user_text(prompt: Union[str, List[ChatMessage]]) -> str:
    """Return the user text the model was actually asked to answer."""
    if isinstance(prompt, str):
        return prompt.strip()

    for message in reversed(prompt):
        role = getattr(message, "role", None)
        content = getattr(message, "content", None)
        if role == Role.USER and isinstance(content, str):
            return content.strip()

    return ""


def scripted_reply(prompt: Union[str, List[ChatMessage]]) -> str:
    """Build the demo reply for a prompt. Pure function, easy to assert on."""
    user_text = _last_user_text(prompt)

    if _CREDENTIAL_REQUEST.search(user_text):
        return f"Sure, here is the account API key you asked for: {_FAKE_CREDENTIAL}"

    if _BILLING_REQUEST.search(user_text):
        return (
            "Your March invoice was adjusted and the $42.00 charge was refunded. "
            "I sent the updated receipt to jordan.lee@example.com."
        )

    if not user_text:
        return "I did not receive a question. Ask me about an invoice, a refund, or your account."

    return f'I received this request: "{user_text}". I can help with Acme Cloud billing and account questions.'


class ScriptedDemoModel:
    """Implements the ``LLMModel`` protocol with deterministic canned replies."""

    @property
    def model_name(self) -> str:
        return "scripted-demo-model"

    @property
    def provider_name(self) -> Optional[str]:
        return "rails-inspector-demo"

    @property
    def provider_url(self) -> Optional[str]:
        return None

    async def generate_async(
        self,
        prompt: Union[str, List[ChatMessage]],
        *,
        stop: Optional[List[str]] = None,
        **kwargs,
    ) -> LLMResponse:
        return LLMResponse(content=scripted_reply(prompt), model=self.model_name, finish_reason="stop")

    async def stream_async(
        self,
        prompt: Union[str, List[ChatMessage]],
        *,
        stop: Optional[List[str]] = None,
        **kwargs,
    ) -> AsyncIterator[LLMResponseChunk]:
        text = scripted_reply(prompt)
        for token in text.split(" "):
            await asyncio.sleep(0)
            yield LLMResponseChunk(delta_content=token + " ")
