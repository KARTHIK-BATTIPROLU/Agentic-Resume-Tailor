"""Unit tests for the deterministic ATS scorer."""
import pytest
from app.ats import score


def _resume(skills=None, bullets=None, name="Jane Doe", email="jane@example.com"):
    return {
        "name": name,
        "contact": {"email": email},
        "core_competencies": skills or [],
        "experience": [{"company": "Acme", "title": "SWE", "bullets": bullets or []}],
        "projects": [],
    }


def test_full_match():
    req = {"required_skills": ["Python", "FastAPI"], "preferred_skills": [], "keywords": []}
    r = _resume(skills=["Python", "FastAPI"])
    result = score(r, req)
    assert result["score"] > 60
    assert set(result["matched"]) == {"Python", "FastAPI"}
    assert result["missing"] == []


def test_no_match():
    req = {"required_skills": ["Kubernetes", "Go"], "preferred_skills": [], "keywords": []}
    r = _resume(skills=["Python"])
    result = score(r, req)
    assert result["match_pct"] == 0.0
    assert set(result["missing"]) == {"Kubernetes", "Go"}


def test_synonym_k8s():
    req = {"required_skills": ["kubernetes"], "preferred_skills": [], "keywords": []}
    r = _resume(skills=["k8s"])
    result = score(r, req)
    assert "kubernetes" in result["matched"]


def test_quantified_bullets():
    req = {"required_skills": [], "preferred_skills": [], "keywords": []}
    bullets = ["Led team of 5", "Improved latency by 30%", "Delivered feature on time"]
    r = _resume(bullets=bullets)
    result = score(r, req)
    assert result["checks"]["quantified_bullets"] > 0


def test_empty_inputs():
    result = score({}, {})
    assert result["score"] >= 0
    assert result["match_pct"] == 0.0
