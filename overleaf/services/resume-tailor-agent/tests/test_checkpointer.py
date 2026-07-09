"""Unit tests for Neo4jCheckpointer with a mocked Neo4j sync driver."""
import json
import uuid
from unittest.mock import MagicMock, patch

import pytest
from app.graph.checkpointer import Neo4jCheckpointer


def _make_mock_session(records=None):
    """Return a context-manager mock that yields a session returning given records."""
    record = None
    if records:
        record = MagicMock()
        record.__getitem__ = lambda self, key: records[key]

    result = MagicMock()
    result.single.return_value = record

    session = MagicMock()
    session.run.return_value = result
    session.__enter__ = MagicMock(return_value=session)
    session.__exit__ = MagicMock(return_value=False)
    return session


def _make_driver(session):
    drv = MagicMock()
    drv.session.return_value = session
    return drv


def test_get_tuple_returns_none_when_no_records():
    session = _make_mock_session(records=None)
    drv = _make_driver(session)
    with patch("app.graph.checkpointer.sync_driver", return_value=drv):
        cp = Neo4jCheckpointer()
        result = cp.get_tuple({"configurable": {"thread_id": "profile:user1"}})
    assert result is None


def test_put_returns_config_with_checkpoint_id():
    session = _make_mock_session()
    drv = _make_driver(session)
    with patch("app.graph.checkpointer.sync_driver", return_value=drv):
        cp = Neo4jCheckpointer()
        cfg = cp.put(
            {"configurable": {"thread_id": "profile:user1"}},
            checkpoint={"v": 1, "id": "abc", "channel_values": {}, "channel_versions": {}, "versions_seen": {}, "pending_sends": []},
            metadata={"step": 0},
            new_versions={},
        )
    assert cfg["configurable"]["thread_id"] == "profile:user1"
    assert "checkpoint_id" in cfg["configurable"]


def test_put_writes_calls_session_run():
    session = _make_mock_session()
    drv = _make_driver(session)
    with patch("app.graph.checkpointer.sync_driver", return_value=drv):
        cp = Neo4jCheckpointer()
        cp.put(
            {"configurable": {"thread_id": "t1"}},
            checkpoint={"v": 1, "id": "x", "channel_values": {}, "channel_versions": {}, "versions_seen": {}, "pending_sends": []},
            metadata={},
            new_versions={},
        )
    # session.run must have been called at least once (the MERGE statement)
    assert session.run.call_count >= 1


def test_get_tuple_with_checkpoint_node():
    cid = str(uuid.uuid4())
    node_data = {
        "threadId": "profile:u1",
        "checkpointId": cid,
        "parentId": "",
        "data": json.dumps({"v": 1, "id": cid, "channel_values": {}, "channel_versions": {}, "versions_seen": {}, "pending_sends": []}),
        "metadata": json.dumps({"step": 0}),
        "pendingWrites": "[]",
    }
    session = _make_mock_session(records={"c": node_data})
    drv = _make_driver(session)
    with patch("app.graph.checkpointer.sync_driver", return_value=drv):
        cp = Neo4jCheckpointer()
        tup = cp.get_tuple({"configurable": {"thread_id": "profile:u1"}})
    assert tup is not None
    assert tup.config["configurable"]["thread_id"] == "profile:u1"
    assert tup.config["configurable"]["checkpoint_id"] == cid
