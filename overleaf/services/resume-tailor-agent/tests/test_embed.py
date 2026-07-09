"""Unit tests for the embedding module (loads real MiniLM — offline, no Neo4j)."""
import pytest
from app.memory.embed import embed, cosine, skill_text, project_text, bullet_text


@pytest.mark.asyncio
async def test_embed_returns_384_dims():
    vec = await embed("Software Engineer at Acme")
    assert isinstance(vec, list)
    assert len(vec) == 384


@pytest.mark.asyncio
async def test_embed_empty_string():
    vec = await embed("")
    assert len(vec) == 384


@pytest.mark.asyncio
async def test_cosine_identical_vectors():
    vec = await embed("Python developer")
    sim = cosine(vec, vec)
    assert abs(sim - 1.0) < 1e-5


@pytest.mark.asyncio
async def test_cosine_different_vectors():
    v1 = await embed("machine learning engineer")
    v2 = await embed("graphic designer pottery studio")
    sim = cosine(v1, v2)
    assert sim < 0.95


def test_skill_text():
    sk = {"name": "Python", "category": "language"}
    assert "Python" in skill_text(sk)
    assert "language" in skill_text(sk)


def test_project_text():
    pr = {"name": "APIGateway", "description": "REST gateway",
          "tech_stack": ["FastAPI", "Redis"], "outcomes": [{"text": "40% latency drop"}]}
    text = project_text(pr)
    assert "FastAPI" in text
    assert "latency" in text


def test_bullet_text():
    b = {"text": "Led team of 5 engineers"}
    assert "Led" in bullet_text(b)
