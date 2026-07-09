"""Profile builder LangGraph.

ingest → write_graph → gap_check → compose_question/interrupt → ingest_answer → done

threadId = profile:{userId}

Graph state accumulates in Neo4j via the Neo4jCheckpointer.
Interrupt/resume is standard LangGraph: interrupt() in ask_question node.
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Optional, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.db.neo4j import async_driver
from app.graph.checkpointer import get_checkpointer
from app.llm import chat_json
from app.memory.embed import embed, skill_text, project_text, bullet_text
from app.memory.extract import extract_career_facts
from app.prompts import (
    PROFILE_QUESTION_SYSTEM_PROMPT,
    build_profile_question_message,
)

# Section interview order
SECTIONS = ["personal", "education", "skills", "projects", "experience", "achievements"]
_MAX_ATTEMPTS = 2


# ── State ─────────────────────────────────────────────────────────────────────
class ProfileState(TypedDict, total=False):
    user_id: str
    current_section: Optional[str]
    sections_done: list[str]
    section_attempts: dict[str, int]
    pending_question: Optional[dict[str, Any]]
    last_reply: str
    added: dict[str, int]
    pending: list[dict[str, Any]]
    done: bool


# ── Neo4j write layer ─────────────────────────────────────────────────────────
async def _upsert_user(user_id: str) -> None:
    drv = async_driver()
    async with drv.session() as s:
        await s.run(
            "MERGE (u:User {userId: $uid})",
            uid=user_id,
        )


async def _upsert_facts(user_id: str, facts: dict) -> dict[str, int]:
    """Write HIGH-confidence facts as Neo4j nodes; return counts by type."""
    drv = async_driver()
    added: dict[str, int] = {}
    pending: list[dict] = []

    await _upsert_user(user_id)

    async with drv.session() as s:
        # Skills
        for sk in facts.get("skills") or []:
            conf = (sk.get("confidence") or "HIGH").upper()
            if conf == "HIGH":
                emb = await embed(skill_text(sk))
                await s.run(
                    """
                    MERGE (u:User {userId: $uid})-[:HAS_SKILL]->(sk:Skill {userId: $uid, name: toLower($name)})
                    SET sk.category = $cat, sk.rawName = $name, sk.embedding = $emb
                    """,
                    uid=user_id, name=sk.get("name",""), cat=sk.get("category",""), emb=emb,
                )
                added["skills"] = added.get("skills", 0) + 1
            else:
                pending.append({"type": "skill", "confidence": conf, "data": sk})

        # Experiences
        for ex in facts.get("experiences") or []:
            conf = (ex.get("confidence") or "HIGH").upper()
            if conf == "HIGH":
                bullets_text = " ".join(
                    b.get("text","") if isinstance(b, dict) else str(b)
                    for b in (ex.get("bullets") or [])
                )
                emb = await embed(f"{ex.get('title','')} {ex.get('company','')} {bullets_text}")
                await s.run(
                    """
                    MERGE (u:User {userId: $uid})-[:HAS_EXPERIENCE]->(ex:Experience
                      {userId: $uid, company: $co, title: $title})
                    SET ex.start = $start, ex.end = $end,
                        ex.bullets = $bullets, ex.embedding = $emb
                    """,
                    uid=user_id,
                    co=ex.get("company",""), title=ex.get("title",""),
                    start=ex.get("start",""), end=ex.get("end",""),
                    bullets=json.dumps(ex.get("bullets") or []),
                    emb=emb,
                )
                added["experiences"] = added.get("experiences", 0) + 1
            else:
                pending.append({"type": "experience", "confidence": conf, "data": ex})

        # Projects
        for pr in facts.get("projects") or []:
            conf = (pr.get("confidence") or "HIGH").upper()
            if conf == "HIGH":
                emb = await embed(project_text(pr))
                await s.run(
                    """
                    MERGE (u:User {userId: $uid})-[:HAS_PROJECT]->(pr:Project
                      {userId: $uid, name: $name})
                    SET pr.description = $desc,
                        pr.techStack = $tech, pr.outcomes = $out,
                        pr.link = $link, pr.embedding = $emb
                    """,
                    uid=user_id,
                    name=pr.get("name",""), desc=pr.get("description",""),
                    tech=json.dumps(pr.get("tech_stack") or []),
                    out=json.dumps(pr.get("outcomes") or []),
                    link=pr.get("link",""), emb=emb,
                )
                added["projects"] = added.get("projects", 0) + 1
            else:
                pending.append({"type": "project", "confidence": conf, "data": pr})

        # Education
        for ed in facts.get("education") or []:
            await s.run(
                """
                MERGE (u:User {userId: $uid})-[:HAS_EDUCATION]->(e:Education
                  {userId: $uid, institution: $inst, degree: $deg})
                SET e.start = $start, e.end = $end, e.details = $det
                """,
                uid=user_id,
                inst=ed.get("institution",""), deg=ed.get("degree",""),
                start=ed.get("start",""), end=ed.get("end",""),
                det=ed.get("details",""),
            )
            added["education"] = added.get("education", 0) + 1

        # Achievements
        for ac in facts.get("achievements") or []:
            text = ac.get("text","") if isinstance(ac, dict) else str(ac)
            emb = await embed(text)
            await s.run(
                """
                MERGE (u:User {userId: $uid})-[:HAS_ACHIEVEMENT]->(a:Achievement
                  {userId: $uid, text: $text})
                SET a.embedding = $emb
                """,
                uid=user_id, text=text, emb=emb,
            )
            added["achievements"] = added.get("achievements", 0) + 1

        # Pending (MEDIUM/LOW)
        for p in pending:
            pid = str(uuid.uuid4())
            await s.run(
                """
                MERGE (u:User {userId: $uid})-[:HAS_PENDING]->(pi:PendingItem {pendingId: $pid})
                SET pi.type = $type, pi.confidence = $conf, pi.data = $data
                """,
                uid=user_id, pid=pid,
                type=p["type"], conf=p["confidence"], data=json.dumps(p["data"]),
            )

        # Contact / profile node
        contact = facts.get("contact")
        if contact:
            await s.run(
                """
                MERGE (u:User {userId: $uid})
                SET u.name = coalesce($name, u.name),
                    u.email = coalesce($email, u.email),
                    u.phone = coalesce($phone, u.phone),
                    u.linkedin = coalesce($li, u.linkedin),
                    u.github = coalesce($gh, u.github)
                """,
                uid=user_id,
                name=contact.get("name"), email=contact.get("email"),
                phone=contact.get("phone"), li=contact.get("linkedin"),
                gh=contact.get("github"),
            )

    return added


async def _get_profile_snapshot(user_id: str) -> dict:
    drv = async_driver()
    async with drv.session() as s:
        res = await s.run(
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
        row = await res.single()
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


# ── Gate logic ────────────────────────────────────────────────────────────────
def _gate_met(section: str, profile: dict) -> bool:
    if section == "personal":
        u = profile.get("contact") or {}
        return bool(u.get("name") and u.get("email"))
    if section == "education":
        return bool(profile.get("education"))
    if section == "skills":
        return len(profile.get("skills") or []) >= 3
    if section == "projects":
        return bool(profile.get("projects"))
    if section == "experience":
        return bool(profile.get("experiences"))
    if section == "achievements":
        return bool(profile.get("achievements"))
    return True


def _missing_fields(section: str) -> list[str]:
    return {
        "personal": ["name", "email"],
        "education": ["degree", "institution", "graduation year"],
        "skills": ["at least 3 skills"],
        "projects": ["project name", "description", "outcome"],
        "experience": ["company", "title", "dates", "key accomplishment"],
        "achievements": ["a notable achievement or award"],
    }.get(section, [])


# ── Nodes ─────────────────────────────────────────────────────────────────────
async def route_section(state: ProfileState) -> dict:
    profile = await _get_profile_snapshot(state["user_id"])
    done_set = set(state.get("sections_done") or [])
    for section in SECTIONS:
        if section in done_set:
            continue
        if not _gate_met(section, profile):
            return {"current_section": section, "done": False}
    return {"current_section": None, "done": True}


async def compose_question(state: ProfileState) -> dict:
    section = state["current_section"]
    profile = await _get_profile_snapshot(state["user_id"])
    missing = _missing_fields(section)
    msg = build_profile_question_message(section, profile, missing)
    try:
        q = await chat_json(PROFILE_QUESTION_SYSTEM_PROMPT, msg)
    except Exception:
        q = {}
    question = q.get("question") or f"Tell me about your {section}."
    return {
        "pending_question": {
            "question": question,
            "field": q.get("field") or (missing[0] if missing else section),
            "section": section,
        }
    }


def ask_question(state: ProfileState) -> dict:
    q = state.get("pending_question") or {}
    reply = interrupt(q)
    return {"last_reply": reply, "pending_question": None}


async def ingest_answer(state: ProfileState) -> dict:
    facts = await extract_career_facts(state.get("last_reply") or "")
    added = await _upsert_facts(state["user_id"], facts)
    section = state.get("current_section")
    attempts = dict(state.get("section_attempts") or {})
    if section:
        attempts[section] = attempts.get(section, 0) + 1
    done_set = list(state.get("sections_done") or [])
    profile = await _get_profile_snapshot(state["user_id"])
    if section and (
        _gate_met(section, profile) or attempts.get(section, 0) >= _MAX_ATTEMPTS
    ):
        if section not in done_set:
            done_set.append(section)
    return {"added": added, "sections_done": done_set, "section_attempts": attempts}


def _route_or_end(state: ProfileState) -> str:
    return END if state.get("done") else "compose_question"


# ── Graph factory ─────────────────────────────────────────────────────────────
def build_profile_graph(checkpointer=None):
    g = StateGraph(ProfileState)
    g.add_node("route_section", route_section)
    g.add_node("compose_question", compose_question)
    g.add_node("ask_question", ask_question)
    g.add_node("ingest_answer", ingest_answer)

    g.add_edge(START, "route_section")
    g.add_conditional_edges("route_section", _route_or_end, ["compose_question", END])
    g.add_edge("compose_question", "ask_question")
    g.add_edge("ask_question", "ingest_answer")
    g.add_edge("ingest_answer", "route_section")

    return g.compile(checkpointer=checkpointer or get_checkpointer())


_graph = None


def get_profile_graph():
    global _graph
    if _graph is None:
        _graph = build_profile_graph()
    return _graph


def thread_config(user_id: str) -> dict:
    return {"configurable": {"thread_id": f"profile:{user_id}"}}
