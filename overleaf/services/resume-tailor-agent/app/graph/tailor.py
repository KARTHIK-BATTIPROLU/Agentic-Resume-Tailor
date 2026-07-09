"""Tailor LangGraph (Neo4j edition).

parse_jd → load_rank → gap_check
  → (gaps & under cap) compose_jd_question → ask_jd_question/interrupt → load_rank …
  → generate_variants → score_variants → finalize_variants → END

threadId = tailor:{userId}:{jdHash}

Variants and session metadata are persisted as a :TailorSession node in Neo4j
(no MongoDB, no Redis — Neo4j is the ONLY datastore).
"""
from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Optional, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.ats import score as ats_score, _normalize as ats_normalize, _term_present
from app.config import MAX_JD_QUESTIONS, VARIANT_LABELS
from app.db.neo4j import async_driver
from app.graph.checkpointer import get_checkpointer
from app.llm import chat_json
from app.memory.extract import extract_career_facts
from app.memory.retrieve import rank_items
from app.prompts import (
    JD_GAP_QUESTION_SYSTEM_PROMPT,
    JD_PARSE_SYSTEM_PROMPT,
    RESUME_ARCHITECT_SYSTEM_PROMPT,
    build_generation_user_message,
    build_jd_gap_question_message,
    build_jd_parse_message,
    VARIANT_DIRECTIVES,
)
from app.render.render import build_tex


# ── State ─────────────────────────────────────────────────────────────────────
class TailorState(TypedDict, total=False):
    user_id: str
    jd_text: str
    jd_hash: str
    messages: list[dict[str, Any]]
    jd_requirements: dict[str, Any]
    profile: dict[str, Any]
    ranked: dict[str, Any]
    gaps: list[str]
    questions_asked: int
    pending_question: Optional[dict[str, Any]]
    variants: list[dict[str, Any]]
    resume_id: str
    done: bool


# ── Helpers ────────────────────────────────────────────────────────────────────
def jd_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode()).hexdigest()[:16]


def thread_config(user_id: str, jdh: str) -> dict:
    return {"configurable": {"thread_id": f"tailor:{user_id}:{jdh}"}}


def _coerce(out: Any) -> dict:
    if not isinstance(out, dict):
        return {"analysis": {}, "resume": {}}
    if "resume" not in out:
        out = {"analysis": out.get("analysis", {}), "resume": out}
    return out


async def _get_profile(user_id: str) -> dict:
    drv = async_driver()
    async with drv.session() as s:
        result = await s.run(
            """
            MATCH (u:User {userId: $uid})
            OPTIONAL MATCH (u)-[:HAS_SKILL]->(sk:Skill)
            OPTIONAL MATCH (u)-[:HAS_EXPERIENCE]->(ex:Experience)
            OPTIONAL MATCH (u)-[:HAS_PROJECT]->(pr:Project)
            OPTIONAL MATCH (u)-[:HAS_EDUCATION]->(ed:Education)
            OPTIONAL MATCH (u)-[:HAS_ACHIEVEMENT]->(ac:Achievement)
            RETURN u {.*} AS user,
                   collect(DISTINCT sk {.*}) AS skills,
                   collect(DISTINCT ex {.*}) AS experiences,
                   collect(DISTINCT pr {.*}) AS projects,
                   collect(DISTINCT ed {.*}) AS education,
                   collect(DISTINCT ac {.*}) AS achievements
            """,
            uid=user_id,
        )
        row = await result.single()
    if not row:
        return {"user_id": user_id}
    return {
        "user_id": user_id,
        "contact": row["user"],
        "skills": row["skills"],
        "experiences": row["experiences"],
        "projects": row["projects"],
        "education": row["education"],
        "achievements": row["achievements"],
    }


def _profile_text(profile: dict) -> str:
    parts: list[str] = []
    u = profile.get("contact") or {}
    for f in ("name", "headline", "summary"):
        if u.get(f):
            parts.append(str(u[f]))
    for sk in profile.get("skills") or []:
        if sk.get("name"):
            parts.append(sk["name"])
    for ex in profile.get("experiences") or []:
        parts.append(f"{ex.get('title','')} {ex.get('company','')}")
        bullets = ex.get("bullets") or []
        if isinstance(bullets, str):
            try:
                bullets = json.loads(bullets)
            except Exception:
                bullets = [bullets]
        for b in bullets:
            if isinstance(b, dict):
                parts.append(b.get("text") or "")
            else:
                parts.append(str(b))
    for pr in profile.get("projects") or []:
        parts.append(f"{pr.get('name','')} {pr.get('description','')}")
    return " ".join(p for p in parts if p)


async def _upsert_profile_answer(user_id: str, reply: str) -> None:
    facts = await extract_career_facts(reply)
    if not facts:
        return
    # Reuse the write path from graph.profile
    from app.graph.profile import _upsert_facts
    await _upsert_facts(user_id, facts)


# ── Nodes ─────────────────────────────────────────────────────────────────────
async def parse_jd(state: TailorState) -> dict:
    try:
        req = await chat_json(JD_PARSE_SYSTEM_PROMPT, build_jd_parse_message(state["jd_text"]))
    except Exception:
        req = {}
    req.setdefault("required_skills", [])
    req.setdefault("preferred_skills", [])
    req.setdefault("keywords", [])
    return {"jd_requirements": req, "jd_hash": jd_hash(state["jd_text"])}


