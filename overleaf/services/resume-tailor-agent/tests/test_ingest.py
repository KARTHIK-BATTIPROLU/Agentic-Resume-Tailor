"""Unit tests for file ingestion (no external deps needed for plain-text path)."""
import pytest
from app.memory.ingest import extract_text


def test_txt_extraction():
    content = b"Hello world\nSecond line"
    assert extract_text(content, "resume.txt") == "Hello world\nSecond line"


def test_md_extraction():
    content = "# Resume\n\nSkills: Python".encode("utf-8")
    result = extract_text(content, "resume.md")
    assert "Python" in result


def test_unsupported_format_raises():
    with pytest.raises(ValueError, match="Unsupported"):
        extract_text(b"\x89PNG\r\n", "photo.png")


def test_utf8_fallback():
    content = "Résumé content".encode("utf-8")
    result = extract_text(content, "resume.bin")
    assert "Résumé" in result
