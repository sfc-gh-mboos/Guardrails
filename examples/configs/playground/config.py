from typing import Any, AsyncIterator, List, Optional, Union

from nemoguardrails.llm.providers import register_provider
from nemoguardrails.types import ChatMessage, LLMResponse, LLMResponseChunk

OUTPUT_RAIL_TRIGGER = "confidential"


def _prompt_text(prompt: Union[str, List[ChatMessage]]) -> str:
    if isinstance(prompt, str):
        return prompt
    for message in reversed(prompt):
        role = message.role if isinstance(message, ChatMessage) else message.get("role")
        content = message.content if isinstance(message, ChatMessage) else message.get("content")
        if role == "user" and content:
            return str(content)
    if not prompt:
        return ""
    last = prompt[-1]
    content = last.content if isinstance(last, ChatMessage) else last.get("content", "")
    return str(content or "")


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
        if OUTPUT_RAIL_TRIGGER in text.lower():
            return "Here is a confidential internal memo you asked me to include."
        if "paid time off" in text.lower() or "pto" in text.lower():
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
