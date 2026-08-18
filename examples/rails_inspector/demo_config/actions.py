"""Deterministic demo actions for the Rails Inspector demo configuration.

These actions are intentionally simple pattern matchers so the inspector can run
offline. Real deployments would use the guardrail catalog (content safety,
topic control, PII detection) instead of the keyword lists below.
"""

import re
from typing import List, Tuple

from nemoguardrails.actions import action
from nemoguardrails.actions.rail_outcome import RailOutcome, TransformTarget

# Ordered so that the most specific identifier wins on overlapping matches.
_MASK_PATTERNS: List[Tuple[str, "re.Pattern[str]"]] = [
    ("EMAIL", re.compile(r"\b[\w.%+-]+@[\w.-]+\.[A-Za-z]{2,}\b")),
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("CARD", re.compile(r"\b\d(?:[ -]?\d){12,15}\b")),
    ("ACCOUNT", re.compile(r"\b(?:ACCT|ACC|ACCOUNT)[ -]?\d{4,}\b", re.IGNORECASE)),
]

_OFF_TOPIC_PATTERNS: List[Tuple[str, "re.Pattern[str]"]] = [
    ("medical advice", re.compile(r"\b(diagnos\w*|prescri\w*|symptom\w*|medical advice)\b", re.IGNORECASE)),
    ("legal advice", re.compile(r"\b(sue|lawsuit|legal advice|attorney)\b", re.IGNORECASE)),
    ("investment advice", re.compile(r"\b(stocks?|crypto|bitcoin|invest\w*)\b", re.IGNORECASE)),
]

_TRANSFORM_TARGETS = {
    "input": TransformTarget.USER_MESSAGE,
    "output": TransformTarget.BOT_MESSAGE,
}


@action(name="mask_sensitive_ids")
async def mask_sensitive_ids(source: str, text: str) -> RailOutcome:
    """Replace card, account, SSN, and email identifiers with placeholders."""
    if source not in _TRANSFORM_TARGETS:
        raise ValueError("source must be either 'input' or 'output'")

    masked_text = text or ""
    detections: List[str] = []
    for label, pattern in _MASK_PATTERNS:
        masked_text, count = pattern.subn(f"[{label}]", masked_text)
        if count:
            detections.extend([label] * count)

    if not detections:
        return RailOutcome.allow(metadata={"source": source, "detections": []})

    return RailOutcome.transform(
        [(_TRANSFORM_TARGETS[source], masked_text)],
        reason=f"Masked {len(detections)} identifier(s): {', '.join(sorted(set(detections)))}.",
        metadata={"source": source, "detections": detections},
    )


@action(name="check_off_topic")
async def check_off_topic(text: str) -> RailOutcome:
    """Block questions outside the billing and account scope of the demo bot."""
    matched = [topic for topic, pattern in _OFF_TOPIC_PATTERNS if pattern.search(text or "")]

    if not matched:
        return RailOutcome.allow(metadata={"topics": []})

    return RailOutcome.block(
        reason=f"Off-topic for a billing assistant: {', '.join(matched)}.",
        metadata={"topics": matched},
    )
