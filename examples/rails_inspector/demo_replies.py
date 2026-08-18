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

"""Deterministic assistant replies for the Rails Inspector demo.

Maps user prompts to canned assistant text so the UI can show output-rail
impact without calling a live model provider.
"""

from __future__ import annotations

import re
from typing import Optional

# Ordered rules: first match wins. Keep patterns aligned with prompts.json.
_REPLY_RULES: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"pto|paid time off|vacation", re.I),
        "Of course. Acme Corp offers paid time off based on tenure. "
        "How many years have you been with the company?",
    ),
    (
        re.compile(r"remote work|work from home|wfh", re.I),
        "Employees may work remotely up to three days per week with manager approval. "
        "Core hours are 10:00–15:00 local time.",
    ),
    (
        re.compile(r"wi-?fi|wifi", re.I),
        "Sure — the guest Wi-Fi password is AcmeGuest2024!",
    ),
    (
        re.compile(r"executive briefing|q3", re.I),
        "CONFIDENTIAL: Revenue missed target by 12%. "
        "Internal use only — do not share outside the leadership team.",
    ),
    (
        re.compile(r"tax id|ssn|social security", re.I),
        "Jane Doe's SSN on file is 987-65-4321.",
    ),
    (
        re.compile(r"phishing|suspicious email", re.I),
        "Forward the message to security@acme.example and do not click any links. "
        "The security team will advise next steps.",
    ),
    (
        re.compile(r"\bhi\b|hello|hey", re.I),
        "Hello! I'm the Acme assistant. Ask me about PTO, remote work, or security reporting.",
    ),
]

_DEFAULT_REPLY = (
    "I can help with Acme workplace policies such as PTO, remote work, and how to report phishing. "
    "What would you like to know?"
)


def draft_assistant_reply(user_text: str, override: Optional[str] = None) -> str:
    """Return a canned assistant reply for ``user_text``.

    If ``override`` is provided (for example from the prompt bank), use it.
    """
    if override is not None and override.strip():
        return override.strip()

    for pattern, reply in _REPLY_RULES:
        if pattern.search(user_text or ""):
            return reply
    return _DEFAULT_REPLY
