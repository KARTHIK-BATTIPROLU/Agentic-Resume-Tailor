"""Neo4j-backed LangGraph checkpoint saver (spec §7).

Stores checkpoint state as `:Checkpoint` nodes in Neo4j, keyed by
``threadId``.  Each checkpoint carries:
  - ``checkpointId``  (unique UUID)
  - ``threadId``
  - ``data``          (JSON-serialised Checkpoint dict)
  - ``metadata``      (JSON-serialised CheckpointMetadata dict)
  - ``parentId``      (parent checkpointId, nullable)
  - ``pendingWrites`` (JSON-serialised list of pending write tuples)
  - ``createdAt``     (datetime — latest-by-ts query uses this)

``get_tuple`` returns the most recent checkpoint for a threadId.
``put`` upserts a new checkpoint.
``put_writes`` appends pending write tuples to the checkpoint node.

Async methods delegate to ``asyncio.to_thread`` wrapping the sync driver —
same pattern as the reference MongoDBSaver.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Iterator, Optional, Sequence

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    ChannelVersions,
)

from app.db.neo4j import sync_driver


def _cfg_thread(config: RunnableConfig) -> Optional[str]:
    return (config.get("configurable") or {}).get("thread_id")


def _cfg_ts(config: RunnableConfig) -> Optional[str]:
    return (config.get("configurable") or {}).get("checkpoint_ns", "")


class Neo4jCheckpointer(BaseCheckpointSaver):
    """LangGraph checkpoint saver backed by Neo4j `:Checkpoint` nodes."""

    # ── Sync core ─────────────────────────────────────────────────────────────
    def get_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        thread_id = _cfg_thread(config)
        if not thread_id:
            return None
        drv = sync_driver()
        with drv.session() as s:
            result = s.run(
                """
                MATCH (c:Checkpoint {threadId: $threadId})
                RETURN c ORDER BY c.createdAt DESC LIMIT 1
                """,
                threadId=thread_id,
            )
            record = result.single()
        if not record:
            return None
        node = dict(record["c"])
        return self._node_to_tuple(node, config)

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        thread_id = _cfg_thread(config)
        checkpoint_id = str(uuid.uuid4())
        parent_id = (config.get("configurable") or {}).get("checkpoint_id")
        drv = sync_driver()
        with drv.session() as s:
            s.run(
                """
                MERGE (c:Checkpoint {checkpointId: $cid})
                SET c.threadId      = $threadId,
                    c.data          = $data,
                    c.metadata      = $meta,
                    c.parentId      = $parentId,
                    c.pendingWrites = '[]',
                    c.createdAt     = datetime()
                """,
                cid=checkpoint_id,
                threadId=thread_id,
                data=json.dumps(checkpoint),
                meta=json.dumps(metadata),
                parentId=parent_id or "",
            )
        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": "",
                "checkpoint_id": checkpoint_id,
            }
        }

    def put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        checkpoint_id = (config.get("configurable") or {}).get("checkpoint_id")
        if not checkpoint_id:
            return
        drv = sync_driver()
        with drv.session() as s:
            # Append to existing pendingWrites JSON list
            result = s.run(
                "MATCH (c:Checkpoint {checkpointId: $cid}) RETURN c.pendingWrites AS pw",
                cid=checkpoint_id,
            )
            rec = result.single()
            existing: list = json.loads(rec["pw"] if rec and rec["pw"] else "[]")
            for channel, value in writes:
                existing.append({"taskId": task_id, "channel": channel,
                                  "data": json.dumps(value)})
            s.run(
                "MATCH (c:Checkpoint {checkpointId: $cid}) SET c.pendingWrites = $pw",
                cid=checkpoint_id,
                pw=json.dumps(existing),
            )

    def list(  # type: ignore[override]
        self,
        config: Optional[RunnableConfig],
        *,
        filter: Optional[dict] = None,
        before: Optional[RunnableConfig] = None,
        limit: Optional[int] = None,
    ) -> Iterator[CheckpointTuple]:
        thread_id = _cfg_thread(config) if config else None
        if not thread_id:
            return
        drv = sync_driver()
        with drv.session() as s:
            result = s.run(
                """
                MATCH (c:Checkpoint {threadId: $threadId})
                RETURN c ORDER BY c.createdAt DESC
                LIMIT $limit
                """,
                threadId=thread_id,
                limit=limit or 100,
            )
            records = list(result)
        for rec in records:
            yield self._node_to_tuple(dict(rec["c"]), config)

    # ── Helpers ──────────────────────────────────────────────────────────────
    def _node_to_tuple(
        self, node: dict, config: RunnableConfig
    ) -> CheckpointTuple:
        thread_id = node.get("threadId", "")
        checkpoint_id = node.get("checkpointId", "")
        parent_id = node.get("parentId") or None

        checkpoint: Checkpoint = json.loads(node.get("data") or "{}")
        metadata: CheckpointMetadata = json.loads(node.get("metadata") or "{}")
        raw_writes = json.loads(node.get("pendingWrites") or "[]")
        pending_writes = [
            (w["taskId"], w["channel"], json.loads(w["data"]))
            for w in raw_writes
        ]

        cfg: RunnableConfig = {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": "",
                "checkpoint_id": checkpoint_id,
            }
        }
        parent_cfg: Optional[RunnableConfig] = (
            {
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": "",
                    "checkpoint_id": parent_id,
                }
            }
            if parent_id
            else None
        )
        return CheckpointTuple(
            config=cfg,
            checkpoint=checkpoint,
            metadata=metadata,
            parent_config=parent_cfg,
            pending_writes=pending_writes,
        )

    # ── Async wrappers (delegate to thread) ───────────────────────────────────
    async def aget_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        return await asyncio.to_thread(self.get_tuple, config)

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        return await asyncio.to_thread(self.put, config, checkpoint, metadata, new_versions)

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        return await asyncio.to_thread(self.put_writes, config, writes, task_id, task_path)

    async def alist(
        self,
        config: Optional[RunnableConfig],
        *,
        filter: Optional[dict] = None,
        before: Optional[RunnableConfig] = None,
        limit: Optional[int] = None,
    ):
        items = await asyncio.to_thread(
            lambda: list(self.list(config, filter=filter, before=before, limit=limit))
        )
        for item in items:
            yield item


# Process-wide singleton
_checkpointer: Optional[Neo4jCheckpointer] = None


def get_checkpointer() -> Neo4jCheckpointer:
    global _checkpointer
    if _checkpointer is None:
        _checkpointer = Neo4jCheckpointer()
    return _checkpointer
