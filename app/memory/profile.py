"""Apply extracted facts to the per-user profile, with dedup + confidence gating.

Gating rule: items with a ``confidence`` field (skills, projects, experiences) are
written to their collection only when confidence is HIGH; MEDIUM/LOW items go to
``pending_confirmations`` to await user approval. Items without a confidence
field (education, certifications, achievements) are written directly.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from app import db
from app.memory.embed import bullet_text, embed, project_text, skill_text


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _conf(item: dict[str, Any]) -> str:
    c = (item.get("confidence") or "MEDIUM")
    c = str(c).upper()
    return c if c in {"HIGH", "MEDIUM", "LOW"} else "MEDIUM"


async def _upsert(collection, key_filter: dict, set_fields: dict) -> None:
    """Upsert by natural key; never put filter keys inside ``$set``."""
    now = _now()
    await collection.update_one(
        key_filter,
        {
            "$set": {**set_fields, "updated_at": now},
            "$setOnInsert": {"item_id": str(uuid4()), "created_at": now},
        },
        upsert=True,
    )


# ---------------------------------------------------------------------------
# Writers for a single item (shared by apply_extraction and confirm)
# ---------------------------------------------------------------------------
async def _write_skill(user_id: str, skill: dict[str, Any]) -> bool:
    name = (skill.get("name") or "").strip()
    if not name:
        return False
    emb = await embed(skill_text(skill))
    await _upsert(
        db.skills(),
        {"user_id": user_id, "name_key": name.lower()},
        {
            "name": name,
            "category": skill.get("category"),
            "proficiency": skill.get("proficiency"),
            "confidence": _conf(skill),
            "embedding": emb,
        },
    )
    return True


async def _write_project(user_id: str, project: dict[str, Any]) -> bool:
    name = (project.get("name") or "").strip()
    if not name:
        return False
    emb = await embed(project_text(project))
    await _upsert(
        db.projects(),
        {"user_id": user_id, "name_key": name.lower()},
        {
            "name": name,
            "description": project.get("description"),
            "role": project.get("role"),
            "tech_stack": project.get("tech_stack") or [],
            "outcomes": project.get("outcomes") or [],
            "confidence": _conf(project),
            "embedding": emb,
        },
    )
    return True


async def _write_experience(user_id: str, exp: dict[str, Any]) -> bool:
    company = (exp.get("company") or "").strip()
    title = (exp.get("title") or "").strip()
    if not company and not title:
        return False
    bullets = []
    for b in exp.get("bullets") or []:
        if not isinstance(b, dict):
            continue
        text = (b.get("text") or "").strip()
        if not text:
            continue
        bullets.append(
            {"text": text, "metric": b.get("metric"), "embedding": await embed(bullet_text(b))}
        )
    await _upsert(
        db.experiences(),
        {"user_id": user_id, "company_key": company.lower(), "title_key": title.lower()},
        {
            "company": company,
            "title": title,
            "location": exp.get("location"),
            "start": exp.get("start"),
            "end": exp.get("end"),
            "is_current": bool(exp.get("is_current")),
            "bullets": bullets,
            "confidence": _conf(exp),
        },
    )
    return True


async def _write_education(user_id: str, e: dict[str, Any]) -> bool:
    degree = (e.get("degree") or "").strip()
    inst = (e.get("institution") or "").strip()
    if not degree and not inst:
        return False
    await _upsert(
        db.education(),
        {"user_id": user_id, "degree_key": degree.lower(), "institution_key": inst.lower()},
        {
            "degree": degree,
            "institution": inst,
            "location": e.get("location"),
            "start": e.get("start"),
            "end": e.get("end"),
            "details": e.get("details"),
        },
    )
    return True


async def _write_certification(user_id: str, c: dict[str, Any]) -> bool:
    name = (c.get("name") or "").strip()
    if not name:
        return False
    await _upsert(
        db.certifications(),
        {"user_id": user_id, "name_key": name.lower()},
        {"name": name, "issuer": c.get("issuer"), "year": c.get("year")},
    )
    return True


async def _write_achievement(user_id: str, text: Any) -> bool:
    text = (str(text) if text is not None else "").strip()
    if not text:
        return False
    await _upsert(
        db.achievements(),
        {"user_id": user_id, "text_key": text.lower()},
        {"text": text},
    )
    return True


# ---------------------------------------------------------------------------
# Pending confirmations (MEDIUM/LOW gated items)
# ---------------------------------------------------------------------------
def _dedup_key(kind: str, item: dict[str, Any]) -> str:
    if kind == "experience":
        return f"{(item.get('company') or '').lower()}|{(item.get('title') or '').lower()}"
    return (item.get("name") or "").lower()


def _summary(kind: str, item: dict[str, Any]) -> str:
    if kind == "experience":
        return f"{item.get('title') or '?'} @ {item.get('company') or '?'}"
    return item.get("name") or kind


async def _add_pending(user_id: str, kind: str, item: dict[str, Any], conf: str) -> dict:
    now = _now()
    flt = {
        "user_id": user_id,
        "kind": kind,
        "dedup_key": _dedup_key(kind, item),
        "status": "awaiting",
    }
    await db.pending_confirmations().update_one(
        flt,
        {
            "$set": {"data": item, "confidence": conf, "summary": _summary(kind, item),
                     "updated_at": now},
            "$setOnInsert": {"confirmation_id": str(uuid4()), "created_at": now},
        },
        upsert=True,
    )
    doc = await db.pending_confirmations().find_one(flt)
    return {
        "confirmation_id": doc["confirmation_id"],
        "kind": kind,
        "summary": doc.get("summary", ""),
        "confidence": conf,
    }


# ---------------------------------------------------------------------------
# Identity (profiles doc)
# ---------------------------------------------------------------------------
async def _update_identity(user_id: str, extraction: dict[str, Any]) -> None:
    contact = extraction.get("contact") or {}
    set_fields: dict[str, Any] = {}
    for k in ("name", "email", "phone", "location", "linkedin", "github", "portfolio"):
        v = contact.get(k)
        if v:
            set_fields[f"contact.{k}"] = v
    if extraction.get("headline"):
        set_fields["headline"] = extraction["headline"]

    now = _now()
    set_fields["updated_at"] = now
    await db.profiles().update_one(
        {"user_id": user_id},
        {"$set": set_fields, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
async def apply_extraction(user_id: str, extraction: dict[str, Any]) -> dict:
    """Apply an extraction result; return ``{"added": {...}, "pending": [...]}``."""
    extraction = extraction or {}
    added = {
        "skills": 0, "projects": 0, "experiences": 0,
        "education": 0, "certifications": 0, "achievements": 0,
    }
    pending: list[dict] = []

    await _update_identity(user_id, extraction)

    gated = [
        ("skills", "skill", _write_skill),
        ("projects", "project", _write_project),
        ("experiences", "experience", _write_experience),
    ]
    for section, kind, writer in gated:
        for item in extraction.get(section) or []:
            if not isinstance(item, dict):
                continue
            if _conf(item) == "HIGH":
                if await writer(user_id, item):
                    added[section] += 1
            else:
                pending.append(await _add_pending(user_id, kind, item, _conf(item)))

    for e in extraction.get("education") or []:
        if isinstance(e, dict) and await _write_education(user_id, e):
            added["education"] += 1
    for c in extraction.get("certifications") or []:
        if isinstance(c, dict) and await _write_certification(user_id, c):
            added["certifications"] += 1
    for a in extraction.get("achievements") or []:
        if await _write_achievement(user_id, a):
            added["achievements"] += 1

    return {"added": added, "pending": pending}


async def confirm(user_id: str, confirmation_id: str, approved: bool) -> dict:
    """Approve (write to collection) or reject a pending item."""
    coll = db.pending_confirmations()
    doc = await coll.find_one({"confirmation_id": confirmation_id, "user_id": user_id})
    if not doc:
        return {"status": "not_found", "applied": False}
    if doc.get("status") != "awaiting":
        return {"status": doc.get("status"), "kind": doc.get("kind"), "applied": False}

    kind = doc.get("kind")
    if not approved:
        await coll.update_one({"_id": doc["_id"]}, {"$set": {"status": "rejected"}})
        return {"status": "rejected", "kind": kind, "applied": False}

    writers = {"skill": _write_skill, "project": _write_project, "experience": _write_experience}
    writer = writers.get(kind)
    applied = bool(writer and await writer(user_id, doc.get("data") or {}))
    await coll.update_one({"_id": doc["_id"]}, {"$set": {"status": "approved"}})
    return {"status": "approved", "kind": kind, "applied": applied}


async def get_profile(user_id: str) -> dict:
    """Assemble all of a user's items into the CANDIDATE_PROFILE shape."""
    profile_doc = await db.profiles().find_one({"user_id": user_id}) or {}
    contact_raw = profile_doc.get("contact") or {}
    contact = {
        k: contact_raw.get(k)
        for k in ("name", "email", "phone", "location", "linkedin", "github", "portfolio")
    }

    skills = [
        {"item_id": s.get("item_id"), "name": s.get("name"),
         "category": s.get("category"), "proficiency": s.get("proficiency")}
        async for s in db.skills().find({"user_id": user_id})
    ]
    experiences = [
        {
            "item_id": x.get("item_id"),
            "company": x.get("company"), "title": x.get("title"),
            "location": x.get("location"), "start": x.get("start"), "end": x.get("end"),
            "is_current": x.get("is_current", False),
            "bullets": [
                {"text": b.get("text"), "metric": b.get("metric")}
                for b in (x.get("bullets") or [])
            ],
        }
        async for x in db.experiences().find({"user_id": user_id})
    ]
    projects = [
        {
            "item_id": p.get("item_id"),
            "name": p.get("name"), "description": p.get("description"), "role": p.get("role"),
            "tech_stack": p.get("tech_stack") or [], "outcomes": p.get("outcomes") or [],
        }
        async for p in db.projects().find({"user_id": user_id})
    ]
    education = [
        {
            "item_id": e.get("item_id"),
            "degree": e.get("degree"), "institution": e.get("institution"),
            "location": e.get("location"), "start": e.get("start"), "end": e.get("end"),
            "details": e.get("details"),
        }
        async for e in db.education().find({"user_id": user_id})
    ]
    certifications = [
        {"item_id": c.get("item_id"), "name": c.get("name"),
         "issuer": c.get("issuer"), "year": c.get("year")}
        async for c in db.certifications().find({"user_id": user_id})
    ]
    achievements = [
        {"item_id": a.get("item_id"), "text": a.get("text")}
        async for a in db.achievements().find({"user_id": user_id})
    ]

    return {
        "contact": contact,
        "headline": profile_doc.get("headline"),
        "summary": profile_doc.get("master_summary"),
        "skills": skills,
        "experiences": experiences,
        "projects": projects,
        "education": education,
        "certifications": certifications,
        "achievements": achievements,
    }


