"""FastAPI application entrypoint.

Auth is FAIL-CLOSED:
  - If RESUME_TAILOR_SERVICE_TOKEN is set AND LOCAL_DEV is not true,
    every non-exempt request must carry the matching X-Service-Token header.
  - 401 on miss or mismatch; no other information disclosed.
  - LOCAL_DEV=true bypasses the check (dev/test only).
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.rest import router as rest_router
from app.api.session import router as session_router
from app.config import settings
from app.db.neo4j import ensure_schema

_NO_AUTH_PATHS = {"/health", "/"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await ensure_schema()
    except Exception as exc:
        print(f"[startup] Neo4j schema init skipped: {exc}")
    yield


app = FastAPI(title="Agentic Resume Tailor", version="3.0.0", lifespan=lifespan)


@app.middleware("http")
async def verify_service_token(request: Request, call_next):
    if not settings.LOCAL_DEV and settings.RESUME_TAILOR_SERVICE_TOKEN:
        if request.url.path not in _NO_AUTH_PATHS:
            incoming = request.headers.get("X-Service-Token", "")
            if incoming != settings.RESUME_TAILOR_SERVICE_TOKEN:
                return JSONResponse(status_code=401, content={"detail": "unauthorized"})
    return await call_next(request)


app.include_router(rest_router)
app.include_router(session_router)