async def load_rank(state: TailorState) -> dict:
    profile = await _get_profile(state["user_id"])
    try:
        ranked = await rank_items(state["user_id"], state["jd_text"])
    except Exception:
        ranked = {"skills": [], "projects": [], "experiences": []}
    return {"profile": profile, "ranked": ranked}


def gap_check(state: TailorState) -> dict:
    req = state.get("jd_requirements") or {}
    padded = ats_normalize(_profile_text(state.get("profile") or {}))
    wanted: list[str] = []
    seen: set[str] = set()
    for key in ("required_skills", "preferred_skills"):
        for term in req.get(key) or []:
            t = str(term).strip()
            if t and t.lower() not in seen:
                seen.add(t.lower())
                wanted.append(t)
    gaps = [t for t in wanted if not _term_present(t, padded)]
    return {"gaps": gaps}


def _need_more(state: TailorState) -> str:
    gaps = state.get("gaps") or []
    asked = state.get("questions_asked", 0)
    return "compose_jd_question" if (gaps and asked < MAX_JD_QUESTIONS) else "generate_variants"


async def compose_jd_question(state: TailorState) -> dict:
    gap = (state.get("gaps") or ["the role's requirements"])[0]
    try:
        q = await chat_json(
            JD_GAP_QUESTION_SYSTEM_PROMPT,
            build_jd_gap_question_message(gap, state.get("jd_requirements") or {}),
        )
    except Exception:
        q = {}
    question = q.get("question") or (
        f"The role mentions \"{gap}\". Do you have any relevant experience? "
        "(It's fine if you don't.)"
    )
    return {
        "pending_question": {
            "question": question,
            "targets": q.get("targets") or "skill",
            "gap": gap,
        }
    }


async def ask_jd_question(state: TailorState) -> dict:
    q = state.get("pending_question") or {}
    reply = interrupt(q)
    await _upsert_profile_answer(state["user_id"], reply)
    messages = list(state.get("messages") or [])
    messages.append({"role": "assistant", "content": q.get("question", "")})
    messages.append({"role": "user", "content": reply})
    return {
        "messages": messages,
        "questions_asked": state.get("questions_asked", 0) + 1,
        "pending_question": None,
    }


async def generate_variants(state: TailorState) -> dict:
    profile = state.get("profile") or {}
    ranked = state.get("ranked") or {}
    jd_text = state["jd_text"]
    variants: list[dict] = []
    for label in VARIANT_LABELS:
        msg = build_generation_user_message(profile, ranked, jd_text, variant=label)
        try:
            out = _coerce(await chat_json(RESUME_ARCHITECT_SYSTEM_PROMPT, msg))
        except Exception:
            out = {"analysis": {}, "resume": {}}
        variants.append({"label": label, "analysis": out["analysis"], "resume": out["resume"]})
    return {"variants": variants}


def score_variants(state: TailorState) -> dict:
    req = state.get("jd_requirements") or {}
    jd_text = state.get("jd_text", "")
    variants = list(state.get("variants") or [])
    for v in variants:
        v["ats"] = ats_score(v.get("resume") or {}, req, jd_text)
    return {"variants": variants}


async def finalize_variants(state: TailorState) -> dict:
    """Build .tex for each variant; persist session to Neo4j :TailorSession node."""
    resume_id = uuid.uuid4().hex
    variants = list(state.get("variants") or [])

    for v in variants:
        v["tex"] = build_tex(v.get("resume") or {})

    session_id = uuid.uuid4().hex
    drv = async_driver()
    async with drv.session() as s:
        await s.run(
            """
            MERGE (u:User {userId: $uid})
            CREATE (u)-[:HAS_SESSION]->(ts:TailorSession {sessionId: $sid})
            SET ts.resumeId = $resumeId,
                ts.jdHash   = $jdHash,
                ts.variants = $variants,
                ts.createdAt = datetime()
            """,
            uid=state["user_id"],
            sid=session_id,
            resumeId=resume_id,
            jdHash=state.get("jd_hash", ""),
            variants=json.dumps([
                {
                    "label": v["label"],
                    "resume_json": v.get("resume") or {},
                    "tex": v["tex"],
                    "analysis": v.get("analysis") or {},
                    "ats": v.get("ats") or {},
                }
                for v in variants
            ]),
        )

    return {"variants": variants, "resume_id": resume_id, "done": True}


# ── Graph factory ─────────────────────────────────────────────────────────────
def build_tailor_graph(checkpointer=None):
    g = StateGraph(TailorState)
    g.add_node("parse_jd", parse_jd)
    g.add_node("load_rank", load_rank)
    g.add_node("gap_check", gap_check)
    g.add_node("compose_jd_question", compose_jd_question)
    g.add_node("ask_jd_question", ask_jd_question)
    g.add_node("generate_variants", generate_variants)
    g.add_node("score_variants", score_variants)
    g.add_node("finalize_variants", finalize_variants)

    g.add_edge(START, "parse_jd")
    g.add_edge("parse_jd", "load_rank")
    g.add_edge("load_rank", "gap_check")
    g.add_conditional_edges(
        "gap_check", _need_more, ["compose_jd_question", "generate_variants"]
    )
    g.add_edge("compose_jd_question", "ask_jd_question")
    g.add_edge("ask_jd_question", "load_rank")
    g.add_edge("generate_variants", "score_variants")
    g.add_edge("score_variants", "finalize_variants")
    g.add_edge("finalize_variants", END)

    return g.compile(checkpointer=checkpointer or get_checkpointer())


_graph = None


def get_tailor_graph():
    global _graph
    if _graph is None:
        _graph = build_tailor_graph()
    return _graph
