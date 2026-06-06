"""WebSocket endpoints that drive the two LangGraph agents and stream progress.

Protocol (JSON both ways):
  client -> {"type": "start", ...}        # profile: optional resume_text; tailor: job_description
            {"type": "reply", "message": "..."}   # answer to a streamed question
  server -> {"type": "status", "message": "..."}
            {"type": "question", "question": "...", ...}
            {"type": "section_update", "profile": {...}}   # profile builder
            {"type": "confirm", "pending": [...]}          # profile builder
            {"type": "variants", "variants": [...], "resume_id": "..."}  # tailor
            {"type": "done", ...}
            {"type": "error", "detail": "..."}
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from langgraph.types import Command

from app.agent.profile_graph import get_profile_graph
from app.agent.profile_graph import thread_config as profile_cfg
from app.agent.tailor_graph import get_tailor_graph, jd_hash
from app.agent.tailor_graph import thread_config as tailor_cfg
from app.memory.extract import extract_career_facts
from app.memory.profile import apply_extraction, get_profile

router = APIRouter()

_PROFILE_STATUS = {
    "route_section": "Reviewing your profile…",
    "compose_question": "Thinking of the next question…",
    "ingest": "Capturing what you said…",
    "validate": "Validating…",
    "upsert": "Saving to your profile…",
}
_TAILOR_STATUS = {
    "parse_jd": "Parsing the job description…",
    "load_rank": "Ranking your experience…",
    "gap_check": "Checking for gaps…",
    "compose_jd_question": "Preparing a quick question…",
    "ask_jd_question": "Adding your answer…",
    "generate_variants": "Generating 3 variants…",
    "score_variants": "Scoring against the JD…",
    "render": "Rendering PDFs…",
}


def _interrupt_payload(chunk: dict) -> dict:
    intr = chunk["__interrupt__"][0]
    value = getattr(intr, "value", intr)
    if isinstance(value, dict):
        return {"type": "question", **value}
    return {"type": "question", "question": str(value)}


async def _emit_profile_node(ws: WebSocket, user_id: str, node: str, update: dict) -> None:
    if node in _PROFILE_STATUS:
        await ws.send_json({"type": "status", "message": _PROFILE_STATUS[node]})
    if node == "upsert":
        await ws.send_json({"type": "section_update", "profile": await get_profile(user_id)})
        if update and update.get("pending"):
            await ws.send_json({"type": "confirm", "pending": update["pending"]})


async def _emit_tailor_node(ws: WebSocket, node: str, update: dict) -> None:
    if node in _TAILOR_STATUS:
        await ws.send_json({"type": "status", "message": _TAILOR_STATUS[node]})
    if node == "render" and update and update.get("variants") is not None:
        await ws.send_json(
            {
                "type": "variants",
                "resume_id": update.get("resume_id"),
                "variants": [
                    {
                        "label": v.get("label"),
                        "ats": v.get("ats", {}),
                        "analysis": v.get("analysis", {}),
                        "resume": v.get("resume", {}),
                        "pdf_url": v.get("pdf_url"),
                        "render_error": v.get("render_error"),
                    }
                    for v in update["variants"]
                ],
            }
        )


async def _drive(
    ws: WebSocket, graph, graph_input: Any, config: dict, kind: str, user_id: str
) -> str:
    """Stream one run of the graph; return 'interrupted' or 'done'."""
    async for chunk in graph.astream(graph_input, config, stream_mode="updates"):
        if "__interrupt__" in chunk:
            await ws.send_json(_interrupt_payload(chunk))
            return "interrupted"
        for node, update in chunk.items():
            if kind == "profile":
                await _emit_profile_node(ws, user_id, node, update or {})
            else:
                await _emit_tailor_node(ws, node, update or {})
    return "done"


@router.websocket("/ws/profile/{user_id}")
async def ws_profile(ws: WebSocket, user_id: str) -> None:
    await ws.accept()
    try:
        graph = get_profile_graph()
        config = profile_cfg(user_id)

        first = await ws.receive_json()
        if first.get("resume_text"):
            await ws.send_json({"type": "status", "message": "Reading your pasted resume…"})
            extraction = await extract_career_facts(first["resume_text"])
            res = await apply_extraction(user_id, extraction)
            await ws.send_json({"type": "section_update", "profile": await get_profile(user_id)})
            if res.get("pending"):
                await ws.send_json({"type": "confirm", "pending": res["pending"]})

        graph_input: Any = {
            "user_id": user_id, "messages": [], "sections_done": [], "section_attempts": {}
        }
        status = await _drive(ws, graph, graph_input, config, "profile", user_id)
        while status == "interrupted":
            reply = (await ws.receive_json()).get("message", "")
            status = await _drive(ws, graph, Command(resume=reply), config, "profile", user_id)

        await ws.send_json({"type": "done", "profile": await get_profile(user_id)})
    except WebSocketDisconnect:
        return
    except Exception as exc:  # surface errors to the client instead of dropping
        try:
            await ws.send_json({"type": "error", "detail": str(exc)})
        except Exception:
            pass


@router.websocket("/ws/tailor/{user_id}")
async def ws_tailor(ws: WebSocket, user_id: str) -> None:
    await ws.accept()
    try:
        graph = get_tailor_graph()
        first = await ws.receive_json()
        jd = (first.get("job_description") or "").strip()
        if not jd:
            await ws.send_json({"type": "error", "detail": "job_description is required."})
            return

        config = tailor_cfg(user_id, jd_hash(jd))
        graph_input: Any = {
            "user_id": user_id, "jd_text": jd, "messages": [], "questions_asked": 0
        }
        status = await _drive(ws, graph, graph_input, config, "tailor", user_id)
        while status == "interrupted":
            reply = (await ws.receive_json()).get("message", "")
            status = await _drive(ws, graph, Command(resume=reply), config, "tailor", user_id)

        await ws.send_json({"type": "done"})
    except WebSocketDisconnect:
        return
    except Exception as exc:
        try:
            await ws.send_json({"type": "error", "detail": str(exc)})
        except Exception:
            pass
