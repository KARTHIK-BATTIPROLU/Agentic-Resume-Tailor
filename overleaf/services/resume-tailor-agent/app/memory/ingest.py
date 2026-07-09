"""File ingestion: PDF / DOCX → plain text, with a plain-text fallback.

Public API:

    extract_text(content: bytes, filename: str) -> str

Pass raw file bytes and the original filename (used to detect format).
Returns extracted plain text suitable for feeding into extract_career_facts.

Dependencies:
    pdfplumber  — PDF text extraction
    python-docx — DOCX text extraction
Both are optional at import time; a clear RuntimeError is raised at call time
if the required package is missing so the rest of the app can boot without them.
"""
from __future__ import annotations

import io


def _extract_pdf(content: bytes) -> str:
    try:
        import pdfplumber
    except ImportError as exc:
        raise RuntimeError(
            "pdfplumber is required for PDF extraction — install it via requirements.txt"
        ) from exc

    text_parts: list[str] = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                text_parts.append(t)
    return "\n\n".join(text_parts)


def _extract_docx(content: bytes) -> str:
    try:
        import docx  # python-docx
    except ImportError as exc:
        raise RuntimeError(
            "python-docx is required for DOCX extraction — install it via requirements.txt"
        ) from exc

    doc = docx.Document(io.BytesIO(content))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n".join(paragraphs)


def extract_text(content: bytes, filename: str) -> str:
    """Extract plain text from a PDF, DOCX, or TXT file.

    Args:
        content:  Raw file bytes.
        filename: Original filename (used to detect format by extension).

    Returns:
        Extracted plain text string.

    Raises:
        ValueError:   Unsupported file format.
        RuntimeError: Required extraction library not installed.
    """
    name_lower = (filename or "").lower()

    if name_lower.endswith(".pdf"):
        return _extract_pdf(content)

    if name_lower.endswith(".docx"):
        return _extract_docx(content)

    if name_lower.endswith((".txt", ".text", ".md")):
        return content.decode("utf-8", errors="replace")

    # Last resort: try UTF-8 decode and hope it's text.
    try:
        decoded = content.decode("utf-8", errors="strict")
        if decoded.strip():
            return decoded
    except UnicodeDecodeError:
        pass

    raise ValueError(
        f"Unsupported file format '{filename}'. Upload a PDF, DOCX, or plain-text file."
    )
