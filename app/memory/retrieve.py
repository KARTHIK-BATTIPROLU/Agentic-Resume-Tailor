"""Rank a user's own items against a job description with in-process cosine.

Embeddings are stored inline in each Mongo doc; we load the user's items, score
them against the JD embedding with numpy cosine, and return the top-N per type.
"""
from __future__ import annotations

from typing import Any

from app import db
from app.config import TOP_BULLETS, TOP_PROJECTS, TOP_SKILLS
from app.memory.embed import cosine, embed


def _top(items: list[dict[str, Any]], n: int) -> list[dict[str, Any]]:
    items.sort(key=lambda x: x["score"], reverse=True)
    return items[:n]


async def rank_items(user_id: str, jd_text: str) -> dict[str, list[dict[str, Any]]]:
    """Return ``{"bullets": [...], "projects": [...], "skills": [...]}``.

    Each entry is ``{"text", "item_id", "score"}``. Empty profiles yield empty
    lists rather than errors.
    """
    jd_vec = await embed(jd_text or "")

    bullets: list[dict[str, Any]] = []
    async for exp in db.experiences().find({"user_id": user_id}):
        for b in exp.get("bullets") or []:
            emb = b.get("embedding")
            if not emb:
                continue
            bullets.append(
                {
                    "text": b.get("text", ""),
                    "item_id": exp.get("item_id"),
                    "score": round(cosine(jd_vec, emb), 4),
                }
            )

    projects: list[dict[str, Any]] = []
    async for p in db.projects().find({"user_id": user_id}):
        emb = p.get("embedding")
        if not emb:
            continue
        projects.append(
            {
                "text": p.get("name", ""),
                "item_id": p.get("item_id"),
                "score": round(cosine(jd_vec, emb), 4),
            }
        )

    skills: list[dict[str, Any]] = []
    async for s in db.skills().find({"user_id": user_id}):
        emb = s.get("embedding")
        if not emb:
            continue
        skills.append(
            {
                "text": s.get("name", ""),
                "item_id": s.get("item_id"),
                "score": round(cosine(jd_vec, emb), 4),
            }
        )

    return {
        "bullets": _top(bullets, TOP_BULLETS),
        "projects": _top(projects, TOP_PROJECTS),
        "skills": _top(skills, TOP_SKILLS),
    }
