"""Multi-turn stateful session endpoints.

Replaces the old single-shot /tailor/tex flow.  Each turn either returns an
interrupt (gap question for the user) or the final variants.

Typical flow:
  POST /session/tailor/start  → {status:"question", question:{...}, thread_id}
  POST /session/tailor/answer → {status:"question", ...}  (repeat as needed)
  POST /session/tailor/answer → {status:"variants", variants:[...], resume_id}
  POST /session/tailor/confirm → {tex:"..."}

  POST /session/profile/init  → {added:{...}, pending:[...]}
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from langgraph.types import Command
from pydantic import BaseModel

from app import db
from app.agent.tailor_graph import get_tailor_graph, jd_hash, thread_config
from app.memory.extract import extract_career_facts
from app.memory.ingest import extract_text
from app.memory.profile import apply_extraction, get_profile

router = APIRouter(prefix="/session")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _interrupt_value(chunk: dict) -> Optional[dict]:
    """Return the interrupt payload if the chunk carries one, else None."""
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


async def _run_until_interrupt_or_done(
    graph_input: Any, config: dict
) -> dict:
    """Stream the tailor graph; return on first interrupt or completion."""
    graph = get_tailor_graph()
    thread_id = config["configurable"]["thread_id"]

    async for chunk in graph.astream(graph_input, config, stream_mode="updates"):
        q = _interrupt_value(chunk)
        if q is not None:
            return {"status": "question", "thread_id": thread_id, "question": q}

    # Graph ran to END — fetch final state for variants.
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


# ---------------------------------------------------------------------------
# Profile init
# ---------------------------------------------------------------------------
class ProfileInitIn(BaseModel):
    user_id: str
    text: str


@router.post("/profile/init")
async def profile_init(payload: ProfileInitIn) -> dict:
    """Parse plain text (or previously extracted file text) into a profile."""
    if not payload.text.strip():
        raise HTTPException(status_code=400, detail="text is required")
    try:
        extraction = await extract_career_facts(payload.text)
        result = await apply_extraction(payload.user_id, extraction)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {
        "added": result.get("added", {}),
        "pending": result.get("pending", []),
        "profile": await get_profile(payload.user_id),
    }


# ---------------------------------------------------------------------------
# Tailor session — start
# ---------------------------------------------------------------------------
class TailorStartIn(BaseModel):
    user_id: str
    job_description: str
    resume_text: Optional[str] = None


@router.post("/tailor/start")
async def tailor_start(payload: TailorStartIn) -> dict:
    """Start (or resume from checkpoint) a tailoring session.

    If `resume_text` is provided, profile extraction runs first.
    Returns either a gap question or the final variants.
    """
    jd = payload.job_description.strip()
    if not jd:
        raise HTTPException(status_code=400, detail="job_description is required")

    # Optional: ingest resume text before starting the graph
    if payload.resume_text and payload.resume_text.strip():
        try:
            extraction = await extract_career_facts(payload.resume_text)
            await apply_extraction(payload.user_id, extraction)
        except Exception:
            pass  # profile ingestion failure must not block tailoring

    jdh = jd_hash(jd)
    config = thread_config(payload.user_id, jdh)
    graph_input: Any = {
        "user_id": payload.user_id,
        "jd_text": jd,
        "messages": [],
        "questions_asked": 0,
    }

    try:
        return await _run_until_interrupt_or_done(graph_input, config)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


# ---------------------------------------------------------------------------
# Tailor session — answer
# ---------------------------------------------------------------------------
class TailorAnswerIn(BaseModel):
    user_id: str
    thread_id: str
    message: str


@router.post("/tailor/answer")
async def tailor_answer(payload: TailorAnswerIn) -> dict:
    """Resume the graph with the user's answer to a gap question."""
    if not payload.message.strip():
        raise HTTPException(status_code=400, detail="message is required")

    config = {"configurable": {"thread_id": payload.thread_id}}
    try:
        return await _run_until_interrupt_or_done(Command(resume=payload.message), config)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


# ---------------------------------------------------------------------------
# Tailor session — confirm (return chosen .tex)
# ---------------------------------------------------------------------------
class TailorConfirmIn(BaseModel):
    user_id: str
    resume_id: str
    variant_label: str


@router.post("/tailor/confirm")
async def tailor_confirm(payload: TailorConfirmIn) -> dict:
    """Return the LaTeX source for the chosen variant."""
    doc = await db.generated_resumes().find_one({"resume_id": payload.resume_id})
    if not doc:
        raise HTTPException(status_code=404, detail="resume_id not found")
    if doc.get("user_id") != payload.user_id:
        raise HTTPException(status_code=403, detail="forbidden")

    variants = doc.get("variants") or []
    match = next((v for v in variants if v.get("label") == payload.variant_label), None)
    if not match:
        # Fallback: first variant
        match = variants[0] if variants else None
    if not match:
        raise HTTPException(status_code=404, detail="variant not found")

    tex = match.get("tex", "")
    if not tex:
        raise HTTPException(status_code=500, detail="stored variant has no tex — was it generated with an older version?")

    return {
        "tex": tex,
        "label": match.get("label"),
        "ats": match.get("ats", {}),
    }
