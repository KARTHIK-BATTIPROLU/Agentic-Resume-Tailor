"""LangGraph — Profile Builder.

A human-in-the-loop interview that asks ONE question at a time, section by section
(Personal -> Education -> Skills -> Projects -> Experience -> Achievements),
extracts structured facts from each reply, and upserts them to the profile.

Loop: route_section -> compose_question -> ask_question(interrupt) -> ingest ->
validate -> upsert -> route_section -> ... -> END.

The question is composed (an LLM call) in ``compose_question`` and committed to
state BEFORE the interrupt, so resuming re-runs only ``ask_question`` and never
re-issues the LLM call.
"""
from __future__ import annotations

from typing import Any, Optional, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.agent.llm import chat_json
from app.agent.prompts import (
    PROFILE_QUESTION_SYSTEM_PROMPT,
    build_profile_question_message,
)
from app.memory.extract import extract_career_facts
from app.memory.profile import apply_extraction, get_profile

# Fixed section order for the interview.
SECTIONS = ["personal", "education", "skills", "projects", "experience", "achievements"]

# Max times we ask about a single section before moving on (prevents infinite loops
# when the user has nothing for a section).
_MAX_ATTEMPTS = 2


class ProfileState(TypedDict, total=False):
    user_id: str
    messages: list[dict[str, Any]]
    current_section: Optional[str]
    collected: dict[str, Any]
    pending_question: Optional[dict[str, Any]]
    reasoning: str
    confidence_map: dict[str, Any]
    sections_done: list[str]
    section_attempts: dict[str, int]
    last_reply: str
    added: dict[str, int]
    pending: list[dict[str, Any]]
    done: bool


# ---------------------------------------------------------------------------
# Gate logic — "present and sensible" required fields per section
# ---------------------------------------------------------------------------
def _gate_met(section: str, profile: dict[str, Any]) -> bool:
    if section == "personal":
        c = profile.get("contact") or {}
        return bool(c.get("name") and c.get("email"))
    if section == "education":
        return any(e.get("degree") and e.get("institution") and e.get("end")
                   for e in profile.get("education") or [])
    if section == "skills":
        return len(profile.get("skills") or []) >= 3
    if section == "projects":
        return any(p.get("name") and p.get("description") and (p.get("outcomes"))
                   for p in profile.get("projects") or [])
    if section == "experience":
        return any(x.get("company") and x.get("title") and x.get("start") and x.get("bullets")
                   for x in profile.get("experiences") or [])
    if section == "achievements":
        return len(profile.get("achievements") or []) >= 1
    return True


def _missing_fields(section: str, profile: dict[str, Any]) -> list[str]:
    if section == "personal":
        c = profile.get("contact") or {}
        return [f for f in ("name", "email") if not c.get(f)]
    if section == "education":
        return ["degree", "institution", "graduation_year"]
    if section == "skills":
        have = len(profile.get("skills") or [])
        return [f"at least {max(0, 3 - have)} more skills"]
    if section == "projects":
        return ["project name", "description", "an outcome/result"]
    if section == "experience":
        return ["company", "job title", "dates", "a key accomplishment bullet"]
    if section == "achievements":
        return ["a notable achievement, award, or talk (optional)"]
    return []


def _snapshot(section: str, profile: dict[str, Any]) -> Any:
    mapping = {
        "personal": profile.get("contact"),
        "education": profile.get("education"),
        "skills": [s.get("name") for s in profile.get("skills") or []],
        "projects": [p.get("name") for p in profile.get("projects") or []],
        "experience": [
            {"company": x.get("company"), "title": x.get("title")}
            for x in profile.get("experiences") or []
        ],
        "achievements": profile.get("achievements"),
    }
    return mapping.get(section)


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------
async def route_section(state: ProfileState) -> dict[str, Any]:
    profile = await get_profile(state["user_id"])
    done_set = set(state.get("sections_done") or [])
    for section in SECTIONS:
        if section in done_set:
            continue
        if not _gate_met(section, profile):
            return {"current_section": section, "done": False}
    return {"current_section": None, "done": True}