# ---------------------------------------------------------------------------
# Inline edit / delete (REST CRUD) — re-embeds embeddable items
# ---------------------------------------------------------------------------
def _clean(doc: dict[str, Any]) -> dict[str, Any]:
    """Strip internal fields (``_id``, embeddings) from a stored item."""
    if not doc:
        return {}
    out = {k: v for k, v in doc.items() if k not in ("_id", "embedding") and not k.endswith("_key")}
    if isinstance(out.get("bullets"), list):
        out["bullets"] = [
            {k: v for k, v in b.items() if k != "embedding"} if isinstance(b, dict) else b
            for b in out["bullets"]
        ]
    return out


def _normalize_bullets(bullets: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for b in bullets or []:
        if isinstance(b, str):
            b = {"text": b}
        if isinstance(b, dict) and (b.get("text") or "").strip():
            out.append({"text": b["text"].strip(), "metric": b.get("metric")})
    return out


async def edit_item(user_id: str, section: str, item_id: str, fields: dict[str, Any]):
    """Update one profile item; re-embed if it is an embeddable section.

    Returns the updated, cleaned item, or ``None`` if not found.
    """
    factory = db.SECTION_COLLECTIONS.get(section)
    if factory is None:
        raise ValueError(f"unknown section '{section}'")
    coll = factory()
    doc = await coll.find_one({"user_id": user_id, "item_id": item_id})
    if not doc:
        return None

    reserved = {"user_id", "item_id", "_id", "embedding", "created_at"}
    set_fields = {k: v for k, v in (fields or {}).items() if k not in reserved}

    if section == "experiences" and "bullets" in set_fields:
        set_fields["bullets"] = _normalize_bullets(set_fields["bullets"])

    merged = {**doc, **set_fields}
    if section == "skills":
        set_fields["embedding"] = await embed(skill_text(merged))
    elif section == "projects":
        set_fields["embedding"] = await embed(project_text(merged))
    elif section == "experiences":
        set_fields["bullets"] = [
            {**b, "embedding": await embed(bullet_text(b))}
            for b in (merged.get("bullets") or [])
        ]

    set_fields["updated_at"] = _now()
    await coll.update_one({"_id": doc["_id"]}, {"$set": set_fields})
    return _clean(await coll.find_one({"user_id": user_id, "item_id": item_id}))


async def delete_item(user_id: str, section: str, item_id: str) -> bool:
    """Delete one profile item. Returns True if something was removed."""
    factory = db.SECTION_COLLECTIONS.get(section)
    if factory is None:
        raise ValueError(f"unknown section '{section}'")
    res = await factory().delete_one({"user_id": user_id, "item_id": item_id})
    return res.deleted_count > 0
