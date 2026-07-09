"""Offline auth middleware tests — no Neo4j, no LLM needed.

Each test uses a fresh reloaded app instance so the singleton Settings
picks up the env vars set for that specific scenario.
"""
import importlib
import os

import pytest
from fastapi.testclient import TestClient


def _make_client(local_dev: bool, token: str) -> TestClient:
    """Build a TestClient with fresh Settings reflecting the given env state."""
    os.environ["LLM_MOCK"] = "true"
    os.environ["LOCAL_DEV"] = "true" if local_dev else "false"
    os.environ["RESUME_TAILOR_SERVICE_TOKEN"] = token
    os.environ["NEO4J_URI"] = "bolt://localhost:7687"

    import app.config as cfg_mod
    importlib.reload(cfg_mod)
    import app.main as main_mod
    importlib.reload(main_mod)
    return TestClient(main_mod.app, raise_server_exceptions=False)


def test_health_passes_without_token():
    c = _make_client(local_dev=False, token="secret")
    r = c.get("/health")
    # Health is in _NO_AUTH_PATHS — must NOT return 401
    assert r.status_code != 401


def test_missing_token_returns_401():
    c = _make_client(local_dev=False, token="secret")
    r = c.get("/profile/user123")
    assert r.status_code == 401


def test_wrong_token_returns_401():
    c = _make_client(local_dev=False, token="secret")
    r = c.get("/profile/user123", headers={"X-Service-Token": "wrong"})
    assert r.status_code == 401


def test_correct_token_passes_auth():
    c = _make_client(local_dev=False, token="secret")
    r = c.get("/profile/user123", headers={"X-Service-Token": "secret"})
    # Auth passes; downstream may fail without Neo4j, but NOT 401
    assert r.status_code != 401


def test_local_dev_bypass():
    c = _make_client(local_dev=True, token="some-token")
    r = c.get("/profile/user123")  # no token header
    assert r.status_code != 401
