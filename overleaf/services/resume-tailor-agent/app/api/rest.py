"""REST endpoints (Neo4j edition).

  GET  /health
  GET  /profile/{user_id}
  POST /profile/{user_id}/ingest        — plain text → profile upsert
  POST /upload/{user_id}                — PDF/DOCX/TXT file → profile upsert
  POST /score                           — live ATS re-score (no LLM)
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, UploadFile, File
from pydantic import BaseModel

from app.ats import score as ats_score
from app.db.neo4j import async_driver, health_check
from app.graph.profile import _get_profile_snapshot, _upsert_facts
from app.llm import chat_json
from app.memory.extract import extract_career_facts
from app.memory.ingest import extract_text
from app.prompts import JD_PARSE_SYSTEM_PROMPT, build_jd_parse_message

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    try:
        neo = await health_check()
        return {"status": "ok", "neo4j": neo}
    except Exception as exc:
        return {"status": "degraded", "error": str(exc)}


@router.get("/profile/{user_id}")
async def get_profile(user_id: str) -> dict:
    return await _get_profile_snapshot(user_id)


class IngestIn(BaseModel):
    text: str


@router.post("/profile/{user_id}/ingest")
async def ingest_text(user_id: str, payload: IngestIn) -> dict:
    if not payload.text.strip():
        raise HTTPException(status_code=400, detail="text is required")
    try:
        facts = await extract_career_facts(payload.text)
        added = await _upsert_facts(user_id, facts)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {"added": added, "profile": await _get_profile_snapshot(user_id)}


@router.post("/upload/{user_id}")
async def upload_resume(user_id: str, file: UploadFile = File(...)) -> dict:
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    try:
        text = extract_text(content, file.filename or "")
    except ValueError as exc:
        raise HTTPException(status_code=415, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    try:
        facts = await extract_career_facts(text)
        added = await _upsert_facts(user_id, facts)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {
        "filename": file.filename,
        "characters_extracted": len(text),
        "added": added,
    }


class ScoreIn(BaseModel):
    resume_json: dict
    job_description: str = ""
    jd_requirements: dict | None = None


@router.post("/score")
async def score_resume(payload: ScoreIn) -> dict:
    req = payload.jd_requirements
    if req is None and payload.job_description.strip():
        try:
            req = await chat_json(
                JD_PARSE_SYSTEM_PROMPT,
                build_jd_parse_message(payload.job_description),
            )
        except Exception:
            req = {}
    return {
        "ats": ats_score(payload.resume_json, req or {}, payload.job_description),
        "jd_requirements": req or {},
    }
