"""Local embeddings (MiniLM) + cosine similarity.

The SentenceTransformer model is loaded exactly once at import time. Encoding is
offloaded to a thread so it never blocks the event loop.
"""
from __future__ import annotations

import asyncio
from typing import Any, Sequence

import numpy as np
from sentence_transformers import SentenceTransformer

from app.config import EMBED_MODEL

# Loaded once, reused for the life of the process.
_model = SentenceTransformer(EMBED_MODEL)


def _encode_sync(text: str) -> list[float]:
    vec = _model.encode(text or "", normalize_embeddings=False)
    return np.asarray(vec, dtype=np.float32).tolist()


async def embed(text: str) -> list[float]:
    """Embed a single string into a 384-d vector (off the event loop)."""
    return await asyncio.to_thread(_encode_sync, text)


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity between two equal-length vectors."""
    va = np.asarray(a, dtype=np.float32)
    vb = np.asarray(b, dtype=np.float32)
    na = float(np.linalg.norm(va))
    nb = float(np.linalg.norm(vb))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(va, vb) / (na * nb))


# ---------------------------------------------------------------------------
# Embed-text builders — what gets embedded for each item type
# ---------------------------------------------------------------------------
def skill_text(skill: dict[str, Any]) -> str:
    parts = [skill.get("name") or ""]
    if skill.get("category"):
        parts.append(str(skill["category"]))
    return " ".join(p for p in parts if p).strip()


def project_text(project: dict[str, Any]) -> str:
    parts = [project.get("name") or "", project.get("description") or ""]
    tech = project.get("tech_stack") or []
    if tech:
        parts.append(" ".join(str(t) for t in tech))
    for oc in project.get("outcomes") or []:
        if isinstance(oc, dict) and oc.get("text"):
            parts.append(str(oc["text"]))
    return " ".join(p for p in parts if p).strip()


def bullet_text(bullet: dict[str, Any]) -> str:
    return (bullet.get("text") or "").strip()
