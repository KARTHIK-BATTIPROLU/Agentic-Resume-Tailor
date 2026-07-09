"""Phase 1 smoke: verify Neo4j connection, constraints, and vector indexes.

Usage:
    NEO4J_URI=bolt://localhost:7687 python tests/smoke_neo4j.py
"""
import asyncio
import os
import sys

os.environ.setdefault("LLM_MOCK", "true")
os.environ.setdefault("LOCAL_DEV", "true")


async def main():
    from app.db.neo4j import ensure_schema, health_check

    print("Pinging Neo4j...")
    r = await health_check()
    assert r.get("neo4j") == "ok", f"ping failed: {r}"
    print("  PING OK")

    print("Creating schema (idempotent)...")
    await ensure_schema()
    print("  SCHEMA OK")

    # Verify constraints exist
    from app.db.neo4j import async_driver
    drv = async_driver()
    async with drv.session() as s:
        res = await s.run("SHOW CONSTRAINTS YIELD name RETURN collect(name) AS names")
        row = await res.single()
        names = row["names"] if row else []
        expected = {"user_userId", "pending_pendingId", "tailor_sessionId", "checkpoint_checkpointId"}
        missing = expected - set(names)
        assert not missing, f"Missing constraints: {missing}"
        print(f"  CONSTRAINTS OK ({len(names)} total)")

        res2 = await s.run("SHOW INDEXES YIELD name, type WHERE type = 'VECTOR' RETURN collect(name) AS names")
        row2 = await res2.single()
        vec_names = row2["names"] if row2 else []
        expected_vec = {"skill_embedding", "project_embedding", "experience_embedding", "achievement_embedding"}
        missing_vec = expected_vec - set(vec_names)
        assert not missing_vec, f"Missing vector indexes: {missing_vec}"
        print(f"  VECTOR INDEXES OK ({len(vec_names)} total)")

    print("\nPhase 1 PASSED")


asyncio.run(main())
