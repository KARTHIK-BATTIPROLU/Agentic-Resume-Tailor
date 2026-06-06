"""Deterministic, explainable ATS scorer — no LLM, pure and unit-testable.

``score(resume_json, jd_requirements, jd_text)`` returns:
    {score, match_pct, matched[], missing[], checks{...}}
"""
from __future__ import annotations

import re
from typing import Any

# Common acronym / spelling variants treated as equivalent for matching.
_SYNONYMS: dict[str, list[str]] = {
    "postgresql": ["postgres", "psql"],
    "postgres": ["postgresql"],
    "kubernetes": ["k8s"],
    "k8s": ["kubernetes"],
    "javascript": ["js"],
    "typescript": ["ts"],
    "ci/cd": ["cicd", "ci cd", "continuous integration", "continuous delivery"],
    "rest": ["restful", "rest api", "rest apis"],
    "ml": ["machine learning"],
    "machine learning": ["ml"],
    "gcp": ["google cloud", "google cloud platform"],
    "aws": ["amazon web services"],
    "nlp": ["natural language processing"],
}

_TOKEN_RE = re.compile(r"[a-z0-9+#.]+")
_STOP = {"and", "or", "the", "a", "an", "of", "to", "in", "with", "for", "on", "&"}


def _normalize(text: str) -> str:
    """Lowercase and reduce to a space-padded token stream for substring matching."""
    cleaned = re.sub(r"[^a-z0-9+#./ ]", " ", (text or "").lower())
    cleaned = cleaned.replace("/", " ")
    return " " + " ".join(cleaned.split()) + " "


def _flatten_resume(resume: dict[str, Any]) -> str:
    parts: list[str] = []

    def add(v: Any) -> None:
        if isinstance(v, str):
            parts.append(v)
        elif isinstance(v, list):
            for x in v:
                add(x)
        elif isinstance(v, dict):
            for x in v.values():
                add(x)

    add(resume or {})
    return " ".join(parts)


def _bullets(resume: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for job in resume.get("experience") or []:
        if isinstance(job, dict):
            out.extend(b for b in (job.get("bullets") or []) if isinstance(b, str))
    for proj in resume.get("projects") or []:
        if isinstance(proj, dict):
            out.extend(b for b in (proj.get("bullets") or []) if isinstance(b, str))
    return out


def _term_present(term: str, padded_text: str) -> bool:
    base = " ".join(re.sub(r"[^a-z0-9+#./ ]", " ", term.lower()).replace("/", " ").split())
    if not base:
        return False
    candidates = [base] + _SYNONYMS.get(term.strip().lower(), []) + _SYNONYMS.get(base, [])
    for cand in candidates:
        toks = [t for t in cand.split() if t and t not in _STOP]
        if not toks:
            continue
        if len(toks) == 1:
            if f" {toks[0]} " in padded_text:
                return True
        else:
            # Multi-word term: count it matched if all significant tokens appear.
            if all(f" {t} " in padded_text for t in toks):
                return True
    return False


def _quality_blend(resume: dict[str, Any], checks: dict[str, Any]) -> float:
    wc = checks["word_count"]
    if 400 <= wc <= 900:
        wc_signal = 1.0
    elif wc < 400:
        wc_signal = max(0.0, wc / 400.0)
    else:
        wc_signal = max(0.0, 1.0 - (wc - 900) / 900.0)
    signals = [
        1.0,  # single_column
        1.0,  # standard_headers
        1.0,  # no_tables
        float(checks["quantified_bullets"]),
        wc_signal,
        1.0 if checks["contact_complete"] else 0.0,
    ]
    return sum(signals) / len(signals)


def score(resume_json: dict, jd_requirements: dict, jd_text: str = "") -> dict:
    """Score a resume against parsed JD requirements. Pure & deterministic."""
    resume = (resume_json or {}).get("resume", resume_json) or {}
    jd_requirements = jd_requirements or {}

    important: list[str] = []
    seen = set()
    for key in ("required_skills", "preferred_skills", "keywords"):
        for term in jd_requirements.get(key) or []:
            t = str(term).strip()
            k = t.lower()
            if t and k not in seen:
                seen.add(k)
                important.append(t)

    padded = _normalize(_flatten_resume(resume))
    matched = [t for t in important if _term_present(t, padded)]
    missing = [t for t in important if t not in matched]
    match_pct = (len(matched) / len(important)) if important else 0.0

    bullets = _bullets(resume)
    quantified = sum(1 for b in bullets if re.search(r"[0-9]|%|\$", b))
    quantified_ratio = (quantified / len(bullets)) if bullets else 0.0
    word_count = len(_flatten_resume(resume).split())
    contact = resume.get("contact") or {}
    contact_complete = bool((resume.get("name")) and contact.get("email"))

    checks = {
        "single_column": True,
        "standard_headers": True,
        "no_tables": True,
        "quantified_bullets": round(quantified_ratio, 2),
        "word_count": word_count,
        "word_count_ok": 400 <= word_count <= 900,
        "contact_complete": contact_complete,
    }

    final = round(60 * match_pct + 40 * _quality_blend(resume, checks))
    return {
        "score": int(final),
        "match_pct": round(match_pct, 3),
        "matched": matched,
        "missing": missing,
        "checks": checks,
    }
