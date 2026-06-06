# Agentic Resume Tailor (v2)

Two **LangGraph** agents, two interfaces, streamed over **WebSockets**:

1. **Profile Builder** — a human-in-the-loop interview that asks ONE question at a
   time (Personal → Education → Skills → Projects → Experience → Achievements),
   extracts structured facts from each reply, and upserts them to a verified
   profile. Editable, live-updating section cards; paste a resume to bootstrap.
2. **Resume Tailor** — paste a job description; the agent parses it, semantically
   ranks your own items, asks **≤3** targeted gap questions, then generates **three
   resume variants** (conservative / balanced / aggressive), scores each with a
   deterministic **ATS scorer**, and renders each to PDF. Edit a variant and
   **re-score live**.

It never fabricates: every resume line is grounded in facts you provided; missing
metrics go to `analysis.needs_confirmation`, never the resume body.

## Architecture

```
chat replies ─▶ Profile Builder graph (interrupt per question)
                   route_section → compose_question → ask(interrupt)
                   → ingest → validate → upsert → …            ⮌ MongoDB checkpoint

job description ─▶ Resume Tailor graph
                   parse_jd → load_rank → gap_check
                     → (≤3) ask gap question (interrupt) ⮌
                   → generate 3 variants → ATS score → render 3 PDFs
```

- **LLM:** Groq `llama-3.3-70b-versatile` (JSON mode).
- **Embeddings:** local `all-MiniLM-L6-v2` (384-d), inline in Mongo + numpy cosine.
- **Agents:** LangGraph + **MongoDB checkpointer** (`langgraph-checkpoint-mongodb`),
  human-in-the-loop via `interrupt()` / `Command(resume=...)`. Checkpoints live in
  their own collections (`lg_checkpoints`, `lg_checkpoint_writes`).
- **ATS scorer:** deterministic & explainable (`60·keyword_match + 40·quality`).
- **PDF:** Jinja2 → LaTeX → `tectonic`.

### Note on the Mongo driver
The data layer uses **pymongo's native async driver** (`AsyncMongoClient`), not
**motor**. motor caps pymongo at `<4.10`, which conflicts with
`langgraph-checkpoint-mongodb` (`pymongo>=4.12`). `AsyncMongoClient` is MongoDB's
official successor to motor with the same API surface.

## Configuration

Copy `.env.example` to `.env`:

```
GROQ_API_KEY=your-groq-key
MONGO_URI=mongodb://localhost:27017
```

Secrets are read via pydantic-settings; nothing is hardcoded and `.env` is ignored.

## Run with Docker

```bash
docker build -t resume-tailor .
docker run --rm --env-file .env -p 8000:8000 resume-tailor
```

Open <http://localhost:8000> (UI) or <http://localhost:8000/docs>. On Docker Desktop
reach a host Mongo via `MONGO_URI=mongodb://host.docker.internal:27017`.

## Run locally

Requires Python 3.11+, a running MongoDB, and `tectonic` on PATH.

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Smoke test

```bash
python -m scripts.smoke_test
```

(1) unit-tests the ATS scorer; (2) drives the Profile Builder graph and checks a
Mongo checkpoint persisted; (3) runs the Tailor graph and asserts **3 scored
variants + non-empty PDFs**. Needs `GROQ_API_KEY`, `MONGO_URI`, `tectonic`.

## API

REST (`app/api/rest.py`):

| Method | Path | Notes |
|--------|------|-------|
| GET | `/` | UI · GET `/health` |
| GET | `/profile/{user_id}` | assembled profile (items include `item_id`) |
| PATCH | `/profile/{user_id}/{section}/{item_id}` | edit an item (re-embeds) |
| DELETE | `/profile/{user_id}/{section}/{item_id}` | delete an item |
| POST | `/chat` | bootstrap profile from pasted text |
| POST | `/confirm` | approve/reject a pending item |
| POST | `/score` | `{resume_json, job_description}` → ATS breakdown (live re-score) |
| GET | `/resume/{resume_id}/pdf?variant=balanced` | a variant's PDF |

`section` ∈ `skills · experiences · projects · education · certifications · achievements`.

WebSockets (`app/api/ws.py`):

- `WS /ws/profile/{user_id}` — drives the Profile Builder. Client sends
  `{type:"start", resume_text?}` then `{type:"reply", message}`; server streams
  `status` / `question` / `section_update` / `confirm` / `done`.
- `WS /ws/tailor/{user_id}` — drives the Resume Tailor. Client sends
  `{type:"start", job_description}` then `{type:"reply", message}`; server streams
  `status` / `question` / `variants` / `done`.

## Confidence gating

Extracted skills / projects / experiences are written to the profile only at
**HIGH** confidence; **MEDIUM/LOW** become `pending_confirmations` and surface as
confirm chips → `POST /confirm`.

## Project layout

```
app/
  main.py            FastAPI app (REST + WS, static mount, lifespan/indexes)
  config.py          env + constants (CHECKPOINT_COLLECTION, MAX_JD_QUESTIONS, VARIANT_LABELS)
  db.py              pymongo AsyncMongoClient, collections, ensure_indexes()
  models.py          pydantic request/response models
  memory/            embed.py · extract.py · profile.py (CRUD) · retrieve.py
  agent/
    prompts.py       extraction + architect(variant) + PROFILE_QUESTION + JD_PARSE + JD_GAP_QUESTION
    llm.py           shared Groq JSON helper
    ats.py           deterministic ATS scorer (pure)
    checkpointer.py  MongoDBSaver factory
    profile_graph.py Profile Builder LangGraph
    tailor_graph.py  Resume Tailor LangGraph (3 variants)
    generate.py      single-resume generator (reused by tailor)
  render/            template.tex · render.py (JSON → tex → tectonic → PDF)
  api/               rest.py · ws.py
web/                 index.html · app.js · styles.css (two tabs)
scripts/smoke_test.py · sample_data/
```
