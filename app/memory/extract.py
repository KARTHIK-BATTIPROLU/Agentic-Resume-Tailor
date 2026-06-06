"""Turn raw chat / pasted-resume text into structured career facts via Groq."""
from __future__ import annotations

import json
import re
from typing import Optional

from groq import AsyncGroq

from app.agent.prompts import EXTRACTION_SYSTEM_PROMPT
from app.config import GROQ_MODEL, settings

_client: Optional[AsyncGroq] = None


def _get_client() -> AsyncGroq:
    global _client
    if _client is None:
        if not settings.GROQ_API_KEY:
            raise RuntimeError("GROQ_API_KEY is not configured.")
        _client = AsyncGroq(api_key=settings.GROQ_API_KEY)
    return _client


_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


def parse_json_object(raw: str) -> dict:
    """Parse a JSON object from an LLM response, tolerating code fences."""
    if not raw:
        raise ValueError("empty response")
    text = _FENCE_RE.sub("", raw.strip())
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        # Fall back to the outermost {...} span.
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        result = json.loads(text[start : end + 1])
    if not isinstance(result, dict):
        raise ValueError("expected a JSON object")
    return result


async def extract_career_facts(text: str) -> dict:
    """Extract structured career facts; return ``{}`` if nothing usable."""
    if not text or not text.strip():
        return {}

    client = _get_client()
    messages = [
        {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
        {"role": "user", "content": text.strip()},
    ]

    last_err: Optional[Exception] = None
    for _ in range(2):  # initial attempt + one retry on parse failure
        try:
            resp = await client.chat.completions.create(
                model=GROQ_MODEL,
                messages=messages,
                temperature=0.1,
                response_format={"type": "json_object"},
            )
            return parse_json_object(resp.choices[0].message.content or "")
        except (json.JSONDecodeError, ValueError) as exc:
            last_err = exc
            continue
    # Parsing failed twice — degrade gracefully rather than crash the endpoint.
    return {}
