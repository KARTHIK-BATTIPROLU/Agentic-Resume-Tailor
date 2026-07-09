"""Neo4j driver factory + idempotent schema setup (constraints + vector indexes).

Two drivers are exposed:
  async_driver() — AsyncDriver for main app endpoints
  sync_driver()  — Driver  for the Neo4jCheckpointer (runs in threads)

Both are created lazily, once per process.
"""
from __future__ import annotations

from typing import Optional

import neo4j
from neo4j import AsyncDriver, Driver

from app.config import (
    ACHIEVEMENT_VEC_INDEX,
    EMBED_DIM,
    EXPERIENCE_VEC_INDEX,
    PROJECT_VEC_INDEX,
    SKILL_VEC_INDEX,
    settings,
)

# ── Lazy singletons ───────────────────────────────────────────────────────────
_async_driver: Optional[AsyncDriver] = None
_sync_driver: Optional[Driver] = None


def async_driver() -> AsyncDriver:
    global _async_driver
    if _async_driver is None:
        _async_driver = neo4j.AsyncGraphDatabase.driver(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
        )
    return _async_driver


def sync_driver() -> Driver:
    global _sync_driver
    if _sync_driver is None:
        _sync_driver = neo4j.GraphDatabase.driver(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
        )
    return _sync_driver


# ── Schema queries ────────────────────────────────────────────────────────────
_CONSTRAINTS = [
    "CREATE CONSTRAINT user_userId IF NOT EXISTS FOR (u:User) REQUIRE u.userId IS UNIQUE",
    "CREATE CONSTRAINT pending_pendingId IF NOT EXISTS FOR (p:PendingItem) REQUIRE p.pendingId IS UNIQUE",
    "CREATE CONSTRAINT tailor_sessionId IF NOT EXISTS FOR (s:TailorSession) REQUIRE s.sessionId IS UNIQUE",
    "CREATE CONSTRAINT checkpoint_checkpointId IF NOT EXISTS FOR (c:Checkpoint) REQUIRE c.checkpointId IS UNIQUE",
]

_VEC_INDEXES = [
    (SKILL_VEC_INDEX,       "Skill",       "embedding"),
    (PROJECT_VEC_INDEX,     "Project",     "embedding"),
    (EXPERIENCE_VEC_INDEX,  "Experience",  "embedding"),
    (ACHIEVEMENT_VEC_INDEX, "Achievement", "embedding"),
]


def _vec_index_query(name: str, label: str, prop: str) -> str:
    return (
        f"CREATE VECTOR INDEX `{name}` IF NOT EXISTS "
        f"FOR (n:{label}) ON (n.{prop}) "
        f"OPTIONS {{indexConfig: {{`vector.dimensions`: {EMBED_DIM}, "
        f"`vector.similarity_function`: 'cosine'}}}}"
    )


async def ensure_schema() -> None:
    """Create constraints and vector indexes idempotently on startup."""
    drv = async_driver()
    async with drv.session() as s:
        for cql in _CONSTRAINTS:
            await s.run(cql)
        for name, label, prop in _VEC_INDEXES:
            await s.run(_vec_index_query(name, label, prop))


async def health_check() -> dict:
    """Ping Neo4j; return {neo4j: 'ok'} or raise."""
    drv = async_driver()
    async with drv.session() as s:
        result = await s.run("RETURN 1 AS ping")
        await result.consume()
    return {"neo4j": "ok"}
