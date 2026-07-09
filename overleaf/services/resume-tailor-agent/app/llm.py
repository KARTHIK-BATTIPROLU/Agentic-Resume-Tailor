"""LLM interface with a built-in mock mode.

When ``settings.LLM_MOCK`` is True (or env ``LLM_MOCK=true``), ``chat_json()``
returns canned JSON without hitting any API — suitable for unit/integration
tests that must run without a real key.

Real path: Groq JSON-mode via the ``groq`` library.
"""
from __future__ import annotations

import json
import re
from typing import Optional

from app.config import settings

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE | re.MULTILINE)

# ── Canned mock responses keyed by a unique substring of each system prompt ────
# Keys must appear literally (lowercased) inside the system prompt they match.
_MOCK_RESPONSES: dict[str, dict] = {
    # EXTRACTION_SYSTEM_PROMPT: "career-data extraction engine"
    "extraction engine": {
        "contact": {"name": "Test User", "email": "test@example.com",
                    "phone": None, "location": None, "linkedin": None, "github": None},
        "skills": [{"name": "Python", "category": "language", "confidence": "HIGH"},
                   {"name": "FastAPI", "category": "framework", "confidence": "HIGH"},
                   {"name": "Docker", "category": "devops", "confidence": "HIGH"}],
        "experiences": [{
            "company": "Acme Corp", "title": "Software Engineer",
            "start": "2021", "end": "2024", "is_current": False,
            "bullets": [{"text": "Built REST APIs", "metric": None}],
            "confidence": "HIGH",
        }],
        "projects": [],
        "education": [{"degree": "BS Computer Science", "institution": "MIT",
                       "start": "2017", "end": "2021", "details": None}],
        "certifications": [],
        "achievements": [],
    },
    # JD_GAP_QUESTION_SYSTEM_PROMPT: "close the most important gap"
    "close the most important gap": {
        "question": "Do you have experience with Kubernetes? It's fine if you don't.",
        "targets": "skill",
    },
    # JD_PARSE_SYSTEM_PROMPT: "precise job-description analyzer"
    "precise job-description analyzer": {
        "title": "Software Engineer",
        "required_skills": ["Python", "FastAPI", "PostgreSQL"],
        "preferred_skills": ["Docker", "Kubernetes"],
        "keywords": ["backend", "REST", "microservices", "CI/CD"],
        "responsibilities": ["Build APIs", "Write tests"],
        "seniority": "mid",
    },
    # RESUME_ARCHITECT_SYSTEM_PROMPT: "ats-optimization specialist"
    "ats-optimization specialist": {
        "analysis": {
            "ats_match_score": 72,
            "matched_keywords": ["Python", "FastAPI"],
            "missing_keywords": ["Kubernetes"],
            "gaps": [],
            "needs_confirmation": [],
        },
        "resume": {
            "name": "Test User",
            "contact": {"email": "test@example.com", "phone": "", "location": "",
                        "linkedin": "", "github": "", "portfolio": ""},
            "summary": "Experienced Python/FastAPI developer.",
            "core_competencies": ["Python", "FastAPI", "Docker", "REST APIs"],
            "experience": [{"company": "Acme Corp", "title": "Software Engineer",
                            "location": "", "start": "2021", "end": "2024",
                            "bullets": ["Built REST APIs serving 10k rps"]}],
            "projects": [],
            "education": [{"degree": "BS Computer Science", "institution": "MIT",
                           "location": "Cambridge", "start": "2017", "end": "2021",
                           "details": None}],
            "certifications": [],
            "achievements": [],
        },
    },
    # PROFILE_QUESTION_SYSTEM_PROMPT: "resume-building assistant"
    "resume-building assistant": {
        "question": "What is your full name and email address?",
        "field": "name",
    },
}


def _mock_response(system_prompt: str) -> dict:
    # Normalize whitespace so keys don't break on mid-word newlines.
    sp_lower = " ".join(system_prompt.lower().split())
    for key, response in _MOCK_RESPONSES.items():
        if key in sp_lower:
            return response
    return {"mock": True, "system_prompt_snippet": system_prompt[:80]}


def parse_json_object(raw: str) -> dict:
    """Parse a JSON dict from an LLM response, tolerating code fences."""
    if not raw:
        raise ValueError("empty response")
    text = _FENCE_RE.sub("", raw.strip())
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        result = json.loads(text[start : end + 1])
    if not isinstance(result, dict):
        raise ValueError("expected a JSON object")
    return result


_groq_client = None


def _get_groq():
    global _groq_client
    if _groq_client is None:
        if not settings.LLM_API_KEY:
            raise RuntimeError(
                "LLM_API_KEY is not set. Set it or enable LLM_MOCK=true for testing."
            )
        from groq import AsyncGroq
        _groq_client = AsyncGroq(api_key=settings.LLM_API_KEY)
    return _groq_client


async def chat_json(
    system_prompt: str,
    user_message: str,
    *,
    temperature: float = 0.1,
    retries: int = 1,
) -> dict:
    """Call the LLM in JSON mode and return a parsed dict.

    Uses the mock backend when ``settings.LLM_MOCK`` is true.
    """
    if settings.LLM_MOCK:
        return _mock_response(system_prompt)

    client = _get_groq()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]
    last_err: Optional[Exception] = None
    for _ in range(retries + 1):
        try:
            resp = await client.chat.completions.create(
                model=settings.LLM_MODEL,
                messages=messages,
                temperature=temperature,
                response_format={"type": "json_object"},
            )
            return parse_json_object(resp.choices[0].message.content or "")
        except (json.JSONDecodeError, ValueError) as exc:
            last_err = exc
            continue
    raise RuntimeError(f"LLM did not return valid JSON: {last_err}")
