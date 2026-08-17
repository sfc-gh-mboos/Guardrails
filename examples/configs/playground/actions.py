import re

from nemoguardrails.actions import action

SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")


@action()
async def mask_pii(text: str) -> str:
    """Rewrite obvious SSN and email values so the playground can show a transform rail."""
    return EMAIL_RE.sub("[EMAIL]", SSN_RE.sub("[SSN]", text or ""))
