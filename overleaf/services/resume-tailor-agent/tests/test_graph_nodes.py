"""Unit tests for LangGraph node functions with mocked Neo4j and mock LLM."""
import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ["LLM_MOCK"] = "true"
os.environ["LOCAL_DEV"] = "true"


def _mock_async_driver(profile_row=None):
    """Return a mock async_driver whose session yields optional profile data."""
    result = AsyncMock()
    result.single = AsyncMock(return_value=profile_row)
    result.data = AsyncMock(return_value=[])

    session = AsyncMock()
    session.run = AsyncMock(return_value=result)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)

    drv = MagicMock()
    drv.session = MagicMock(return_value=session)
    return drv


# ── Profile graph nodes ────────────────────────────────────────────────────────
class TestProfileNodes:

    @pytest.mark.asyncio
    async def test_route_section_returns_first_unmet_section(self):
        from app.graph.profile import route_section

        drv = _mock_async_driver(profile_row=None)  # no profile yet
        with patch("app.graph.profile.async_driver", return_value=drv):
            result = await route_section({"user_id": "u1", "sections_done": []})
        assert result["current_section"] == "personal"
        assert result["done"] is False

    @pytest.mark.asyncio
    async def test_route_section_done_when_all_sections_done(self):
        from app.graph.profile import route_section, SECTIONS

        drv = _mock_async_driver(profile_row=None)
        with patch("app.graph.profile.async_driver", return_value=drv):
            result = await route_section({
                "user_id": "u1",
                "sections_done": list(SECTIONS),
            })
        assert result["done"] is True
        assert result["current_section"] is None

    @pytest.mark.asyncio
    async def test_compose_question_returns_pending_question(self):
        from app.graph.profile import compose_question

        drv = _mock_async_driver(profile_row=None)
        with patch("app.graph.profile.async_driver", return_value=drv):
            result = await compose_question({"user_id": "u1", "current_section": "personal"})
        assert "pending_question" in result
        pq = result["pending_question"]
        assert "question" in pq
        assert pq["section"] == "personal"

    @pytest.mark.asyncio
    async def test_ingest_answer_marks_section_done_when_gate_met(self):
        from app.graph.profile import ingest_answer

        # Mock profile_row so _get_profile_snapshot returns name+email → personal gate met
        profile_row = MagicMock()
        profile_row.__getitem__ = lambda s, k: {
            "user": {"name": "Jane", "email": "jane@example.com"},
            "skills": [], "experiences": [], "projects": [], "education": [], "achievements": [],
        }.get(k, [])

        drv = _mock_async_driver(profile_row=profile_row)
        with patch("app.graph.profile.async_driver", return_value=drv):
            result = await ingest_answer({
                "user_id": "u1",
                "last_reply": "My name is Jane, email jane@example.com",
                "current_section": "personal",
                "sections_done": [],
                "section_attempts": {},
            })
        # After ingesting personal info, gate should be met, section marked done
        assert "personal" in result.get("sections_done", [])


# ── Tailor graph nodes ─────────────────────────────────────────────────────────
class TestTailorNodes:

    @pytest.mark.asyncio
    async def test_parse_jd_returns_requirements(self):
        from app.graph.tailor import parse_jd

        result = await parse_jd({"jd_text": "We need a Python engineer with FastAPI skills."})
        assert "jd_requirements" in result
        req = result["jd_requirements"]
        assert "required_skills" in req
        assert "preferred_skills" in req

    @pytest.mark.asyncio
    async def test_gap_check_finds_missing_skills(self):
        from app.graph.tailor import gap_check

        result = gap_check({
            "jd_requirements": {
                "required_skills": ["Kubernetes", "Go"],
                "preferred_skills": [],
                "keywords": [],
            },
            "profile": {"skills": [{"name": "Python"}], "experiences": [], "projects": []},
        })
        assert "Kubernetes" in result["gaps"]
        assert "Go" in result["gaps"]

    @pytest.mark.asyncio
    async def test_gap_check_no_gaps_when_profile_has_skills(self):
        from app.graph.tailor import gap_check

        result = gap_check({
            "jd_requirements": {
                "required_skills": ["Python"],
                "preferred_skills": [],
                "keywords": [],
            },
            "profile": {"skills": [{"name": "Python", "rawName": "Python"}],
                        "experiences": [], "projects": []},
        })
        assert result["gaps"] == []

    def test_score_variants_populates_ats(self):
        from app.graph.tailor import score_variants

        variants = [
            {
                "label": "balanced",
                "resume": {
                    "name": "Jane",
                    "contact": {"email": "j@j.com"},
                    "core_competencies": ["Python"],
                    "experience": [],
                    "projects": [],
                },
            }
        ]
        result = score_variants({
            "jd_requirements": {"required_skills": ["Python"], "preferred_skills": [], "keywords": []},
            "jd_text": "Need Python developer",
            "variants": variants,
        })
        assert "ats" in result["variants"][0]
        assert "score" in result["variants"][0]["ats"]

    @pytest.mark.asyncio
    async def test_generate_variants_returns_three_labels(self):
        from app.graph.tailor import generate_variants

        drv = _mock_async_driver(profile_row=None)
        with patch("app.graph.tailor.async_driver", return_value=drv):
            result = await generate_variants({
                "user_id": "u1",
                "jd_text": "Python FastAPI role",
                "profile": {"skills": [], "experiences": [], "projects": [], "contact": {}},
                "ranked": {"skills": [], "projects": [], "experiences": []},
            })
        labels = [v["label"] for v in result["variants"]]
        assert set(labels) == {"conservative", "balanced", "aggressive"}
