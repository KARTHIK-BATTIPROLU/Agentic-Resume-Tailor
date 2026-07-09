"""Turn raw text into structured career-facts JSON via the LLM.

Mockable: when ``settings.LLM_MOCK`` is true, returns canned facts without
hitting any API — suitable for unit tests that must run without a real key.
"""
from __future__ import annotations

from app.llm import chat_json
from app.prompts import EXTRACTION_SYSTEM_PROMPT


async def extract_career_facts(text: str) -> dict:
    """Extract structured career facts; return ``{}`` if nothing usable."""
    if not text or not text.strip():
        return {}
    try:
        return await chat_json(EXTRACTION_SYSTEM_PROMPT, text.strip())
    except Exception:
        return {}