async def compose_question(state: ProfileState) -> dict[str, Any]:
    section = state["current_section"]
    profile = await get_profile(state["user_id"])
    missing = _missing_fields(section, profile)
    msg = build_profile_question_message(section, _snapshot(section, profile), missing)
    try:
        q = await chat_json(PROFILE_QUESTION_SYSTEM_PROMPT, msg)
    except Exception:
        q = {}
    question = q.get("question") or f"Let's cover your {section}. What should I add?"
    field = q.get("field") or (missing[0] if missing else section)
    return {
        "pending_question": {"question": question, "field": field, "section": section},
        "reasoning": f"section={section}; missing={missing}",
    }


def ask_question(state: ProfileState) -> dict[str, Any]:
    q = state.get("pending_question") or {}
    reply = interrupt(q)  # suspends; returns the user's reply on resume
    messages = list(state.get("messages") or [])
    messages.append({"role": "assistant", "content": q.get("question", "")})
    messages.append({"role": "user", "content": reply})
    return {"messages": messages, "last_reply": reply, "pending_question": None}


async def ingest(state: ProfileState) -> dict[str, Any]:
    return {"collected": await extract_career_facts(state.get("last_reply") or "")}


def validate(state: ProfileState) -> dict[str, Any]:
    extraction = state.get("collected") or {}
    cmap = dict(state.get("confidence_map") or {})
    for sec_key in ("skills", "projects", "experiences"):
        for item in extraction.get(sec_key) or []:
            if isinstance(item, dict):
                name = item.get("name") or item.get("title") or sec_key
                cmap[f"{sec_key}:{name}"] = (item.get("confidence") or "MEDIUM")
    return {"confidence_map": cmap}


async def upsert(state: ProfileState) -> dict[str, Any]:
    res = await apply_extraction(state["user_id"], state.get("collected") or {})
    section = state.get("current_section")
    attempts = dict(state.get("section_attempts") or {})
    if section:
        attempts[section] = attempts.get(section, 0) + 1
    profile = await get_profile(state["user_id"])
    done_set = list(state.get("sections_done") or [])
    if section and (_gate_met(section, profile) or attempts.get(section, 0) >= _MAX_ATTEMPTS):
        if section not in done_set:
            done_set.append(section)
    return {
        "added": res["added"],
        "pending": res["pending"],
        "sections_done": done_set,
        "section_attempts": attempts,
    }


def _route_or_end(state: ProfileState) -> str:
    return END if state.get("done") else "compose_question"


# ---------------------------------------------------------------------------
# Graph factory
# ---------------------------------------------------------------------------
def build_profile_graph(checkpointer=None):
    g = StateGraph(ProfileState)
    g.add_node("route_section", route_section)
    g.add_node("compose_question", compose_question)
    g.add_node("ask_question", ask_question)
    g.add_node("ingest", ingest)
    g.add_node("validate", validate)
    g.add_node("upsert", upsert)

    g.add_edge(START, "route_section")
    g.add_conditional_edges("route_section", _route_or_end, ["compose_question", END])
    g.add_edge("compose_question", "ask_question")
    g.add_edge("ask_question", "ingest")
    g.add_edge("ingest", "validate")
    g.add_edge("validate", "upsert")
    g.add_edge("upsert", "route_section")

    if checkpointer is None:
        from app.agent.checkpointer import get_checkpointer
        checkpointer = get_checkpointer()
    return g.compile(checkpointer=checkpointer)


_graph = None


def get_profile_graph():
    global _graph
    if _graph is None:
        _graph = build_profile_graph()
    return _graph


def thread_config(user_id: str) -> dict:
    return {"configurable": {"thread_id": f"profile:{user_id}"}}
