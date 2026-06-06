"""Generate a tailored resume JSON from a user's profile + a job description."""
from __future__ import annotations

import json
from typing import Any, Optional

from groq import AsyncGroq

from app.agent.prompts import (
    RESUME_ARCHITECT_SYSTEM_PROMPT,
    build_generation_user_message,
)
from app.config import GROQ_MODEL, settings
from app.memory.extract import parse_json_object
from app.memory.profile import get_profile
from app.memory.retrieve import rank_items

_client: Optional[AsyncGroq] = None


def _get_client() -> AsyncGroq:
    global _client
    if _client is None:
        if not settings.GROQ_API_KEY:
            raise RuntimeError("GROQ_API_KEY is not configured.")
        _client = AsyncGroq(api_key=settings.GROQ_API_KEY)
    return _client


_EMPTY_ANALYSIS = {
    "ats_match_score": 0,
    "matched_keywords": [],
    "missing_keywords": [],
    "gaps": [],
    "needs_confirmation": [],
}
_EMPTY_RESUME = {
    "name": "", "contact": {}, "summary": "", "core_competencies": [],
    "experience": [], "projects": [], "education": [],
    "certifications": [], "achievements": [],
}


def _coerce(result: dict[str, Any]) -> dict[str, Any]:
    """Guarantee both top-level keys exist so downstream code never KeyErrors."""
    analysis = result.get("analysis")
    resume = result.get("resume")
    return {
        "analysis": {**_EMPTY_ANALYSIS, **(analysis if isinstance(analysis, dict) else {})},
        "resume": {**_EMPTY_RESUME, **(resume if isinstance(resume, dict) else {})},
    }


async def generate_resume(user_id: str, jd_text: str) -> dict:
    """Return ``{"analysis": {...}, "resume": {...}}`` for ``user_id`` + ``jd_text``."""
    profile = await get_profile(user_id)
    ranked = await rank_items(user_id, jd_text)
    user_msg = build_generation_user_message(profile, ranked, jd_text)

    client = _get_client()
    messages = [
        {"role": "system", "content": RESUME_ARCHITECT_SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
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
            return _coerce(parse_json_object(resp.choices[0].message.content or ""))
        except (json.JSONDecodeError, ValueError) as exc:
            last_err = exc
            continue

    raise RuntimeError(f"Resume generation failed to return valid JSON: {last_err}")
