"""Unit tests for .tex rendering (no compilation, no tectonic)."""
import pytest
from app.render.render import build_tex, escape_latex


def test_escape_special_chars():
    assert r"\&" in escape_latex("AT&T")
    assert r"\$" in escape_latex("$1M")
    assert r"\_" in escape_latex("snake_case")


def test_build_tex_returns_string():
    resume = {
        "name": "Jane Doe",
        "contact": {"email": "jane@example.com", "phone": "555-1234",
                    "location": "NYC", "linkedin": "", "github": "", "portfolio": ""},
        "summary": "Experienced engineer.",
        "core_competencies": ["Python", "FastAPI"],
        "experience": [{"company": "Acme", "title": "SWE", "location": "Remote",
                        "start": "2020", "end": "2024",
                        "bullets": ["Built REST APIs", "Led a team of 5"]}],
        "projects": [{"name": "MyApp", "tech": ["Python"], "link": None,
                      "bullets": ["Open source tool"]}],
        "education": [{"degree": "BS CS", "institution": "MIT",
                       "location": "Cambridge", "start": "2016", "end": "2020",
                       "details": None}],
        "certifications": [],
        "achievements": ["Best intern 2019"],
    }
    tex = build_tex(resume)
    assert isinstance(tex, str)
    assert "Jane Doe" in tex
    assert "Acme" in tex
    assert "FastAPI" in tex


def test_build_tex_empty_resume():
    tex = build_tex({})
    assert isinstance(tex, str)


def test_special_chars_escaped_in_tex():
    resume = {
        "name": "O'Brien & Co",
        "contact": {"email": "test@test.com"},
        "summary": "Expert in C++ & Python",
        "core_competencies": [],
        "experience": [], "projects": [], "education": [],
        "certifications": [], "achievements": [],
    }
    tex = build_tex(resume)
    assert "\\&" in tex
