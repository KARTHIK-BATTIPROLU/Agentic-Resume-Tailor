"""Application settings and constants.

Secrets (``GROQ_API_KEY``, ``MONGO_URI``) are read from the environment / a local
``.env`` file via pydantic-settings. Nothing is ever hardcoded.
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Secrets — default to empty so the app can still import/boot without them.
    # Calls that actually need them fail loudly at request time with a clear error.
    GROQ_API_KEY: str = ""
    MONGO_URI: str = ""


settings = Settings()

# ---------------------------------------------------------------------------
# Constants (not secrets)
# ---------------------------------------------------------------------------
DB_NAME = "resume_tailor"
GROQ_MODEL = "llama-3.3-70b-versatile"
EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBED_DIM = 384

# Ranking limits used when assembling the tailored resume.
TOP_BULLETS = 8
TOP_PROJECTS = 6
TOP_SKILLS = 15

# Where rendered PDFs are written.
OUTPUT_DIR = "output"

# LangGraph checkpointing (MongoDBSaver) — own collections in the same DB.
CHECKPOINT_COLLECTION = "lg_checkpoints"
CHECKPOINT_WRITES_COLLECTION = "lg_checkpoint_writes"

# Resume Tailor: cap on job-specific follow-up questions.
MAX_JD_QUESTIONS = 3

# The three resume variants generated per job (selection/emphasis only — never fabrication).
VARIANT_LABELS = ("conservative", "balanced", "aggressive")
