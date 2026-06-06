"""End-to-end smoke test (internal calls, no server) for the v2 architecture.

(1) Unit-asserts the deterministic ATS scorer (no external services).
(2) Drives the Profile Builder graph through scripted replies and asserts the
    profile populates and a Mongo checkpoint exists.
(3) Runs the Resume Tailor graph on a sample JD and asserts exactly 3 variants
    come back, each with an ATS score and a non-empty PDF.

Requires GROQ_API_KEY + MONGO_URI (e.g. via .env) and tectonic on PATH for (2)+(3).

Run:  python -m scripts.smoke_test
"""
from __future__ import annotations

import asyncio
import os
import sys

from langgraph.types import Command

from app.agent import ats
from app.agent.profile_graph import get_profile_graph
from app.agent.profile_graph import thread_config as profile_cfg
from app.agent.tailor_graph import get_tailor_graph, jd_hash
from app.agent.tailor_graph import thread_config as tailor_cfg
from app.config import CHECKPOINT_COLLECTION, settings
from app import db
from app.memory.profile import get_profile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
USER_ID = "smoke_demo"


def _read(rel: str) -> str:
    with open(os.path.join(_ROOT, rel), "r", encoding="utf-8") as fh:
        return fh.read()


def test_ats_unit() -> None:
    print("[1/4] ATS scorer unit test...")
    req = {
        "required_skills": ["Python", "FastAPI", "Kafka"],
        "preferred_skills": ["Docker"],
        "keywords": ["REST API"],
    }
    resume = {
        "name": "Test User",
        "contact": {"email": "t@example.com"},
        "summary": "Backend engineer.",
        "core_competencies": ["Python", "FastAPI"],
        "experience": [
            {"bullets": ["Built a REST API in Python with FastAPI handling 2M requests/day",
                         "Used Kafka for event streaming"]}
        ],
    }
    r = ats.score(resume, req, "")
    assert 0 <= r["score"] <= 100, r
    assert "Python" in r["matched"] and "FastAPI" in r["matched"], r["matched"]
    assert "Kafka" in r["matched"], r["matched"]
    assert "REST API" in r["matched"], r["matched"]
    assert "Docker" in r["missing"], r["missing"]
    print(f"      OK: score={r['score']}, match_pct={r['match_pct']}, "
          f"matched={r['matched']}, missing={r['missing']}")


async def drive_profile(replies: list[str]) -> dict:
    graph = get_profile_graph()
    cfg = profile_cfg(USER_ID)
    state = {"user_id": USER_ID, "messages": [], "sections_done": [], "section_attempts": {}}
    out = await graph.ainvoke(state, cfg)
    i = 0
    while "__interrupt__" in out and i < len(replies):
        out = await graph.ainvoke(Command(resume=replies[i]), cfg)
        i += 1
    return out


async def main() -> int:
    test_ats_unit()

    if not settings.GROQ_API_KEY or not settings.MONGO_URI:
        print("\nSkipping graph tests: set GROQ_API_KEY and MONGO_URI to run them.")
        return 0

    resume_text = _read("sample_data/sample_resume.txt")
    jd_text = _read("sample_data/sample_jd.txt")

    print("[2/4] Driving Profile Builder graph (scripted replies)...")
    # First reply is the full resume (extraction fills most sections); the rest
    # are graceful fallbacks for any remaining gaps.
    replies = [resume_text] + ["That's everything for now."] * 10
    await drive_profile(replies)
    profile = await get_profile(USER_ID)
    n_skills = len(profile.get("skills") or [])
    n_exp = len(profile.get("experiences") or [])
    print(f"      profile now has {n_skills} skills, {n_exp} experiences")
    assert n_skills >= 1 and n_exp >= 1, "profile did not populate"

    cp = await db.get_db()[CHECKPOINT_COLLECTION].count_documents(
        {"thread_id": f"profile:{USER_ID}"}
    )
    print(f"      checkpoints for thread profile:{USER_ID} = {cp}")
    assert cp > 0, "no checkpoint persisted"

    print("[3/4] Running Resume Tailor graph (3 variants)...")
    tg = get_tailor_graph()
    cfg = tailor_cfg(USER_ID, jd_hash(jd_text))
    out = await tg.ainvoke(
        {"user_id": USER_ID, "jd_text": jd_text, "messages": [], "questions_asked": 0}, cfg
    )
    rounds = 0
    while "__interrupt__" in out and rounds < 5:
        out = await tg.ainvoke(
            Command(resume="I don't have direct experience with that."), cfg
        )
        rounds += 1
    variants = out.get("variants") or []
    assert len(variants) == 3, f"expected 3 variants, got {len(variants)}"

    print("[4/4] Verifying scores + PDFs...")
    for v in variants:
        score = v.get("ats", {}).get("score")
        pdf = v.get("pdf_path")
        assert score is not None, f"variant {v['label']} missing ATS score"
        assert pdf and os.path.exists(pdf) and os.path.getsize(pdf) > 0, \
            f"variant {v['label']} missing non-empty PDF"
        print(f"      {v['label']:<13} score={score:<3} "
              f"match={int(v['ats'].get('match_pct', 0)*100)}%  pdf={pdf}")

    print("\n=== SMOKE TEST PASSED ===")
    print("Scores:", {v["label"]: v["ats"]["score"] for v in variants})
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
