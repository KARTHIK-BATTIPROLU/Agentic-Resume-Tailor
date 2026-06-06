"""FastAPI application entrypoint (REST + WebSocket, two agents)."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.rest import router as rest_router
from app.api.ws import router as ws_router
from app.config import OUTPUT_DIR
from app.db import ensure_indexes

_WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web")


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    try:
        await ensure_indexes()
    except Exception as exc:  # never block startup if Mongo is briefly unreachable
        print(f"[startup] index creation skipped: {exc}")
    yield


app = FastAPI(title="Agentic Resume Tailor", version="2.0.0", lifespan=lifespan)

# Static assets (app.js, styles.css). The HTML itself is served by GET / in rest.py.
if os.path.isdir(_WEB_DIR):
    app.mount("/static", StaticFiles(directory=_WEB_DIR), name="static")

app.include_router(rest_router)
app.include_router(ws_router)
