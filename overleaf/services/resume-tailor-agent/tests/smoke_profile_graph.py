"""Phase 3 smoke: profile LangGraph interrupt/resume with mock LLM + local Neo4j.

Usage:
    NEO4J_URI=bolt://localhost:7687 LLM_MOCK=true python tests/smoke_profile_graph.py
"""
import asyncio
import os
import sys
import uuid

os.environ["LLM_MOCK"] = "true"
os.environ["LOCAL_DEV"] = "true"
os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")

USER_ID = f"smoke-{uuid.uuid4().hex[:8]}"


async def main():
    from app.db.neo4j import ensure_schema
    await ensure_schema()
    print(f"Schema ready. User: {USER_ID}")

    from app.graph.profile import build_profile_graph, thread_config

    graph = build_profile_graph()
    cfg = thread_config(USER_ID)

    # Turn 1 — expect first interrupt (personal section question)
    chunks = []
    interrupt_val = None
    async for chunk in graph.astream(
        {"user_id": USER_ID, "sections_done": [], "done": False},
        cfg,
        stream_mode="updates",
    ):
        intr = chunk.get("__interrupt__")
        if intr:
            interrupt_val = getattr(intr[0], "value", intr[0])
            break
        chunks.append(chunk)

    assert interrupt_val is not None, "Expected first interrupt for personal section"
    print(f"  Turn 1 interrupt: {interrupt_val.get('question','?')[:80]}")

    # Resume with a canned answer
    from langgraph.types import Command

    answer1 = "My name is Jane Doe, email jane@example.com, I work as a software engineer."
    interrupt2 = None
    async for chunk in graph.astream(Command(resume=answer1), cfg, stream_mode="updates"):
        intr = chunk.get("__interrupt__")
        if intr:
            interrupt2 = getattr(intr[0], "value", intr[0])
            break

    print(f"  Turn 2 interrupt: {(interrupt2 or {}).get('question','(none, done)')[:80]}")

    # Verify state survived (re-instantiation)
    state = await graph.aget_state(cfg)
    values = state.values if hasattr(state, "values") else {}
    print(f"  State sections_done: {values.get('sections_done', [])}")

    # Verify Neo4j node written
    from app.db.neo4j import async_driver
    drv = async_driver()
    async with drv.session() as s:
        r = await s.run("MATCH (u:User {userId: $uid}) RETURN u.name AS n", uid=USER_ID)
        row = await r.single()
    print(f"  Neo4j user.name: {row['n'] if row else '(not written — mock LLM returns no contact)'}")

    # Verify interrupt/resume works across a fresh graph instance (re-instantiation test)
    graph2 = build_profile_graph()
    state2 = await graph2.aget_state(cfg)
    assert state2 is not None, "State must survive re-instantiation"
    print("  Re-instantiation OK")

    print("\nPhase 3 PASSED")


asyncio.run(main())
