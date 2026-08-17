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

"""Keyword rails for the inspector demo. No live LLM or provider calls."""

from __future__ import annotations

import re
from typing import Optional

from nemoguardrails.actions import action
from nemoguardrails.actions.rail_outcome import RailOutcome, TransformTarget

JAILBREAK_MARKERS = (
    "ignore previous instructions",
    "ignore all previous",
    "you are now dan",
    "jailbreak mode",
    "developer mode enabled",
)

HARMFUL_MARKERS = (
    "make a bomb",
    "build a bomb",
    "how to make a weapon",
    "how to kill",
)

SECRET_MARKERS = ("secret-token-42",)

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")


def _contains_any(text: str, markers: tuple[str, ...]) -> Optional[str]:
    lowered = text.lower()
    for marker in markers:
        if marker in lowered:
            return marker
    return None


def _mask_pii(text: str) -> str:
    masked = EMAIL_RE.sub("[EMAIL]", text)
    return SSN_RE.sub("[SSN]", masked)


@action()
async def check_jailbreak_input(context: Optional[dict] = None, **kwargs) -> RailOutcome:
    text = (context or {}).get("user_message") or ""
    matched = _contains_any(text, JAILBREAK_MARKERS)
    if matched:
        return RailOutcome.block(reason=f"Jailbreak marker matched: {matched}")
    return RailOutcome.allow()


@action()
async def check_content_safety_input(context: Optional[dict] = None, **kwargs) -> RailOutcome:
    text = (context or {}).get("user_message") or ""
    matched = _contains_any(text, HARMFUL_MARKERS)
    if matched:
        return RailOutcome.block(reason=f"Harmful-content marker matched: {matched}")
    return RailOutcome.allow()


@action()
async def mask_pii_on_input(context: Optional[dict] = None, **kwargs) -> RailOutcome:
    text = (context or {}).get("user_message") or ""
    masked = _mask_pii(text)
    if masked != text:
        return RailOutcome.transform(
            ((TransformTarget.USER_MESSAGE, masked),),
            reason="Masked email or SSN in the user message.",
        )
    return RailOutcome.allow()


@action()
async def check_content_safety_output(context: Optional[dict] = None, **kwargs) -> RailOutcome:
    text = (context or {}).get("bot_message") or ""
    matched = _contains_any(text, SECRET_MARKERS)
    if matched:
        return RailOutcome.block(reason=f"Secret marker matched: {matched}")
    return RailOutcome.allow()


@action()
async def mask_pii_on_output(context: Optional[dict] = None, **kwargs) -> RailOutcome:
    text = (context or {}).get("bot_message") or ""
    masked = _mask_pii(text)
    if masked != text:
        return RailOutcome.transform(
            ((TransformTarget.BOT_MESSAGE, masked),),
            reason="Masked email or SSN in the bot message.",
        )
    return RailOutcome.allow()
