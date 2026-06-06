"""LangGraph MongoDB checkpointer factory.

langgraph-checkpoint-mongodb 0.4.0 exposes a single ``MongoDBSaver`` that takes a
**synchronous** ``pymongo.MongoClient`` but implements the async checkpoint
methods (``aget_tuple``/``aput``/``aput_writes``) by offloading to a threadpool,
so it is safe to use from the async graph runtime. Checkpoints live in their own
collections in the application database.
"""
from __future__ import annotations

from typing import Optional

from langgraph.checkpoint.mongodb import MongoDBSaver
from pymongo import MongoClient

from app.config import (
    CHECKPOINT_COLLECTION,
    CHECKPOINT_WRITES_COLLECTION,
    DB_NAME,
    settings,
)

_saver: Optional[MongoDBSaver] = None


def get_checkpointer() -> MongoDBSaver:
    """Return a process-wide MongoDBSaver (lazily constructed)."""
    global _saver
    if _saver is None:
        uri = settings.MONGO_URI or "mongodb://localhost:27017"
        client = MongoClient(uri)
        _saver = MongoDBSaver(
            client,
            db_name=DB_NAME,
            checkpoint_collection_name=CHECKPOINT_COLLECTION,
            writes_collection_name=CHECKPOINT_WRITES_COLLECTION,
        )
    return _saver
