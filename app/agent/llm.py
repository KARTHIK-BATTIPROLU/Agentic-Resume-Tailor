"""Shared Groq client + JSON-mode chat helper used by the agent graph nodes."""
from __future__ import annotations

import json
from typing import Optional

from groq import AsyncGroq

from app.config import GROQ_MODEL, settings
from app.memory.extract import parse_json_object

_client: Optional[AsyncGroq] = None


def get_client() -> AsyncGroq:
    global _client
    if _client is None:
        if not settings.GROQ_API_KEY:
            raise RuntimeError("GROQ_API_KEY is not configured.")
        _client = AsyncGroq(api_key=settings.GROQ_API_KEY)
    return _client


async def chat_json(
    system_prompt: str,
    user_message: str,
    *,
    temperature: float = 0.1,
    retries: int = 1,
) -> dict:
    """Call Groq in JSON mode and return a parsed dict (one retry on parse error)."""
    client = get_client()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]
    last_err: Optional[Exception] = None
    for _ in range(retries + 1):
        try:
            resp = await client.chat.completions.create(
                model=GROQ_MODEL,
                messages=messages,
                temperature=temperature,
                response_format={"type": "json_object"},
            )
            return parse_json_object(resp.choices[0].message.content or "")
        except (json.JSONDecodeError, ValueError) as exc:
            last_err = exc
            continue
    raise RuntimeError(f"LLM did not return valid JSON: {last_err}")
