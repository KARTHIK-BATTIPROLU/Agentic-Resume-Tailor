"""Phase 4 smoke: tailor LangGraph end-to-end with mock LLM + local Neo4j.

Usage:
    NEO4J_URI=bolt://localhost:7687 LLM_MOCK=true python tests/smoke_tailor_graph.py
"""
import asyncio
import json
import os
import uuid

os.environ["LLM_MOCK"] = "true"
os.environ["LOCAL_DEV"] = "true"
os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")

USER_ID = f"smoke-tailor-{uuid.uuid4().hex[:8]}"
JD = """
We are looking for a Senior Python Engineer with experience in FastAPI, PostgreSQL,
Docker, and Kubernetes. You will build scalable REST APIs and work in a CI/CD environment.
Strong communication skills required.
"""


async def _seed_profile():
    """Put minimal profile data in Neo4j so vector queries return something."""
    from app.graph.profile import _upsert_facts
    facts = {
        "contact": {"name": "Jane Doe", "email": "jane@example.com"},
        "skills": [
            {"name": "Python", "category": "language", "confidence": "HIGH"},
            {"name": "FastAPI", "category": "framework", "confidence": "HIGH"},
            {"name": "Docker", "category": "devops", "confidence": "HIGH"},
        ],
        "experiences": [{
            "company": "Acme", "title": "Software Engineer",
            "start": "2021", "end": "2024",
            "bullets": [{"text": "Built REST APIs serving 10k rps", "metric": "10k rps"}],
            "confidence": "HIGH",
        }],
        "projects": [{
            "name": "API Gateway",
            "description": "FastAPI-based gateway",
            "tech_stack": ["Python", "FastAPI", "PostgreSQL"],
            "outcomes": [{"text": "Reduced latency by 40%", "metric": "40%"}],
            "confidence": "HIGH",
        }],
        "education": [{"degree": "BS Computer Science", "institution": "MIT",
                        "start": "2017", "end": "2021"}],
        "achievements": [],
    }
    added = await _upsert_facts(USER_ID, facts)
    print(f"  Seeded profile: {added}")


async def main():
    from app.db.neo4j import ensure_schema
    await ensure_schema()
    print(f"Schema ready. User: {USER_ID}")

    await _seed_profile()

    from app.graph.tailor import build_tailor_graph, jd_hash, thread_config

    graph = build_tailor_graph()
    jdh = jd_hash(JD)
    cfg = thread_config(USER_ID, jdh)

    graph_input = {"user_id": USER_ID, "jd_text": JD, "messages": [], "questions_asked": 0}

    interrupt_val = None
    async for chunk in graph.astream(graph_input, cfg, stream_mode="updates"):
        intr = chunk.get("__interrupt__")
        if intr:
            interrupt_val = getattr(intr[0], "value", intr[0])
            print(f"  Gap question: {interrupt_val.get('question','?')[:80]}")
            break

    # If there was an interrupt, answer it and continue
    if interrupt_val:
        from langgraph.types import Command
        async for chunk in graph.astream(
            Command(resume="I don't have that experience."), cfg, stream_mode="updates"
        ):
            intr = chunk.get("__interrupt__")
            if intr:
                iv2 = getattr(intr[0], "value", intr[0])
                print(f"  Gap question 2: {iv2.get('question','?')[:80]}")
                # Answer and continue until done
                async for chunk2 in graph.astream(
                    Command(resume="No, not really."), cfg, stream_mode="updates"
                ):
                    pass
                break

    state = await graph.aget_state(cfg)
    values = state.values if hasattr(state, "values") else {}
    variants = values.get("variants") or []
    resume_id = values.get("resume_id", "")

    assert len(variants) == 3, f"Expected 3 variants, got {len(variants)}: {[v.get('label') for v in variants]}"
    print(f"  Variants: {[v.get('label') for v in variants]}")

    for v in variants:
        assert v.get("tex"), f"Variant {v.get('label')} has no .tex"
        assert v.get("ats"), f"Variant {v.get('label')} has no ATS score"
        score = v["ats"].get("score", -1)
        print(f"  {v['label']}: ATS={score}, tex_len={len(v['tex'])}")

    # Verify TailorSession persisted in Neo4j
    assert resume_id, "resume_id must be set"
    from app.db.neo4j import async_driver
    drv = async_driver()
    async with drv.session() as s:
        r = await s.run(
            "MATCH (u:User {userId:$uid})-[:HAS_SESSION]->(ts:TailorSession {resumeId:$rid}) RETURN ts.sessionId AS sid",
            uid=USER_ID, rid=resume_id,
        )
        row = await r.single()
    assert row, "TailorSession not found in Neo4j"
    print(f"  TailorSession in Neo4j: {row['sid'][:12]}...")

    print("\nPhase 4 PASSED")


asyncio.run(main())
