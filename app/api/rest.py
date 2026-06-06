"""REST endpoints: profile CRUD, confirm, live ATS scoring, PDF, health, UI."""
from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse

from app import db
from app.agent import ats
from app.agent.llm import chat_json
from app.agent.prompts import JD_PARSE_SYSTEM_PROMPT, build_jd_parse_message
from app.memory.extract import extract_career_facts
from app.memory.profile import apply_extraction, confirm, delete_item, edit_item, get_profile
from app.models import ChatIn, ChatOut, ConfirmIn, ConfirmOut, ScoreIn

router = APIRouter()

_WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "web")

_EDITABLE_SECTIONS = set(db.SECTION_COLLECTIONS.keys())


@router.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    path = os.path.join(_WEB_DIR, "index.html")
    if not os.path.exists(path):
        return HTMLResponse("<h1>Agentic Resume Tailor</h1><p>UI not found.</p>")
    with open(path, "r", encoding="utf-8") as fh:
        return HTMLResponse(fh.read())


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@router.post("/chat", response_model=ChatOut)
async def chat(payload: ChatIn) -> ChatOut:
    """Bootstrap the profile from a pasted resume or a free-text message."""
    text = payload.resume_text or payload.message
    if not text or not text.strip():
        raise HTTPException(status_code=400, detail="Provide 'message' or 'resume_text'.")
    try:
        extraction = await extract_career_facts(text)
        result = await apply_extraction(payload.user_id, extraction)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return ChatOut(**result)


@router.get("/profile/{user_id}")
async def profile(user_id: str) -> dict:
    return await get_profile(user_id)


@router.patch("/profile/{user_id}/{section}/{item_id}")
async def patch_item(
    user_id: str, section: str, item_id: str, payload: dict[str, Any] = Body(...)
) -> dict:
    if section not in _EDITABLE_SECTIONS:
        raise HTTPException(status_code=400, detail=f"Unknown section '{section}'.")
    updated = await edit_item(user_id, section, item_id, payload)
    if updated is None:
        raise HTTPException(status_code=404, detail="Item not found.")
    return {"updated": updated}


@router.delete("/profile/{user_id}/{section}/{item_id}")
async def delete_profile_item(user_id: str, section: str, item_id: str) -> dict:
    if section not in _EDITABLE_SECTIONS:
        raise HTTPException(status_code=400, detail=f"Unknown section '{section}'.")
    ok = await delete_item(user_id, section, item_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Item not found.")
    return {"deleted": True}


@router.post("/confirm", response_model=ConfirmOut)
async def confirm_pending(payload: ConfirmIn) -> ConfirmOut:
    try:
        result = await confirm(payload.user_id, payload.confirmation_id, payload.approved)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    if result.get("status") == "not_found":
        raise HTTPException(status_code=404, detail="confirmation_id not found for this user.")
    return ConfirmOut(**result)


@router.post("/score")
async def score_resume(payload: ScoreIn) -> dict:
    """Deterministically score a (possibly edited) resume against a JD. Powers live re-score."""
    req = payload.jd_requirements
    if req is None:
        try:
            req = await chat_json(JD_PARSE_SYSTEM_PROMPT, build_jd_parse_message(payload.job_description))
        except Exception:
            req = {}
    return {"ats": ats.score(payload.resume_json, req, payload.job_description),
            "jd_requirements": req}


@router.get("/resume/{resume_id}/pdf")
async def resume_pdf(resume_id: str, variant: str = Query("balanced")) -> FileResponse:
    doc = await db.generated_resumes().find_one({"resume_id": resume_id})
    if not doc:
        raise HTTPException(status_code=404, detail="resume_id not found.")

    pdf_path = None
    variants = doc.get("variants") or []
    if variants:
        match = next((v for v in variants if v.get("label") == variant), None)
        match = match or variants[0]
        pdf_path = match.get("pdf_path")
    else:  # backward-compatible with single-resume docs
        pdf_path = doc.get("pdf_path")

    if not pdf_path or not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail="PDF file is missing.")
    return FileResponse(pdf_path, media_type="application/pdf", filename=f"resume_{variant}.pdf")
