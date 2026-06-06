"""MongoDB client (pymongo native async), collection accessors, index creation.

We use pymongo's native ``AsyncMongoClient`` (the official successor to motor).
motor is intentionally avoided: it caps pymongo at <4.10, which conflicts with
``langgraph-checkpoint-mongodb`` (requires pymongo>=4.12).
"""
from __future__ import annotations

from typing import Any

from pymongo import AsyncMongoClient

from app.config import DB_NAME, settings

# pymongo connects lazily and binds to the running event loop on first use, so
# constructing the client at import time is safe even with an empty MONGO_URI.
_MONGO_URI = settings.MONGO_URI or "mongodb://localhost:27017"
client: AsyncMongoClient = AsyncMongoClient(_MONGO_URI, maxPoolSize=50)


def get_db() -> Any:
    """Return the application's database handle."""
    return client[DB_NAME]


# Collections that hold one item-per-document, keyed by user_id.
ITEM_COLLECTIONS = (
    "experiences",
    "projects",
    "skills",
    "education",
    "certifications",
    "achievements",
)

# Collections whose items carry an inline 384-d embedding for ranking.
EMBEDDABLE_COLLECTIONS = ("experiences", "projects", "skills")


def col(name: str):
    """Return a collection by name."""
    return get_db()[name]


# Convenience accessors -----------------------------------------------------
def profiles():
    return get_db()["profiles"]


def experiences():
    return get_db()["experiences"]


def projects():
    return get_db()["projects"]


def skills():
    return get_db()["skills"]


def education():
    return get_db()["education"]


def certifications():
    return get_db()["certifications"]


def achievements():
    return get_db()["achievements"]


def pending_confirmations():
    return get_db()["pending_confirmations"]


def generated_resumes():
    return get_db()["generated_resumes"]


# Map a profile "section" name to its collection (used by REST CRUD).
SECTION_COLLECTIONS = {
    "experiences": experiences,
    "projects": projects,
    "skills": skills,
    "education": education,
    "certifications": certifications,
    "achievements": achievements,
}


async def ensure_indexes() -> None:
    """Create the indexes the app relies on (idempotent)."""
    db = get_db()
    await db["profiles"].create_index("user_id", unique=True)

    for name in ITEM_COLLECTIONS:
        await db[name].create_index("user_id")
        await db[name].create_index([("user_id", 1), ("item_id", 1)])

    await db["pending_confirmations"].create_index("user_id")
    await db["pending_confirmations"].create_index("confirmation_id", unique=True)

    await db["generated_resumes"].create_index("user_id")
    await db["generated_resumes"].create_index("resume_id", unique=True)
