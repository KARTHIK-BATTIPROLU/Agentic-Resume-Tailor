"""Multi-turn stateful session endpoints (Neo4j edition).

Tailor flow:
  POST /session/tailor/start   → {status:"question", question:{...}, thread_id}
                                 | {status:"variants", variants:[...], resume_id}
  POST /session/tailor/answer  → (repeat until status:"variants")
  POST /session/tailor/confirm → {tex:"...", label:"...", ats:{...}}

Profile interview flow:
  POST /session/profile/start  → {status:"question", question:{...}, thread_id}
  POST /session/profile/answer → (repeat until status:"done")

Profile one-shot init:
  POST /session/profile/init   → {added:{...}, profile:{...}}
"""
from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from langgraph.types import Command
from pydantic import BaseModel

from app.db.neo4j import async_driver
from app.graph.profile import (
    _get_profile_snapshot,
    _upsert_facts,
    get_profile_graph,
    thread_config as profile_thread_config,
)
from app.graph.tailor import (
    get_tailor_graph,
    jd_hash,
    thread_config as tailor_thread_config,
)
from app.memory.extract import extract_career_facts

router = APIRouter(prefix="/session")


# ── Helpers ───────────────────────────────────────────────────────────────────
def _interrupt_value(chunk: dict) -> Optional[dict]:
    intr_list = chunk.get("__interrupt__")
    if not intr_list:
        return None
    intr = intr_list[0]
    value = getattr(intr, "value", intr)
    return value if isinstance(value, dict) else {"question": str(value)}


def _variant_summary(v: dict) -> dict:
    return {
        "label": v.get("label"),
        "tex": v.get("tex", ""),
        "ats": v.get("ats", {}),
        "analysis": v.get("analysis", {}),
    }


async def _run_tailor_until_interrupt_or_done(graph_input: Any, config: dict) -> dict:
    graph = get_tailor_graph()
    thread_id = config["configurable"]["thread_id"]

    async for chunk in graph.astream(graph_input, config, stream_mode="updates"):
        q = _interrupt_value(chunk)
        if q is not None:
            return {"status": "question", "thread_id": thread_id, "question": q}

    state = await graph.aget_state(config)
    values = state.values if hasattr(state, "values") else (state or {})
    variants = values.get("variants") or []
    resume_id = values.get("resume_id", "")
    return {
        "status": "variants",
        "thread_id": thread_id,
        "resume_id": resume_id,
        "variants": [_variant_summary(v) for v in variants],
    }


async def _run_profile_until_interrupt_or_done(graph_input: Any, config: dict) -> dict:
    graph = get_profile_graph()
    thread_id = config["configurable"]["thread_id"]

    async for chunk in graph.astream(graph_input, config, stream_mode="updates"):
        q = _interrupt_value(chunk)
        if q is not None:
            return {"status": "question", "thread_id": thread_id, "question": q}

    return {"status": "done", "thread_id": thread_id}


# ── Profile one-shot init ─────────────────────────────────────────────────────
class ProfileInitIn(BaseModel):
    user_id: str
    text: str


@router.post("/profile/init")
async def profile_init(payload: ProfileInitIn) -> dict:
    if not payload.text.strip():
        raise HTTPException(status_code=400, detail="text is required")
    try:
        facts = await extract_career_facts(payload.text)
        added = await _upsert_facts(payload.user_id, facts)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {"added": added, "profile": await _get_profile_snapshot(payload.user_id)}


# ── Profile interview — start ─────────────────────────────────────────────────
class ProfileStartIn(BaseModel):
    user_id: str


@router.post("/profile/start")
async def profile_start(payload: ProfileStartIn) -> dict:
    config = profile_thread_config(payload.user_id)
    graph_input = {"user_id": payload.user_id, "sections_done": [], "done": False}
    try:
        return await _run_profile_until_interrupt_or_done(graph_input, config)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))


# ── Profile interview — answer ────────────────────────────────────────────────
class ProfileAnswerIn(BaseModel):
    user_id: str
    thread_id: str
    message: str


@router.post("/profile/answer")
async def profile_answer(payload: ProfileAnswerIn) -> dict:
    if not payload.message.strip():
        raise HTTPException(status_code=400, detail="message is required")
    config = {"configurable": {"thread_id": payload.thread_id}}
    try:
        return await _run_profile_until_interrupt_or_done(
            Command(resume=payload.message), config
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))


# ── Tailor — start ────────────────────────────────────────────────────────────
class TailorStartIn(BaseModel):
    user_id: str
    job_description: str
    resume_text: Optional[str] = None


@router.post("/tailor/start")
async def tailor_start(payload: TailorStartIn) -> dict:
    jd = payload.job_description.strip()
    if not jd:
        raise HTTPException(status_code=400, detail="job_description is required")

    if payload.resume_text and payload.resume_text.strip():
        try:
            facts = await extract_career_facts(payload.resume_text)
            await _upsert_facts(payload.user_id, facts)
        except Exception:
            pass

    jdh = jd_hash(jd)
    config = tailor_thread_config(payload.user_id, jdh)
    graph_input: Any = {
        "user_id": payload.user_id,
        "jd_text": jd,
        "messages": [],
        "questions_asked": 0,
    }
    try:
        return await _run_tailor_until_interrupt_or_done(graph_input, config)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))


# ── Tailor — answer ───────────────────────────────────────────────────────────
class TailorAnswerIn(BaseModel):
    user_id: str
    thread_id: str
    message: str


@router.post("/tailor/answer")
async def tailor_answer(payload: TailorAnswerIn) -> dict:
    if not payload.message.strip():
        raise HTTPException(status_code=400, detail="message is required")
    config = {"configurable": {"thread_id": payload.thread_id}}
    try:
        return await _run_tailor_until_interrupt_or_done(
            Command(resume=payload.message), config
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))


# ── Tailor — confirm (return .tex for chosen variant) ────────────────────────
class TailorConfirmIn(BaseModel):
    user_id: str
    resume_id: str
    variant_label: str


@router.post("/tailor/confirm")
async def tailor_confirm(payload: TailorConfirmIn) -> dict:
    drv = async_driver()
    async with drv.session() as s:
        result = await s.run(
            """
            MATCH (u:User {userId: $uid})-[:HAS_SESSION]->(ts:TailorSession {resumeId: $rid})
            RETURN ts.variants AS variants
            """,
            uid=payload.user_id,
            rid=payload.resume_id,
        )
        row = await result.single()

    if not row:
        raise HTTPException(status_code=404, detail="resume_id not found")

    raw = row["variants"]
    try:
        variants: list[dict] = json.loads(raw) if isinstance(raw, str) else list(raw)
    except Exception:
        variants = []

    match = next((v for v in variants if v.get("label") == payload.variant_label), None)
    if not match and variants:
        match = variants[0]
    if not match:
        raise HTTPException(status_code=404, detail="variant not found")

    tex = match.get("tex", "")
    if not tex:
        raise HTTPException(status_code=500, detail="variant has no tex")

    return {"tex": tex, "label": match.get("label"), "ats": match.get("ats", {})}
