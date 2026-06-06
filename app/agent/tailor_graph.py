"""LangGraph — Resume Tailor.

parse_jd -> load_rank -> gap_check
   -> (gaps & under cap) compose_jd_question -> ask_jd_question(interrupt) -> load_rank ...
   -> generate_variants (conservative/balanced/aggressive)
   -> score_variants (deterministic ATS) -> render (3 PDFs) -> END
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from typing import Any, Optional, TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app import db
from app.agent import ats
from app.agent.generate import _coerce
from app.agent.llm import chat_json
from app.agent.prompts import (
    JD_GAP_QUESTION_SYSTEM_PROMPT,
    JD_PARSE_SYSTEM_PROMPT,
    RESUME_ARCHITECT_SYSTEM_PROMPT,
    build_generation_user_message,
    build_jd_gap_question_message,
    build_jd_parse_message,
)
from app.config import MAX_JD_QUESTIONS, OUTPUT_DIR, VARIANT_LABELS
from app.memory.extract import extract_career_facts
from app.memory.profile import apply_extraction, get_profile
from app.memory.retrieve import rank_items
from app.render.render import render_pdf


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


def jd_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def _profile_text(profile: dict[str, Any]) -> str:
    parts: list[str] = [profile.get("headline") or "", profile.get("summary") or ""]
    parts += [s.get("name") or "" for s in profile.get("skills") or []]
    for x in profile.get("experiences") or []:
        parts += [x.get("title") or "", x.get("company") or ""]
        parts += [b.get("text") or "" for b in x.get("bullets") or []]
    for p in profile.get("projects") or []:
        parts += [p.get("name") or "", p.get("description") or ""]
        parts += [str(t) for t in p.get("tech_stack") or []]
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------
async def parse_jd(state: TailorState) -> dict[str, Any]:
    try:
        req = await chat_json(JD_PARSE_SYSTEM_PROMPT, build_jd_parse_message(state["jd_text"]))
    except Exception:
        req = {}
    req.setdefault("required_skills", [])
    req.setdefault("preferred_skills", [])
    req.setdefault("keywords", [])
    return {"jd_requirements": req, "jd_hash": jd_hash(state["jd_text"])}


async def load_rank(state: TailorState) -> dict[str, Any]:
    profile = await get_profile(state["user_id"])
    ranked = await rank_items(state["user_id"], state["jd_text"])
    return {"profile": profile, "ranked": ranked}


def gap_check(state: TailorState) -> dict[str, Any]:
    req = state.get("jd_requirements") or {}
    padded = ats._normalize(_profile_text(state.get("profile") or {}))
    wanted: list[str] = []
    seen = set()
    for key in ("required_skills", "preferred_skills"):
        for term in req.get(key) or []:
            t = str(term).strip()
            if t and t.lower() not in seen:
                seen.add(t.lower())
                wanted.append(t)
    gaps = [t for t in wanted if not ats._term_present(t, padded)]
    return {"gaps": gaps}


def _need_more(state: TailorState) -> str:
    gaps = state.get("gaps") or []
    asked = state.get("questions_asked", 0)
    return "compose_jd_question" if (gaps and asked < MAX_JD_QUESTIONS) else "generate_variants"


async def compose_jd_question(state: TailorState) -> dict[str, Any]:
    gap = (state.get("gaps") or ["the role's requirements"])[0]
    try:
        q = await chat_json(
            JD_GAP_QUESTION_SYSTEM_PROMPT,
            build_jd_gap_question_message(gap, state.get("jd_requirements") or {}),
        )
    except Exception:
        q = {}
    question = q.get("question") or (
        f"The role mentions \"{gap}\". Do you have any experience with it? "
        "(It's fine if you don't.)"
    )
    return {"pending_question": {"question": question, "targets": q.get("targets") or "skill",
                                 "gap": gap}}


async def ask_jd_question(state: TailorState) -> dict[str, Any]:
    q = state.get("pending_question") or {}
    reply = interrupt(q)  # suspends; returns the user's reply on resume
    # Everything below runs once, on resume.
    extraction = await extract_career_facts(reply)
    await apply_extraction(state["user_id"], extraction)
    messages = list(state.get("messages") or [])
    messages.append({"role": "assistant", "content": q.get("question", "")})
    messages.append({"role": "user", "content": reply})
    return {
        "messages": messages,
        "questions_asked": state.get("questions_asked", 0) + 1,
        "pending_question": None,
    }


async def generate_variants(state: TailorState) -> dict[str, Any]:
    profile = state.get("profile") or {}
    ranked = state.get("ranked") or {}
    jd_text = state["jd_text"]
    variants: list[dict[str, Any]] = []
    for label in VARIANT_LABELS:
        msg = build_generation_user_message(profile, ranked, jd_text, variant=label)
        out = _coerce(await chat_json(RESUME_ARCHITECT_SYSTEM_PROMPT, msg))
        variants.append({"label": label, "analysis": out["analysis"], "resume": out["resume"]})
    return {"variants": variants}


def score_variants(state: TailorState) -> dict[str, Any]:
    req = state.get("jd_requirements") or {}
    jd_text = state.get("jd_text", "")
    variants = state.get("variants") or []
    for v in variants:
        v["ats"] = ats.score(v["resume"], req, jd_text)
    return {"variants": variants}


async def render(state: TailorState) -> dict[str, Any]:
    resume_id = uuid4().hex
    variants = state.get("variants") or []
    for v in variants:
        out_dir = os.path.join(OUTPUT_DIR, resume_id, v["label"])
        try:
            v["pdf_path"] = render_pdf(v["resume"], out_dir)
            v["pdf_url"] = f"/resume/{resume_id}/pdf?variant={v['label']}"
        except Exception as exc:  # never let a render failure crash the graph
            v["pdf_path"] = None
            v["pdf_url"] = None
            v["render_error"] = str(exc).splitlines()[0] if str(exc) else "render failed"

    await db.generated_resumes().insert_one(
        {
            "resume_id": resume_id,
            "user_id": state["user_id"],
            "jd_text": state.get("jd_text", ""),
            "jd_hash": state.get("jd_hash", ""),
            "variants": [
                {
                    "label": v["label"],
                    "resume_json": v["resume"],
                    "analysis": v["analysis"],
                    "ats": v.get("ats", {}),
                    "pdf_path": v.get("pdf_path"),
                }
                for v in variants
            ],
            "created_at": datetime.now(timezone.utc),
        }
    )
    return {"variants": variants, "resume_id": resume_id, "done": True}


# ---------------------------------------------------------------------------
# Graph factory
# ---------------------------------------------------------------------------
def build_tailor_graph(checkpointer=None):
    g = StateGraph(TailorState)
    g.add_node("parse_jd", parse_jd)
    g.add_node("load_rank", load_rank)
    g.add_node("gap_check", gap_check)
    g.add_node("compose_jd_question", compose_jd_question)
    g.add_node("ask_jd_question", ask_jd_question)
    g.add_node("generate_variants", generate_variants)
    g.add_node("score_variants", score_variants)
    g.add_node("render", render)

    g.add_edge(START, "parse_jd")
    g.add_edge("parse_jd", "load_rank")
    g.add_edge("load_rank", "gap_check")
    g.add_conditional_edges("gap_check", _need_more, ["compose_jd_question", "generate_variants"])
    g.add_edge("compose_jd_question", "ask_jd_question")
    g.add_edge("ask_jd_question", "load_rank")
    g.add_edge("generate_variants", "score_variants")
    g.add_edge("score_variants", "render")
    g.add_edge("render", END)

    if checkpointer is None:
        from app.agent.checkpointer import get_checkpointer
        checkpointer = get_checkpointer()
    return g.compile(checkpointer=checkpointer)


_graph = None


def get_tailor_graph():
    global _graph
    if _graph is None:
        _graph = build_tailor_graph()
    return _graph


def thread_config(user_id: str, jdh: str) -> dict:
    return {"configurable": {"thread_id": f"tailor:{user_id}:{jdh}"}}
