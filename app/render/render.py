"""Render a tailored-resume JSON object to a PDF via Jinja2 + LaTeX (tectonic).

Public contract:

    render_pdf(resume: dict, out_dir: str) -> str

``resume`` is the ``resume`` sub-object produced by the resume architect (see
:data:`app.agent.prompts.RESUME_ARCHITECT_SYSTEM_PROMPT`). The function writes
``<out_dir>/resume.tex`` and compiles it with ``tectonic`` to
``<out_dir>/resume.pdf``, returning the absolute path to that PDF.

All user-supplied strings are LaTeX-escaped, so arbitrary resume content cannot
break compilation.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

_HERE = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# LaTeX escaping
# ---------------------------------------------------------------------------
_LATEX_MAP = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
    "<": r"\textless{}",
    ">": r"\textgreater{}",
}
# A single pass over the original string (re.sub never rescans its own output),
# so the backslash replacement does not get re-escaped.
_LATEX_RE = re.compile("[" + re.escape("".join(_LATEX_MAP.keys())) + "]")


def escape_latex(value: Any) -> str:
    """Escape a value for safe inclusion in LaTeX body text."""
    if value is None:
        return ""
    return _LATEX_RE.sub(lambda m: _LATEX_MAP[m.group()], str(value))


def _escape_struct(obj: Any) -> Any:
    """Recursively LaTeX-escape every string in a nested dict/list structure."""
    if isinstance(obj, dict):
        return {k: _escape_struct(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_escape_struct(v) for v in obj]
    if isinstance(obj, str):
        return escape_latex(obj)
    return obj


# ---------------------------------------------------------------------------
# URL / contact helpers
# ---------------------------------------------------------------------------
def _url_target(url: str) -> str:
    """Make a hyperref-safe URL target, ensuring a scheme is present."""
    u = url.strip()
    if not u:
        return ""
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", u):
        u = "https://" + u
    # hyperref's first argument still needs a few characters escaped.
    return u.replace("\\", r"\\").replace("%", r"\%").replace("#", r"\#")


def _format_url(url: str) -> tuple[str, str]:
    """Return (escaped display text, hyperref-safe target) for a URL."""
    display = escape_latex(url.strip())
    return display, _url_target(url)


def _build_contacts(resume: dict[str, Any]) -> list[str]:
    """Build a list of LaTeX-safe contact snippets for the header line."""
    contact = resume.get("contact") or {}
    parts: list[str] = []

    email = (contact.get("email") or "").strip()
    if email:
        parts.append(rf"\href{{mailto:{_url_target(email).replace('https://', '')}}}"
                     rf"{{{escape_latex(email)}}}")

    phone = (contact.get("phone") or "").strip()
    if phone:
        parts.append(escape_latex(phone))

    location = (contact.get("location") or "").strip()
    if location:
        parts.append(escape_latex(location))

    for key in ("linkedin", "github", "portfolio"):
        val = (contact.get(key) or "").strip()
        if val:
            disp, target = _format_url(val)
            parts.append(rf"\href{{{target}}}{{{disp}}}")

    return parts


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------
def _as_list(v: Any) -> list:
    return v if isinstance(v, list) else ([] if v in (None, "") else [v])


def _normalize(resume: dict[str, Any]) -> dict[str, Any]:
    """Coerce the resume into the exact shape the template expects."""
    contact = resume.get("contact") or {}
    return {
        "name": resume.get("name") or "",
        "contact": {
            "email": contact.get("email") or "",
            "phone": contact.get("phone") or "",
            "location": contact.get("location") or "",
            "linkedin": contact.get("linkedin") or "",
            "github": contact.get("github") or "",
            "portfolio": contact.get("portfolio") or "",
        },
        "summary": resume.get("summary") or "",
        "core_competencies": [str(c) for c in _as_list(resume.get("core_competencies"))],
        "experience": [
            {
                "company": j.get("company") or "",
                "title": j.get("title") or "",
                "location": j.get("location") or "",
                "start": j.get("start") or "",
                "end": j.get("end") or "",
                "bullets": [str(b) for b in _as_list(j.get("bullets"))],
            }
            for j in _as_list(resume.get("experience"))
            if isinstance(j, dict)
        ],
        "projects": [
            {
                "name": p.get("name") or "",
                "tech": [str(t) for t in _as_list(p.get("tech"))],
                "link": p.get("link") or None,
                "bullets": [str(b) for b in _as_list(p.get("bullets"))],
            }
            for p in _as_list(resume.get("projects"))
            if isinstance(p, dict)
        ],
        "education": [
            {
                "degree": e.get("degree") or "",
                "institution": e.get("institution") or "",
                "location": e.get("location") or "",
                "start": e.get("start") or "",
                "end": e.get("end") or "",
                "details": e.get("details") or None,
            }
            for e in _as_list(resume.get("education"))
            if isinstance(e, dict)
        ],
        "certifications": [str(c) for c in _as_list(resume.get("certifications"))],
        "achievements": [str(a) for a in _as_list(resume.get("achievements"))],
    }


# ---------------------------------------------------------------------------
# Jinja environment
# ---------------------------------------------------------------------------
def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_HERE)),
        block_start_string="((*",
        block_end_string="*))",
        variable_start_string="(((",
        variable_end_string=")))",
        comment_start_string="((=",
        comment_end_string="=))",
        trim_blocks=True,
        lstrip_blocks=True,
        autoescape=False,
        keep_trailing_newline=True,
    )


def _run_tectonic(tex_path: Path, out_dir: Path) -> None:
    exe = shutil.which("tectonic")
    if not exe:
        raise RuntimeError(
            "tectonic was not found on PATH. Install it (the Docker image bundles "
            "it) before rendering PDFs."
        )
    # Run with the .tex basename and cwd=out_dir so the input resolves correctly
    # (passing a relative path while also setting cwd would double-nest it), and
    # tectonic writes resume.pdf next to the input by default.
    proc = subprocess.run(
        [exe, tex_path.name],
        cwd=str(out_dir),
        capture_output=True,
        text=True,
        timeout=240,
    )
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-2000:]
        raise RuntimeError(f"tectonic failed (exit {proc.returncode}):\n{tail}")


def build_tex(resume: dict) -> str:
    """Render the resume to a LaTeX source string (no compilation)."""
    normalized = _normalize(resume or {})
    escaped = _escape_struct(normalized)

    # Project links are built from the *original* values (escaping a URL would
    # break the hyperref target), then merged into the escaped structure.
    for original, esc in zip(normalized["projects"], escaped["projects"]):
        if original.get("link"):
            disp, target = _format_url(original["link"])
            esc["link"], esc["link_raw"] = disp, target
        else:
            esc["link"], esc["link_raw"] = None, None

    contacts = _build_contacts(normalized)
    return _env().get_template("template.tex").render(resume=escaped, contacts=contacts)


def render_pdf(resume: dict, out_dir: str) -> str:
    """Render ``resume`` to ``<out_dir>/resume.pdf`` and return its path."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    tex = build_tex(resume)
    tex_path = out / "resume.tex"
    tex_path.write_text(tex, encoding="utf-8")

    _run_tectonic(tex_path, out)

    pdf_path = out / "resume.pdf"
    if not pdf_path.exists() or pdf_path.stat().st_size == 0:
        raise RuntimeError("tectonic finished but no non-empty resume.pdf was produced.")
    return str(pdf_path.resolve())
