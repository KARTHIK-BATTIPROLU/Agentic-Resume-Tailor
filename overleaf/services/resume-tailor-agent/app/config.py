"""Application settings — all secrets come from the environment / .env file."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Neo4j (ONLY datastore) ────────────────────────────────────────────────
    # Local compose service: bolt://neo4j:7687
    # Phase 11 Aura: neo4j+s://xxxx.databases.neo4j.io
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "neo4j"

    # ── LLM (Groq) ───────────────────────────────────────────────────────────
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "llama-3.3-70b-versatile"
    # Set to true to return canned responses without calling the API.
    LLM_MOCK: bool = False

    # ── Service auth ─────────────────────────────────────────────────────────
    RESUME_TAILOR_SERVICE_TOKEN: str = ""
    # Bypass token check in local dev (never set in production).
    LOCAL_DEV: bool = False


settings = Settings()

# ── Non-secret constants ──────────────────────────────────────────────────────
EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBED_DIM = 384

TOP_BULLETS = 8
TOP_PROJECTS = 6
TOP_SKILLS = 15

MAX_JD_QUESTIONS = 3
VARIANT_LABELS = ("conservative", "balanced", "aggressive")

# ── Neo4j vector index names ──────────────────────────────────────────────────
SKILL_VEC_INDEX = "skill_embedding"
PROJECT_VEC_INDEX = "project_embedding"
EXPERIENCE_VEC_INDEX = "experience_embedding"
ACHIEVEMENT_VEC_INDEX = "achievement_embedding"
