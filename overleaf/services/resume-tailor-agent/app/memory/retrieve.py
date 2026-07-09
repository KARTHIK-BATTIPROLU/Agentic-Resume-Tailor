"""Rank profile items against a JD using Neo4j native vector search (dim 384, cosine).

Falls back to an empty result if the vector index is not yet populated.
"""
from __future__ import annotations

from typing import Any

from app.config import (
    EXPERIENCE_VEC_INDEX,
    PROJECT_VEC_INDEX,
    SKILL_VEC_INDEX,
    TOP_BULLETS,
    TOP_PROJECTS,
    TOP_SKILLS,
)
from app.db.neo4j import async_driver
from app.memory.embed import embed


async def _vector_query(
    session,
    index_name: str,
    user_id: str,
    query_vec: list[float],
    top_k: int,
) -> list[dict[str, Any]]:
    result = await session.run(
        """
        CALL db.index.vector.queryNodes($index, $k, $vec) YIELD node, score
        WHERE node.userId = $userId
        RETURN node {.*} AS item, score
        ORDER BY score DESC
        LIMIT $k
        """,
        index=index_name,
        k=top_k,
        vec=query_vec,
        userId=user_id,
    )
    rows = await result.data()
    return [r["item"] for r in rows]


async def rank_items(
    user_id: str,
    jd_text: str,
    top_k: int | None = None,
) -> dict[str, Any]:
    """Return top-K skills/projects/experiences ranked against the JD text."""
    k_skills = top_k or TOP_SKILLS
    k_projects = top_k or TOP_PROJECTS
    k_bullets = top_k or TOP_BULLETS

    jd_vec = await embed(jd_text)
    drv = async_driver()
    async with drv.session() as s:
        skills = await _vector_query(s, SKILL_VEC_INDEX, user_id, jd_vec, k_skills)
        projects = await _vector_query(s, PROJECT_VEC_INDEX, user_id, jd_vec, k_projects)
        experiences = await _vector_query(s, EXPERIENCE_VEC_INDEX, user_id, jd_vec, k_bullets)

    return {"skills": skills, "projects": projects, "experiences": experiences}


async def get_full_profile_text(user_id: str) -> str:
    """Flat text of the user's profile for gap-detection without vector search."""
    drv = async_driver()
    async with drv.session() as s:
        result = await s.run(
            """
            MATCH (u:User {userId: $userId})
            OPTIONAL MATCH (u)-[:HAS_SKILL]->(sk:Skill)
            OPTIONAL MATCH (u)-[:HAS_EXPERIENCE]->(ex:Experience)
            OPTIONAL MATCH (u)-[:HAS_PROJECT]->(pr:Project)
            RETURN
              collect(DISTINCT sk.name) AS skills,
              collect(DISTINCT ex.title + ' at ' + ex.company) AS roles,
              collect(DISTINCT pr.name + ' ' + coalesce(pr.description,'')) AS projects
            """,
            userId=user_id,
        )
        row = await result.single()
    if not row:
        return ""
    parts = (row["skills"] or []) + (row["roles"] or []) + (row["projects"] or [])
    return " ".join(str(p) for p in parts if p)
