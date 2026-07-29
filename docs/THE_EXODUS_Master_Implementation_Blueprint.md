# THE EXODUS — Master Implementation Blueprint

**Complete build specification. Self-contained — assumes no prior document, only the repository.**

Repo: `Dapper434/ProjectGen` · Engineering codename **FactoryOS** · Product name **The Exodus**
Client: GDF Kenya (Genesis Design Factory) and any other that interact with clients to make proposals and give tasks to talents
Prepared: **July 28, 2026** · Internal

---

## 0. How to use this document

This is the single specification for everything being added to The Exodus. It is written to be handed to a coding agent **one work package at a time**. Every `WP-n` section is self-contained: scope, data model, endpoints, file touch list, code sketches, and acceptance criteria.

The companion file **`AGENTS.md`** goes at the repository root. It is the short, always-loaded contract — invariants, conventions, and the list of things that look like good ideas and are not. This file is the reference the agent gets pointed at per task.

**Working loop:**

1. Pick the next `WP-n` in the build order (§3.3). Do not start a WP whose dependencies are unmerged.
2. Read that WP section plus `AGENTS.md`. Restate the scope in two sentences before writing code.
3. Build in order: **migration → models → service module → route → frontend → test**.
4. Check every box in the WP's acceptance criteria. Anything you cannot check, say so in the PR.
5. Ship behind the WP's feature flag, default **off**.

Section §1 describes what the repository already contains. It was accurate as of a direct code read on July 25, 2026 — **verify against the current tree before relying on any specific line reference.** If code and document disagree, the code wins and the discrepancy gets reported.

---

## 1. What already exists

### 1.1 Architecture

```
Browser (React 18 + Vite + Tailwind, deployed on Vercel)
 │ /api/* rewrite (same-origin, so session cookies stay first-party)
 ▼
Flask + SQLAlchemy (backend/app.py) ── gunicorn --workers 1 --threads 8
 │ (single worker is deliberate: SQLite is a single-writer database)
 ├── ThreadPoolExecutor(max_workers=3)  ← background agent jobs
 │     agents.py: generate_brief · refine_brief · extract_meeting_signals ·
 │                generate_proposal · revise_proposal
 │     all model calls go to NVIDIA NIM (Nemotron reasoning model)
 ├── weasyprint → Brief / Proposal PDF export (built and working)
 ├── fathom.py → Svix-signed webhook receiver + registration CLI
 └── SQLite (factoryos.db)

Deploy: Vercel (frontend) + Cloudflare Tunnel → gunicorn (backend), per DEPLOY.md
```

### 1.2 The agent pipeline (`backend/agents.py`)

| Function | Role | Triggered by |
|---|---|---|
| `generate_brief()` | Turns the first client-meeting transcript into a structured Production Brief | `POST /api/engagements/<id>/transcripts` when status is `awaiting_transcript` |
| `refine_brief()` | Targeted-edit update to an existing brief from a later intake meeting | same endpoint, status `brief_ready` |
| `extract_meeting_signals()` + `generate_proposal()` | Merges Brief + review-meeting transcript + Rate Card + Past Projects into a scoped Client Proposal | same endpoint, status `awaiting_review_transcript` |
| `revise_proposal()` | Targeted revision when an Account Manager sends the proposal back with notes | `POST /api/engagements/<id>/proposals/review` with `action: "send_back"` |

All of these run on the shared `ThreadPoolExecutor(max_workers=3)`, dispatched via `_executor.submit(task, eng_id, transcript_id)`, gated by a per-engagement `Engagement.is_processing` boolean, and logged to a shared `AgentEvent` table that already functions as the system's agent-activity audit trail.

**The pattern to imitate:** the Flask route creates the row, sets `is_processing = True`, commits, submits the task, and returns **202 immediately** — the HTTP request never waits on an LLM call. The worker thread re-queries fresh ORM objects (thread-local `db_session`), does the work, writes the result, clears the flag, logs an `AgentEvent`, and calls `db_session.remove()` in a `finally` block. Task functions take **primitive IDs only**, never live ORM objects. The frontend polls `GET /api/engagements/<id>` and watches `is_processing`.

### 1.3 The Fathom inbox (`backend/fathom.py`, `app.py`)

Fully built and self-activating. `fathom_webhook()` parses the payload, dedupes on Fathom's `recording_id`, and for external meetings calls `_auto_match_client(title)`, which does an exact case-insensitive substring match against every client name. On a single unambiguous match, `_attach_inbound(..., auto=True)` creates the `Transcript` row and submits the agent job immediately — **no human clicks anything**. Anything that does not match unambiguously lands as pending in the Inbox UI (`Inbox.jsx`) for a manual Attach.

### 1.4 The proposal review gate (`app.py`, approximately lines 1085–1134)

`POST /api/engagements/<id>/proposals/review` with `action: "approve"` sets `proposal.status = 'approved'` and `engagement.status = 'approved'`, restricted to the Account Manager role. The frontend already derives `proposalApproved = engagement?.proposal?.status === 'approved'` and uses it to gate the Download PDF button in `EngagementDetail.jsx`.

### 1.5 PDF generation

`build_proposal_pdf_html()` + WeasyPrint already renders an approved proposal to a branded PDF for `GET /api/engagements/<id>/proposal/pdf`. Any new delivery path attaches this same byte stream — there is no need for a second rendering path.

### 1.6 Constraints to respect

- **Single gunicorn worker, single-writer SQLite** — documented deliberately in `DEPLOY.md` and `ASSUMPTIONS.md` #4. New background work goes through the existing executor pattern, not a second ad-hoc thread pool.
- **No email-sending library** in `backend/requirements.txt` today. No SMTP wrapper, no SendGrid/Postmark SDK.
- **`Client` has no contact email** (`models.py`: `id, name, industry, notes` only).
- **No accessibility tooling** in `frontend/package.json` — no `eslint-plugin-jsx-a11y`, no `axe-core`.
- **No real migration tool.** `backend/migrate_schema.py` is a hand-written, idempotent `ALTER TABLE ADD COLUMN` script paired with `create_all()` for new tables — it gets an existing SQLite file's columns in sync with `models.py`, but it cannot rename, drop, or batch-alter anything. This blueprint adds roughly seventeen tables; Alembic is WP-0 and is not optional. `migrate_schema.py` is superseded once Alembic lands and should not gain new columns after that.
- **No test suite** on the frontend. The backend has no `pytest` suite either — `backend/test_pdf_gen.py` is a manual script (it renders a PDF to disk when run directly), not a pytest test module, despite the `test_` filename.

### 1.7 A naming note

The codebase and internal docs (README, backend routes, deploy notes) refer to the system as **FactoryOS** — that is the engineering codename. The product is branded **The Exodus** in product copy (see the client-acceptance screen in `EngagementDetail.jsx`). Use "The Exodus" in anything a user reads; "FactoryOS" only for the repo and internal code.

### 1.8 A gap in this document: Part 2 already exists

This blueprint's §2 talks about talent (WP-9/10/11) as a new capability area. It is not entirely new. The repo already has a working, deterministic **Part 2 pipeline** — "client acceptance → production staffing" — that this document was not written against:

- `models.py`: `Talent` (`name`, `title`, `skills` JSON, `day_rate_kes`, `availability`, `available_from`, `location`, `years_experience`, `highlight`, `is_active`) and `StaffingPlan` (`engagement_id`, `proposal_id`, `plan` JSON).
- `backend/staffing.py`: `build_staffing_plan()` — greedy, deterministic title/skill scoring against the `Talent` pool with tie-breaks and human-readable `match_reasons`. No LLM call.
- `backend/seed_talents.py` seeds the pool; `app.py` exposes `GET /api/talents`, `POST /api/engagements/<id>/staffing`, `GET /api/engagements/<id>/staffing`.

WP-9's token ledger, certifications, and availability calendar are genuinely new. WP-10's Casting Agent is genuinely new for the *proposal-time* ranking-with-rationale use case the blueprint describes. But both must **extend the existing `Talent`/`StaffingPlan` tables additively** (new nullable columns, new related tables for tokens/certs) rather than re-modelling talent from scratch — see the note added to `AGENTS.md` §1. Treat `staffing.py`'s scoring function as prior art for WP-10's casting algorithm, not a thing to route around.

---

## 2. What is being built

Ten capability areas, delivered as fifteen work packages:

1. **Voice dictation** — speak into any transcript box, with four interchangeable speech engines.
2. **Post-meeting transcription (cloud)** — upload a recording after the meeting, get a transcript in minutes via Groq.
3. **Post-meeting transcription (local)** — the same thing on your own hardware: free, private, offline, slower.
4. **Boardroom live transcription** — a live meeting page that transcribes as you go and, at the end, tells you **what nobody asked about**, judged against an authoritative meeting protocol. Then feeds straight into brief generation.
5. **Provider registry and a switching Lab** — every pluggable capability has multiple drivers, switchable from the frontend at runtime, with a side-by-side bake-off tool so you can compare before committing.
6. **Authoritative data everywhere** — versioned, scoped, viewable, editable system knowledge (rate cards, meeting protocols, token policy, casting weights, prompts) consumed by every agent.
7. **Talent acquisition** — a token-based bench: talents earn tokens from events, certifications, and idle time; a Casting Agent ranks them against role requirements and availability.
8. **Talent-facing portal** — auth, mock certification, portfolio, availability, token ledger, offers, and a page that explains exactly how selection works.
9. **Reviewed-then-emailed delivery** — a Send via Email action that unlocks only after Account Manager approval.
10. **Accessibility** — real screen-reader and keyboard support, verified by tooling, across old and new UI.

### 2.1 The work packages

| WP | Name | Depends on | Effort | Flag |
|---|---|---|---|---|
| **WP-0** | Repo prep: Alembic, config object, feature flags, `/api/config` | — | 0.5 d | — |
| **WP-1** | Authoritative Data Layer | WP-0 | 2–2.5 d | `FEATURE_AUTH_DATA` |
| **WP-2** | **Provider Registry, Runtime Settings & the Lab** | WP-0, WP-1 | 3–4 d | `FEATURE_LAB` |
| **WP-3** | Agent lock scoping (`AgentLock`) | WP-0 | 0.5–1 d | — |
| **WP-4** | STT driver layer: Groq, local Whisper, Wispr, browser + polish stage | WP-0, WP-2 | 2.5–3 d | `FEATURE_VOICE` |
| **WP-5** | Voice dictation in `TranscriptDropArea` | WP-4 | 0.5–1 d | `FEATURE_VOICE` |
| **WP-6** | **Recording Studio — post-meeting transcription, cloud and local** | WP-3, WP-4 | 2.5–3 d | `FEATURE_RECORDINGS` |
| **WP-7** | Boardroom live transcription + Coverage Agent | WP-1, WP-3, WP-4 | 3.5–4 d | `FEATURE_BOARDROOM` |
| **WP-8** | Fathom zero-click: fuzzy match + `[ENG-XXXX]` tag | WP-1 | 0.5 d | — |
| **WP-9** | Talent domain: talents, tokens, certifications, availability | WP-0, WP-1 | 2–3 d | `FEATURE_TALENT` |
| **WP-10** | Casting Agent + assignment lifecycle | WP-1, WP-3, WP-9 | 2–2.5 d | `FEATURE_TALENT` |
| **WP-11** | Talent-facing portal | WP-9, WP-12 | 3–4 d | `FEATURE_TALENT_PORTAL` |
| **WP-12** | Reviewed-then-emailed proposal delivery | WP-1 | 1–1.5 d | `FEATURE_EMAIL` |
| **WP-13** | Accessibility pass across all UI | all UI WPs | 3–4 d | — |
| **WP-14** | Local-first developer experience + deployment readiness | all | 2–2.5 d | — |

**Total: ~29–37 working days.** Nothing replaces the Nemotron pipeline, the Flask+React architecture, or the deploy topology. Every change is additive.

### 2.2 Dependency graph

```
WP-0  repo prep
 ├── WP-1  authoritative data ─┬── WP-2  provider registry + Lab ─┬── WP-4  STT drivers ─┬── WP-5  dictation
 │                             │                                   │                      ├── WP-6  recording studio
 │                             ├── WP-7  boardroom ────────────────┴──────────────────────┘
 │                             ├── WP-8  fathom zero-click
 │                             ├── WP-9  talent ── WP-10 casting ── WP-11 talent portal
 │                             └── WP-12 email ────────────────────┘ (invite + offer mail)
 └── WP-3  agent locks ── (WP-6, WP-7, WP-10 all acquire locks)

WP-13 accessibility  (last — sweeps every screen built above)
WP-14 local + deploy (runs alongside from WP-0; hardening finishes last)
```

### 2.3 Recommended build order

| Phase | Days | Work | Why here |
|---|---|---|---|
| **0** | 1 | WP-0 | Seventeen tables are arriving. Migrations and flags first, or you will regret it in week three. |
| **1** | 2–6 | WP-1, WP-3, WP-8 | Foundations that later WPs consume, plus a half-day win (WP-8) that widens what already works today. |
| **2** | 7–10 | WP-2 | The provider registry. Build it **before** the STT drivers so the drivers are born switchable rather than retrofitted. |
| **3** | 11–17 | WP-4, WP-5, WP-6 | All three transcription paths — dictation, cloud post-meeting, local post-meeting — testable side by side in the Lab by the end of this phase. This is the phase where you decide what to settle on. |
| **4** | 18–22 | WP-7 | Boardroom. Largest single feature; needs the protocol (WP-1), locks (WP-3), and STT (WP-4) landed. |
| **5** | 23–24 | WP-12 | Email. Unblocks talent invites and offers. Can run in parallel with WP-7 if two people are available. |
| **6** | 25–32 | WP-9, WP-10, WP-11 | Talent, in strict order: data → scoring → portal. |
| **7** | 33–37 | WP-13, WP-14 | Accessibility sweep across everything at once, then deploy hardening. |

---

## 3. Cross-cutting architecture: everything pluggable

> *"Have the options readily available for me to test and switch between in the frontend before I settle on something. What else can you have options to switch between?"*

This is the organising idea of the whole build, so it gets stated once, up front, and then every WP conforms to it.

### 3.1 The shape

Three layers, built once in WP-2 and reused everywhere:

```
┌──────────────────────────────────────────────────────────────────┐
│  CAPABILITY            an abstract job: "turn audio into text"    │
│    └── DRIVERS         concrete implementations: groq, local, ... │
│          └── OPTIONS   per-driver knobs: model, chunk size, temp  │
└──────────────────────────────────────────────────────────────────┘
             ▲                    ▲                     ▲
      env default          runtime setting        per-request
      (Config)             (DB, set in UI)        override (Lab)
             └────────── resolution order, lowest to highest ───────┘
```

**Resolution order** — later wins:

1. **Hardcoded fallback** in the registry (so a broken config never means a dead app).
2. **Environment default** (`Config.STT_LIVE_DRIVER`), which is what production boots with.
3. **Runtime setting** stored in the database, changed from the frontend, effective immediately with no restart.
4. **Per-request override** (`X-Driver-Override: stt_batch=local_whisper`), used by the Lab and by "transcribe this one with the other engine" buttons.

### 3.2 What you get to switch between

The honest version of this table matters more than a long one. Not every knob deserves a switch — each one is code, UI, and a test surface. Tier 1 is built in this blueprint; Tier 2 is cheap to add once the registry exists; Tier 3 is deliberately *not* a runtime switch and the reason is given.

**Tier 1 — built now, switchable in the UI**

| Capability | Drivers | Why you'd switch |
|---|---|---|
| `stt_live` | `groq_chunked`, `local_whisper_chunked`, `wispr_stream`, `browser_webspeech`, `off` | Live boardroom and dictation. Trade latency against cost against privacy. |
| `stt_batch` | `groq_batch`, `local_whisper_batch`, `wispr_batch`, `off` | Post-meeting recordings. Cloud is minutes; local is free and private. |
| `polish` | `ollama`, `nim`, `groq_llm`, `off` | Cleaning raw transcripts. Local model here costs nothing per run. |
| `agent_llm` | `nim_nemotron`, `ollama`, `groq_llm` | Which model writes briefs and proposals. The most consequential switch in the system. |
| `coverage_llm` | `nim_nemotron`, `nim_small`, `ollama`, `groq_llm` | Boardroom coverage checks run every 90 seconds. A cheap model here saves real money. |
| `email` | `console`, `sendgrid`, `postmark`, `resend`, `smtp` | `console` locally, real provider in production, swap on deliverability. |
| `client_match` | `exact`, `fuzzy_difflib`, `eng_tag_then_fuzzy` | How aggressively Fathom auto-attaches meetings. |
| `prompt_variant` | any active version of the relevant authoritative prompt doc | A/B two brief-writing prompts on the same transcript. |

**Tier 2 — the registry makes these nearly free to add later**

| Capability | Drivers | Note |
|---|---|---|
| `casting_rank` | `weighted_score`, `tokens_only`, `lottery`, `weighted_plus_llm_review` | Worth building once the bench has real data to argue about (§WP-10). |
| `diarization` | `off`, `heuristic_llm`, `pyannote_local` | Speaker labelling. `pyannote_local` needs a GPU; do not promise it. |
| `pdf` | `weasyprint`, `playwright_print` | Only if WeasyPrint's CSS support becomes a limitation. |
| `storage` | `local_fs`, `s3_compatible` | Only when recordings need to outlive the box. |

**Tier 3 — configuration, deliberately not a runtime switch**

| Thing | Why not |
|---|---|
| Database (`sqlite` / `postgres`) | Switching at runtime is meaningless; it is a `DATABASE_URL` and a data migration. |
| Auth mechanism | Security surfaces should have exactly one code path. |
| Feature flags | Already a separate mechanism; do not nest one switch system inside another. |

### 3.3 The Lab

The bake-off UI is what makes the whole thing worth building. `/lab/transcription` takes one audio file, runs it through two to four selected drivers, and shows results side by side with a text diff, word counts, wall-clock latency, and estimated cost. `/lab/agents` does the same for brief generation across model drivers or prompt variants. A **"Use this one"** button on a winning column writes the runtime setting.

Full specification in **WP-2**.

---

## WP-0 — Repo prep · 0.5 d

Small, boring, non-negotiable. Roughly seventeen tables and eighty routes are arriving; the repo has no migration tool and no way to ship a half-built feature safely.

### 0.1 Alembic

```bash
cd backend
pip install alembic
alembic init migrations
# migrations/env.py:  target_metadata = Base.metadata
#                     url from Config.DATABASE_URL
#                     context.configure(..., render_as_batch=True)   ← required for SQLite
alembic revision --autogenerate -m "baseline: current schema"    # review by hand
alembic stamp head                                               # for existing dev databases
```

**From here on: one migration per work package, autogenerated then hand-reviewed.** SQLite cannot `ALTER COLUMN`; every new column must be nullable or carry a server default. `render_as_batch=True` is what lets Alembic emulate table alterations on SQLite.

### 0.2 Config object

Replace scattered `os.environ.get(...)` calls with one module. Every switchable capability gets an env default here; WP-2 layers runtime overrides on top.

```python
# backend/config.py  (NEW)
import os

def _bool(key, default="false"):
    return os.environ.get(key, default).strip().lower() in ("1", "true", "yes", "on")

class Config:
    SECRET_KEY   = os.environ.get("SECRET_KEY", "dev-only-change-me")
    DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///factoryos.db")
    APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:5173")
    UPLOAD_DIR   = os.environ.get("UPLOAD_DIR", "./var/uploads")

    # --- model providers -------------------------------------------------
    NIM_API_KEY     = os.environ.get("NIM_API_KEY")
    NIM_BASE_URL    = os.environ.get("NIM_BASE_URL", "https://integrate.api.nvidia.com/v1")
    NIM_MODEL       = os.environ.get("NIM_MODEL", "nvidia/llama-3.3-nemotron-super-49b-v1")
    NIM_SMALL_MODEL = os.environ.get("NIM_SMALL_MODEL", "")
    GROQ_API_KEY    = os.environ.get("GROQ_API_KEY")
    GROQ_LLM_MODEL  = os.environ.get("GROQ_LLM_MODEL", "llama-3.3-70b-versatile")
    OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL    = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b-instruct")

    # --- speech ----------------------------------------------------------
    GROQ_STT_MODEL   = os.environ.get("GROQ_STT_MODEL", "whisper-large-v3-turbo")
    WHISPER_BASE_URL = os.environ.get("WHISPER_BASE_URL", "http://localhost:8001/v1")
    WHISPER_MODEL    = os.environ.get("WHISPER_MODEL", "Systran/faster-whisper-small")
    WISPRFLOW_API_KEY = os.environ.get("WISPRFLOW_API_KEY")
    STT_KEEP_AUDIO   = _bool("STT_KEEP_AUDIO")
    STT_DAILY_SECONDS_PER_USER = int(os.environ.get("STT_DAILY_SECONDS_PER_USER", "7200"))

    # --- email -----------------------------------------------------------
    SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY")
    POSTMARK_TOKEN   = os.environ.get("POSTMARK_SERVER_TOKEN")
    RESEND_API_KEY   = os.environ.get("RESEND_API_KEY")
    EMAIL_FROM       = os.environ.get("EMAIL_FROM", "proposals@gdfkenya.com")

    # --- default driver per capability (WP-2 can override at runtime) -----
    DEFAULT_DRIVERS = {
        "stt_live":     os.environ.get("STT_LIVE_DRIVER",     "groq_chunked"),
        "stt_batch":    os.environ.get("STT_BATCH_DRIVER",    "groq_batch"),
        "polish":       os.environ.get("POLISH_DRIVER",       "ollama"),
        "agent_llm":    os.environ.get("AGENT_LLM_DRIVER",    "nim_nemotron"),
        "coverage_llm": os.environ.get("COVERAGE_LLM_DRIVER", "ollama"),
        "email":        os.environ.get("EMAIL_DRIVER",        "console"),
        "client_match": os.environ.get("CLIENT_MATCH_DRIVER", "eng_tag_then_fuzzy"),
    }

    FLAGS = {
        "auth_data":     _bool("FEATURE_AUTH_DATA"),
        "lab":           _bool("FEATURE_LAB"),
        "voice":         _bool("FEATURE_VOICE"),
        "recordings":    _bool("FEATURE_RECORDINGS"),
        "boardroom":     _bool("FEATURE_BOARDROOM"),
        "talent":        _bool("FEATURE_TALENT"),
        "talent_portal": _bool("FEATURE_TALENT_PORTAL"),
        "email":         _bool("FEATURE_EMAIL"),
    }
```

`EMAIL_DRIVER=console` prints the email to stdout instead of sending it. That is what makes WP-11's invite flow and WP-12 fully testable locally with no vendor account.

### 0.3 Feature flags, enforced on both sides

```python
# backend/app.py
from functools import wraps

def feature(name):
    def deco(fn):
        @wraps(fn)
        def inner(*a, **kw):
            if not Config.FLAGS.get(name):
                return jsonify({"error": "Feature not enabled."}), 404
            return fn(*a, **kw)
        return inner
    return deco

@app.route('/api/config')
def get_config():
    return jsonify({"flags": Config.FLAGS, "product": "The Exodus"})
```

```jsx
// frontend/src/lib/config.jsx (NEW) — one fetch on boot, provided via context
const { flags } = useConfig();
{flags.boardroom && <StartBoardroomButton engagementId={eng.id} />}
```

A disabled feature returns **404, not 403** — a dark-shipped feature should be indistinguishable from one that does not exist.

### 0.4 Acceptance criteria

- [ ] `alembic upgrade head` builds the current schema from empty; `--autogenerate` on a clean tree produces an empty diff.
- [ ] `env.py` uses `render_as_batch=True`.
- [ ] Every existing route still works with all flags off.
- [ ] `GET /api/config` returns all eight flags; the frontend hides flagged navigation.
- [ ] `.env.example` committed, listing every key in `Config` with safe defaults and a one-line comment each.

---

## WP-1 — Authoritative Data Layer · 2–2.5 d

> *Requirement: "Authoritative data should be viewable and should be able to be added for more sections of the system."*

### 1.1 The problem

The Proposal agent already consumes two authoritative inputs — the **Rate Card** and **Past Projects** — as code constants or ad-hoc rows: not versioned, not viewable in the UI, not attributable, not scopeable to one client. Nearly every feature in this blueprint needs the same thing for its own domain:

| Feature | Authoritative data it needs |
|---|---|
| Brief agent (exists) | Brief template, brand voice |
| Proposal agent (exists) | Rate card, past projects, brand voice, proposal template |
| Boardroom (WP-7) | **Meeting protocol — the required-topics list coverage is judged against** |
| Fathom matching (WP-8) | Fuzzy threshold, minimum name length |
| Casting (WP-10) | Token policy, casting weights, role definitions |
| Talent portal (WP-11) | Certification catalog, the "how you get picked" explanation |
| Email (WP-12) | Cover-note template |
| The Lab (WP-2) | Prompt variants for A/B testing |

Building each as its own table with its own admin screen is seven times the work and produces seven inconsistent editors. Build one layer.

### 1.2 Data model

```python
# backend/models.py
class AuthoritativeDoc(Base):
    __tablename__ = 'authoritative_docs'
    id          = Column(Integer, primary_key=True)
    key         = Column(String(60), nullable=False, index=True)
    scope_type  = Column(String(20), nullable=False, default='global')   # global | client | engagement
    scope_id    = Column(Integer, nullable=True)
    title       = Column(String(160), nullable=False)
    fmt         = Column(String(10), nullable=False, default='markdown') # markdown | json
    body        = Column(Text, nullable=False)
    version     = Column(Integer, nullable=False, default=1)
    is_active   = Column(Boolean, nullable=False, default=True)
    label       = Column(String(40))     # optional variant tag, e.g. 'concise' — used by the Lab
    note        = Column(Text)           # changelog line for this version
    updated_by  = Column(Integer, ForeignKey('users.id'), nullable=True)
    updated_at  = Column(DateTime, default=datetime.datetime.utcnow)
    # UniqueConstraint('key','scope_type','scope_id','version')
    # Index('ix_auth_lookup','key','scope_type','scope_id','is_active')
```

**Documents are immutable. Editing creates version N+1 and deactivates version N.** No UPDATE path on `body`. This gives version history, rollback, and — critically — the ability to answer *"which rate card did this proposal actually use?"* six months later.

One nullable column on the existing audit table:

```python
# AgentEvent gains provenance
authoritative_refs = Column(Text)   # JSON: [{"key":"rate_card","scope":"global","version":3}, ...]
```

Every agent run records which authoritative versions it read. This is the highest-value line in WP-1: it turns the existing `AgentEvent` log into a **reproducible** one.

### 1.3 Resolution: most-specific-active-wins

```python
# backend/authoritative.py  (NEW)
def resolve(key, engagement=None, client=None, version=None, label=None):
    """Engagement override beats client override beats global default.
    Returns (parsed_body, provenance) or (None, None)."""
    client = client or (engagement.client if engagement else None)
    candidates = [('engagement', engagement.id if engagement else None),
                  ('client',     client.id if client else None),
                  ('global',     None)]
    for scope_type, scope_id in candidates:
        if scope_type != 'global' and scope_id is None:
            continue
        q = db_session.query(AuthoritativeDoc).filter_by(
                key=key, scope_type=scope_type, scope_id=scope_id)
        q = q.filter_by(version=version) if version else q.filter_by(is_active=True)
        if label:
            q = q.filter_by(label=label)
        doc = q.order_by(AuthoritativeDoc.version.desc()).first()
        if doc:
            body = json.loads(doc.body) if doc.fmt == 'json' else doc.body
            return body, {"key": key, "scope": scope_type, "scope_id": scope_id,
                          "version": doc.version, "label": doc.label}
    return None, None
```

No merging between scopes. An engagement-level rate card *replaces* the global one rather than patching it. Merge semantics are where this kind of layer usually goes wrong and nobody has asked for them.

### 1.4 The key registry — declared in code

The registry is what makes the UI self-documenting and stops the table becoming a junk drawer.

```python
REGISTRY = {
  'rate_card':            {'fmt':'json','scopes':('global','client'),              'consumers':['generate_proposal'], 'schema':RATE_CARD_SCHEMA},
  'past_projects':        {'fmt':'markdown','scopes':('global','client'),          'consumers':['generate_proposal']},
  'brand_voice':          {'fmt':'markdown','scopes':('global','client'),          'consumers':['generate_brief','generate_proposal','render_email_body']},
  'brief_prompt':         {'fmt':'markdown','scopes':('global',),                  'consumers':['generate_brief','refine_brief'], 'variants':True},
  'proposal_prompt':      {'fmt':'markdown','scopes':('global',),                  'consumers':['generate_proposal','revise_proposal'], 'variants':True},
  'coverage_prompt':      {'fmt':'markdown','scopes':('global',),                  'consumers':['analyze_coverage'], 'variants':True},
  'polish_prompt':        {'fmt':'markdown','scopes':('global',),                  'consumers':['polish'], 'variants':True},
  'boardroom_protocol':   {'fmt':'json','scopes':('global','client','engagement'), 'consumers':['analyze_coverage','Boardroom.jsx'], 'schema':PROTOCOL_SCHEMA},
  'fathom_matching':      {'fmt':'json','scopes':('global',),                      'consumers':['_auto_match_client'], 'schema':MATCHING_SCHEMA},
  'talent_token_policy':  {'fmt':'json','scopes':('global',),                      'consumers':['tokens.balance','HowIGetPicked.jsx'], 'schema':TOKEN_POLICY_SCHEMA},
  'casting_policy':       {'fmt':'json','scopes':('global','engagement'),          'consumers':['run_casting','HowIGetPicked.jsx'], 'schema':CASTING_POLICY_SCHEMA},
  'certification_catalog':{'fmt':'json','scopes':('global',),                      'consumers':['TalentCertifications.jsx'], 'schema':CERT_CATALOG_SCHEMA},
  'email_cover_note':     {'fmt':'markdown','scopes':('global','client'),          'consumers':['render_email_body']},
}
```

JSON bodies are validated against their schema on save using `pydantic` (already a dependency — do not add a new validation library). **A `json` doc that fails validation cannot be saved.** An agent must never crash at 2am because someone typo'd a weight.

`'variants': True` marks documents the Lab can A/B: multiple active versions may coexist with different `label` values, and `resolve(..., label=...)` picks one.

### 1.5 API

```
GET  /api/authoritative                     ?scope_type=&scope_id=    active docs + registry metadata
GET  /api/authoritative/registry            the REGISTRY map, for the "used by" UI
GET  /api/authoritative/resolve/<key>       ?engagement_id=|client_id=|label=   resolved body + provenance
GET  /api/authoritative/<key>/versions      ?scope_type=&scope_id=    full history, newest first
POST /api/authoritative                     create version N+1 (validates against schema)
POST /api/authoritative/<id>/activate       rollback: reactivate an older version
```

Write access: `Account Manager` and `Admin`. Read: any authenticated internal role. **The Talent role gets none of this** — a separate whitelisted endpoint in WP-11 exposes only the token and casting policies. Rate cards must never leak to contractors.

### 1.6 Frontend — one editor, embedded in many places

```
frontend/src/pages/Playbook.jsx                 (NEW)  the global list: key, scope, version, updated by/when.
                                                       Shipped as AuthoritativeData.jsx; later merged with the
                                                       Requirements page into one "Playbook", grouped by
                                                       authoritative.GROUPS, because prompts, policies and the
                                                       completeness corpus are one mental model, not two pages
frontend/src/components/AuthoritativeEditor.jsx (NEW)  raw editor, JSON validation, diff vs active,
                                                       changelog note, version dropdown, rollback
frontend/src/components/AuthoritativePanel.jsx  (NEW)  embeddable read-only card + "Edit" affordance
```

`AuthoritativePanel` is the answer to *"viewable for more sections of the system."* It takes `keys` and a scope and mounts wherever context demands:

| Mounted in | Keys shown |
|---|---|
| `EngagementDetail.jsx` | `rate_card`, `past_projects`, `boardroom_protocol` — resolved for this engagement |
| `ClientDetail.jsx` | `rate_card`, `past_projects`, `brand_voice`, `email_cover_note` |
| `Boardroom.jsx` | `boardroom_protocol` (read-only during a live session — see WP-7 §7.6) |
| Talent admin | `talent_token_policy`, `casting_policy`, `certification_catalog` |
| Talent portal | `talent_token_policy`, `casting_policy` (read-only prose) |
| The Lab | all `variants: True` prompt docs |

**The scope badge matters.** A producer must be able to see at a glance *"this engagement is using the global rate card v4"* versus *"this engagement has its own rate card v2."*

### 1.7 Migrating the existing hardcoded data

```python
# backend/seed_authoritative.py (NEW) — idempotent, safe to re-run
# 1. Read the current hardcoded rate card / past projects / prompts out of agents.py
# 2. Insert each as scope_type='global', version=1, is_active=True
# 3. Leave the constants in place for one release as a logged fallback:

body, prov = resolve('rate_card', engagement=eng)
if body is None:
    body, prov = LEGACY_RATE_CARD, {"key":"rate_card","scope":"legacy_constant","version":0}
    log.warning("rate_card fell back to legacy constant")
```

Delete the fallback in the release *after* the seed lands, once logs show it never fires.

### 1.8 Acceptance criteria

- [x] Saving creates a new version; the previous row is untouched with `is_active=False`.
- [x] `resolve()` returns engagement over client over global — unit test with all three present.
- [x] A `json` doc failing its schema returns 400 and is not persisted.
- [x] Every existing agent function reads its inputs via `resolve()` and writes `authoritative_refs` into its `AgentEvent`. *(Prompts only — see §1.9 on the rate card.)*
- [x] Regenerating a proposal after a rate card edit shows the new version in `authoritative_refs`. *(Verified with a prompt edit rather than a rate card edit, for the same reason.)*
- [x] `AuthoritativePanel` renders in `EngagementDetail` and `ClientDetail` with a visible scope badge.
- [x] Rollback restores an old version as a new active pointer, not a mutation.
- [x] The Talent role receives 403 from `GET /api/authoritative`.

### 1.9 What WP-1 actually shipped, and two deliberate deviations

Built as specified: `AuthoritativeDoc`, `AgentEvent.authoritative_refs`, `backend/authoritative.py` (`resolve` / `create_version` / `activate_version` / `build_refs`), all six endpoints, `AuthoritativePanel` / `AuthoritativeEditor` / `AuthoritativeData.jsx` (now `Playbook.jsx`), and `seed_authoritative.py`. Everything sits behind `FEATURE_AUTH_DATA`, default off, 404 when disabled.

**Deviation 1 — five prompt keys, not two.** The sketch in §1.4 groups generation and refinement under one key each (`brief_prompt`, `proposal_prompt`). This repo's `agents.py` has five genuinely distinct system prompts, and two of them carry careful behavioural constraints that would be lost if merged: `revise_proposal`'s "copy every field verbatim unless asked to change it" rules directly contradict `generate_proposal`'s merge-and-rewrite instructions. The registry therefore has `brief_generation_prompt`, `brief_refinement_prompt`, `signal_extraction_prompt`, `proposal_generation_prompt`, and `proposal_revision_prompt`.

**Deviation 2 — `rate_card` and `past_projects` are NOT yet authoritative docs.** The blueprint assumes these are "code constants or ad-hoc rows." They are neither: `RateCardItem` and `PastProject` are real relational tables that `generate_proposal` already queries, and the rate card drives client pricing. Collapsing live pricing data into a versioned JSON blob is a product decision that touches money, so WP-1 built and proved the mechanism against the five prompts instead and left the pricing tables alone. Doing this properly is its own task: decide whether the rate card becomes a JSON doc or whether `AuthoritativeDoc` gains a pointer-to-table mode, then backfill. Until then a proposal's `authoritative_refs` records its prompt version but not its rate card version — the audit trail is real but not yet complete.

Also deferred with them: the `json`-format keys (`boardroom_protocol`, `fathom_matching`, `talent_token_policy`, `casting_policy`, `certification_catalog`) belong to WPs that have not landed. The schema-validation path they need is built and tested — a key only has to be added to `REGISTRY` with a `schema`.

---

## WP-2 — Provider Registry, Runtime Settings & the Lab · 3–4 d

> *Requirement: "Have the options readily available for me to test and switch between in the frontend before I settle on something."*

Build this **before** the STT drivers. Retrofitting switchability onto four hardcoded integrations costs more than building the socket first.

### 2.1 The driver interface

```python
# backend/providers/base.py  (NEW)
@dataclass
class DriverInfo:
    key: str                      # 'groq_batch'
    capability: str               # 'stt_batch'
    label: str                    # 'Groq (cloud, fast)'
    blurb: str                    # one sentence shown in the UI
    is_local: bool                # runs on our own hardware
    requires_env: tuple[str, ...] # ('GROQ_API_KEY',)
    cost_hint: str                # 'free tier: 2k req/day' | 'no marginal cost'
    options_schema: dict          # {'model': {'type':'string','default':'...'}}

class Driver(ABC):
    info: DriverInfo
    def __init__(self, options: dict | None = None): self.options = options or {}

    @abstractmethod
    def health(self) -> dict:
        """{'ok': bool, 'detail': str, 'latency_ms': int|None}. Never raises."""

    def available(self) -> bool:
        return all(getattr(Config, k, None) for k in self.info.requires_env)
```

Capability-specific subclasses add the actual method — `STTDriver.transcribe()`, `LLMDriver.complete()`, `EmailDriver.send()`. A driver that cannot run (missing key, unreachable host) reports it through `health()` and `available()` rather than throwing at call time.

### 2.2 Registry and resolution

```python
# backend/providers/registry.py  (NEW)
CAPABILITIES = {
    'stt_live':     {'label': 'Live speech-to-text',    'fallback': 'browser_webspeech'},
    'stt_batch':    {'label': 'Recording transcription','fallback': 'off'},
    'polish':       {'label': 'Transcript cleanup',     'fallback': 'off'},
    'agent_llm':    {'label': 'Brief & proposal model', 'fallback': 'nim_nemotron'},
    'coverage_llm': {'label': 'Coverage check model',   'fallback': 'nim_nemotron'},
    'email':        {'label': 'Email delivery',         'fallback': 'console'},
    'client_match': {'label': 'Fathom auto-matching',   'fallback': 'exact'},
}

_DRIVERS: dict[str, dict[str, type[Driver]]] = defaultdict(dict)

def register(cls):
    _DRIVERS[cls.info.capability][cls.info.key] = cls
    return cls

def get(capability, override=None, options=None) -> Driver:
    """Resolution: per-request override → runtime setting → env default → fallback."""
    key = (override
           or runtime_setting(capability)
           or Config.DEFAULT_DRIVERS.get(capability)
           or CAPABILITIES[capability]['fallback'])
    cls = _DRIVERS[capability].get(key)
    if cls is None or not cls().available():
        fb = CAPABILITIES[capability]['fallback']
        log.warning("driver %s/%s unavailable, falling back to %s", capability, key, fb)
        cls = _DRIVERS[capability][fb]
    return cls(options or runtime_options(capability))
```

**The fallback path is the point.** A missing `GROQ_API_KEY` must degrade to the browser engine with a visible badge, never a 500 in the middle of a client meeting.

### 2.3 Runtime settings

```python
class RuntimeSetting(Base):
    __tablename__ = 'runtime_settings'
    id          = Column(Integer, primary_key=True)
    capability  = Column(String(40), unique=True, nullable=False)
    driver_key  = Column(String(40), nullable=False)
    options     = Column(Text)          # JSON
    updated_by  = Column(Integer, ForeignKey('users.id'))
    updated_at  = Column(DateTime, default=datetime.datetime.utcnow)

class SettingChange(Base):              # append-only audit
    __tablename__ = 'setting_changes'
    id = Column(Integer, primary_key=True)
    capability = Column(String(40)); from_driver = Column(String(40)); to_driver = Column(String(40))
    options = Column(Text); changed_by = Column(Integer, ForeignKey('users.id'))
    changed_at = Column(DateTime, default=datetime.datetime.utcnow); reason = Column(String(200))
```

Cache settings in memory with a short TTL (30 s) or a version counter — this is read on nearly every request and must not be a database round trip each time. Admin role only for writes; every change appends to `SettingChange` so *"who switched us to the local model on Tuesday"* is answerable.

### 2.4 Per-request override

```
X-Driver-Override: stt_batch=local_whisper_batch;agent_llm=ollama
```

Parsed into a request-scoped dict that `get()` consults first. Restricted to Account Manager and Admin, and **ignored entirely when the flag `FEATURE_LAB` is off** — a per-request driver override is a debugging tool, not a production API surface.

### 2.5 Endpoints

```
GET  /api/providers                        every capability, its drivers, availability, current selection
GET  /api/providers/health                 live health for all drivers (cached 30s, parallel probes)
POST /api/providers/<capability>           {driver_key, options, reason} → set runtime setting
POST /api/providers/<capability>/test      smoke-test one driver, return latency + sample output
GET  /api/providers/history                the SettingChange log

POST /api/lab/transcribe                   multipart audio + drivers[] → ComparisonRun (async, 202)
POST /api/lab/generate                     {transcript_id|text, kind, drivers[]|prompt_labels[]} → ComparisonRun
GET  /api/lab/runs                         GET /api/lab/runs/<id>
POST /api/lab/runs/<id>/adopt              {capability, driver_key} → writes the runtime setting
```

### 2.6 The bake-off

```python
class ComparisonRun(Base):
    __tablename__ = 'comparison_runs'
    id         = Column(Integer, primary_key=True)
    capability = Column(String(40))                 # 'stt_batch' | 'agent_llm'
    input_kind = Column(String(20))                 # 'audio' | 'transcript'
    input_ref  = Column(String(300))                # file path or transcript id
    input_meta = Column(Text)                       # JSON: duration, size, source
    status     = Column(String(20), default='running')
    created_by = Column(Integer, ForeignKey('users.id'))
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class ComparisonResult(Base):
    __tablename__ = 'comparison_results'
    id           = Column(Integer, primary_key=True)
    run_id       = Column(Integer, ForeignKey('comparison_runs.id'), index=True)
    driver_key   = Column(String(40)); label = Column(String(60))
    options      = Column(Text)
    status       = Column(String(20))               # ok | error
    output       = Column(Text)
    error        = Column(Text)
    latency_ms   = Column(Integer)
    word_count   = Column(Integer)
    tokens_used  = Column(Integer)
    est_cost_usd = Column(Float)
    metrics      = Column(Text)                     # JSON: diff stats vs the reference column
```

Comparison jobs run on the shared executor **one driver at a time per run** (serial, not parallel) so a four-way bake-off cannot starve the agent pool. A run is progress-polled like every other async job in the system.

Metrics worth computing, cheap and genuinely useful:

- **Word count and duration-normalised speed** (words per audio-minute) — a driver that silently drops half the audio shows up instantly here.
- **Similarity to a chosen reference column** via `difflib.SequenceMatcher` ratio, plus the count of differing tokens. This is not a true word error rate — there is no ground truth — but *"local agrees with Groq 94% of the time"* is exactly the decision-grade number you need.
- **Latency** wall-clock, including upload.
- **Estimated cost** from a per-driver rate in `DriverInfo.cost_hint` — approximate, clearly labelled as such.

### 2.7 Frontend

```
frontend/src/pages/ProviderSettings.jsx     (NEW)  one card per capability
frontend/src/pages/LabTranscription.jsx     (NEW)  audio bake-off
frontend/src/pages/LabAgents.jsx            (NEW)  model / prompt bake-off
frontend/src/components/DriverPicker.jsx    (NEW)  radio list + options form + health dot + Test
frontend/src/components/DiffView.jsx        (NEW)  word-level diff, two columns
frontend/src/components/ComparisonTable.jsx (NEW)  side-by-side results + "Use this one"
frontend/src/components/ProviderBadge.jsx   (NEW)  small "via Groq · 1.2s" chip used across the app
```

**ProviderSettings** — one card per capability showing the current driver, a radio list of alternatives with blurb, local/cloud tag, cost hint and a health dot (green ok / amber degraded / red unavailable, with the reason: *"GROQ_API_KEY not set"*). Each driver exposes its options form from `options_schema`. A **Test** button runs the smoke probe and reports latency inline. Changing a driver asks for an optional reason, writes the setting, and takes effect on the next request — **no restart**.

**LabTranscription** — drop an audio file, tick two to four drivers, Run. Results stream in as each driver finishes: full text, word count, latency, cost estimate, and a diff against whichever column you nominate as the reference. Buttons: **Use this one** (adopts the runtime setting), **Save as sample** (keeps the audio for future comparisons), **Attach to engagement** (sends the winning transcript into the real pipeline, so a bake-off is never wasted work).

**LabAgents** — pick a transcript already in the system, tick model drivers and/or prompt variants, Run. Same table shape. This is how you decide whether Nemotron is worth it over a local model for brief generation, on your own data, before committing.

**ProviderBadge** appears wherever a driver was used — under a boardroom transcript, on a recording job, beside a generated brief. Small, quiet, and it means you never have to guess which engine produced a given artefact.

### 2.8 Acceptance criteria

- [x] A new driver is added by writing one class with an `@register` decorator — no changes to routes, settings, or Lab code.
- [x] Resolution order verified: per-request override beats runtime setting beats env default beats fallback.
- [x] A driver whose required env var is missing reports unavailable, is not selectable, and falls back with a warning log rather than raising. *(Verified with `nim_small`, which needs `NIM_SMALL_MODEL`.)*
- [x] Changing a driver in the UI affects the very next request, with no restart.
- [x] Every change is recorded in `SettingChange` with the actor.
- [~] **Model** bake-off completes and **Use this one** writes the runtime setting. The *transcription* bake-off is deferred — see below.
- [x] Comparison jobs run serially and cannot occupy more than one executor slot at a time.
- [x] With `FEATURE_LAB=false`, the `X-Driver-Override` header is ignored and Lab routes return 404.
- [x] `GET /api/providers/health` returns in under two seconds with unreachable hosts. *(Measured 1.5s with Ollama and SMTP both down.)*

### 2.9 What shipped, and what is deferred to WP-4

**Shipped:** `providers/base.py`, `providers/registry.py`, `RuntimeSetting` /
`SettingChange` / `ComparisonRun` / `ComparisonResult`, `provider_settings.py`,
`lab.py`, all nine endpoints, and the `ProviderSettings` / `LabAgents` /
`DriverPicker` / `ComparisonTable` / `ProviderBadge` frontend. Seven
capabilities are registered with sixteen drivers.

**`agents.py::call_nim_api()` now resolves through the registry.** It keeps its
original name and signature — the five agent functions are untouched — but the
model behind briefs and proposals is switchable at runtime. NIM is the
registry's fallback, so behaviour with no configuration is byte-identical to
before. The Nemotron reasoning presets moved from `agents.py` into
`providers/llm/nim.py`, since each driver maps the shared "off | low | full"
vocabulary onto its own knobs.

**Deferred to WP-4:** `LabTranscription.jsx`, `POST /api/lab/transcribe`, and
`DiffView.jsx`. All three compare STT engines, and no STT engine exists yet —
`providers/stt/` currently holds only the `off` no-op drivers, registered so
`stt_live` / `stt_batch` / `polish` resolve rather than raise, and so the
capabilities are visible in Provider Settings from day one. `lab.py` already
carries the generic run/result/serial-execution/similarity machinery, so WP-4
adds a transcribe task and a page, not a second Lab.

**`client_match` drivers now hold WP-8's matching logic** (`exact`,
`fuzzy_difflib`, `eng_tag_then_fuzzy` in `providers/client_match/matchers.py`),
making the blueprint's promised runtime switch real.
`app.py::_auto_match_client()` is now a thin wrapper that resolves the driver
through the registry, so the algorithm exists in exactly one place and the
Fathom webhook honours a runtime switch. Verified identical results before and
after the refactor on the same four titles, including the ambiguous
two-client case that must return `None`.

---

## WP-3 — Agent lock scoping · 0.5–1 d

Today, `Engagement.is_processing` is a single boolean meaning "something is busy." It cannot express *which* thing is busy, so two genuinely independent agent types on one engagement serialise behind one flag — and there is no timeout, so a worker that dies mid-call wedges the engagement until someone edits the database by hand. With four new agent types arriving, both problems become weekly.

```python
class AgentLock(Base):
    __tablename__ = 'agent_locks'
    id            = Column(Integer, primary_key=True)
    engagement_id = Column(Integer, ForeignKey('engagements.id'), nullable=True)
    scope         = Column(String(40), nullable=False)
    ref_type      = Column(String(30))    # 'engagement' | 'boardroom_session' | 'recording_job' | 'casting_run'
    ref_id        = Column(Integer)
    locked_at     = Column(DateTime, default=datetime.datetime.utcnow)
    locked_by     = Column(Integer, ForeignKey('users.id'), nullable=True)
    expires_at    = Column(DateTime)
    # UniqueConstraint('scope','ref_type','ref_id')
```

| Scope | Acquired by | Keyed on |
|---|---|---|
| `brief` | `generate_brief`, `refine_brief` | engagement |
| `proposal` | `extract_meeting_signals` + `generate_proposal`, `revise_proposal` | engagement |
| `transcription` | recording jobs (WP-6) | recording_job |
| `boardroom_coverage` | `analyze_coverage` (WP-7) | boardroom_session — **not** engagement, so two rooms can run at once |
| `casting` | `run_casting` (WP-10) | engagement |
| `email_send` | `send_proposal_email` (WP-12) | engagement — short-lived, prevents a double-click double-send |

```python
# backend/locks.py (NEW)
@contextmanager
def agent_lock(scope, ref_type, ref_id, engagement_id=None, ttl_minutes=15):
    _reap_stale(scope, ref_type, ref_id)      # deletes expired locks, logs an AgentEvent when it does
    lock = AgentLock(scope=scope, ref_type=ref_type, ref_id=ref_id, engagement_id=engagement_id,
                     expires_at=datetime.datetime.utcnow() + timedelta(minutes=ttl_minutes))
    db_session.add(lock)
    try:
        db_session.commit()                   # IntegrityError here means: already locked
    except IntegrityError:
        db_session.rollback()
        raise AlreadyProcessing(scope)
    try:
        yield lock
    finally:
        db_session.query(AgentLock).filter_by(id=lock.id).delete()
        db_session.commit()
```

Stale-lock reaping logs an `AgentEvent` with `trigger='stale_lock_reaped'` so it is visible rather than silent. `Engagement.is_processing` stays as a **derived** convenience value — `EXISTS(SELECT 1 FROM agent_locks WHERE engagement_id = ?)` — so the existing polling and spinner code in `EngagementDetail.jsx` keeps working untouched.

### 3.1 Acceptance criteria

- [x] Two different scopes on the same engagement run concurrently; the same scope twice returns 409.
- [x] A lock past `expires_at` is reaped on the next acquire and logs an `AgentEvent`.
- [x] `is_processing` is derived; existing spinner behaviour is unchanged. *(See the note below — it is synced, not computed.)*
- [x] Uniqueness is enforced by a database constraint, not application logic.
- [x] An exception inside the `with` block still releases the lock — test with a deliberately raised exception.

**Note on `is_processing`.** The spec describes it as a derived value
(`EXISTS(SELECT 1 FROM agent_locks …)`). It is implemented as a **synced**
column instead: `locks.py::_sync_is_processing()` writes it on every acquire and
release. A computed property would have been cleaner, but the upload route sets
the flag *before* submitting to the executor, and the frontend's first poll can
beat the worker thread to the database — a purely derived value would report
"idle" in that window and the spinner would flicker off. The lock rows remain
the only thing that actually enforces exclusion; the column is presentation.

Task functions are wrapped by `app.py::_with_lock(scope)` rather than each
opening its own `with` block, which also moves `db_session.remove()` to after
the lock release (releasing against an already-discarded thread-local session
would silently leak the lock until its TTL).

---

## WP-4 — Speech-to-text driver layer · 2.5–3 d

> *Requirement: "Implement both your Groq method and also a transcription-after-meeting method, and also a transcription-after-meeting method that uses local models."*

Three transcription paths, four engines, one interface. All of them register with WP-2's provider registry, so they are switchable in the UI from the moment they exist.

### 4.1 ⚠️ Correction: Ollama cannot do speech-to-text

Ollama serves text and multimodal *language* models. It has no ASR runtime and no `/audio/transcriptions` equivalent. The local speech path is **faster-whisper behind an OpenAI-compatible HTTP server**; Ollama's job is the *text* stage afterwards — cleanup, filler removal, name correction, speaker labelling, and cheap interim coverage checks in WP-7.

This is not a compromise. Self-hosted Whisper servers expose the same route shape as the hosted APIs (`POST /v1/audio/transcriptions`), so the local driver is the cloud driver with a different base URL and no auth header. The local-model requirement is fully met; it is just met by the tool that actually does the job.

### 4.2 The three paths

| Path | Capability | Engine options | Latency | Cost | Use it for |
|---|---|---|---|---|---|
| **Live dictation / boardroom** | `stt_live` | `groq_chunked`, `local_whisper_chunked`, `wispr_stream`, `browser_webspeech` | seconds behind the room | free tier or local | WP-5 dictation, WP-7 boardroom |
| **Post-meeting, cloud** | `stt_batch` | `groq_batch` | a 60-min recording in roughly 1–3 min | Groq free tier | The default: someone recorded on their phone, upload it after |
| **Post-meeting, local** | `stt_batch` | `local_whisper_batch` | a 60-min recording in roughly 10–25 min on CPU | zero, forever | Sensitive clients, no internet, backlog processing, free-tier exhaustion |

The post-meeting paths share **one pipeline** (WP-6) and differ only by driver. That is the whole reason for the abstraction: you can transcribe the same recording both ways and diff them in the Lab before deciding.

### 4.3 Module layout

```
backend/providers/stt/
├── base.py                 STTDriver, Segment, error hierarchy
├── groq_chunked.py         live: 15s chunks → Groq
├── groq_batch.py           post-meeting: ffmpeg split → Groq → stitch
├── local_whisper_chunked.py  live: 15s chunks → faster-whisper server
├── local_whisper_batch.py    post-meeting: ffmpeg split → faster-whisper server → stitch
├── wispr_stream.py         live: Wispr Flow WebSocket
├── wispr_batch.py          post-meeting: Wispr Flow REST
└── browser_webspeech.py    marker driver — transcription happens client-side
backend/providers/llm/      nim.py · ollama.py · groq_llm.py   (shared by polish, agents, coverage)
backend/audio.py            ffmpeg: normalise, probe duration, split with overlap
backend/stitch.py           overlap-aware segment joining
backend/polish.py           transcript cleanup via the `polish` capability
```

```python
# backend/providers/stt/base.py
@dataclass
class Segment:
    text: str
    start_ms: int | None = None
    end_ms: int | None = None
    confidence: float | None = None
    speaker: str | None = None
    provider: str = ""
    raw: dict | None = None

class STTDriver(Driver):
    supports_timestamps: bool = False
    supports_live: bool = False
    max_bytes: int = 25 * 1024 * 1024

    @abstractmethod
    def transcribe(self, audio: bytes, mime: str, *, hints: str = "",
                   language: str = "en") -> list[Segment]:
        """One piece of audio in, segments out. Pieces are produced by audio.split()."""
```

**`hints` matters more than it looks.** Both Groq and local Whisper accept a `prompt` field (roughly 224 tokens) that biases spelling. Feed it the **client name, producer name, talent names, and the engagement's key terms**, pulled from the database. Kenyan client and talent names are exactly the vocabulary a generic Whisper model mangles, and this one parameter is the cheapest accuracy win available anywhere in the system.

### 4.4 Groq drivers

Groq's speech-to-text is an OpenAI-compatible REST endpoint with `whisper-large-v3-turbo` as the fast model, supporting `verbose_json` responses with segment timestamps and a `prompt` field for spelling guidance. There is no streaming socket — "live" means chunked, and the chunk arithmetic in §4.6 exists because of that.

Free tier as of mid-2026: roughly **2,000 speech requests per day and 7,200 audio-seconds per hour**, with `429` responses carrying `x-ratelimit-*` headers that tell you where you stand before you hit the wall. Read those headers; do not discover limits by failing.

```python
# backend/providers/stt/groq_batch.py
@register
class GroqBatchSTT(STTDriver):
    info = DriverInfo(
        key="groq_batch", capability="stt_batch",
        label="Groq Whisper (cloud)",
        blurb="Fast cloud transcription. A one-hour recording in a couple of minutes.",
        is_local=False, requires_env=("GROQ_API_KEY",),
        cost_hint="Free tier: ~2,000 requests/day, 7,200 audio-seconds/hour",
        options_schema={"model": {"type": "string", "default": "whisper-large-v3-turbo",
                                  "enum": ["whisper-large-v3-turbo", "whisper-large-v3"]},
                        "temperature": {"type": "number", "default": 0.0}})
    supports_timestamps = True
    URL = "https://api.groq.com/openai/v1/audio/transcriptions"

    def transcribe(self, audio, mime, *, hints="", language="en"):
        data = {"model": self.options.get("model", Config.GROQ_STT_MODEL),
                "response_format": "verbose_json",
                "timestamp_granularities[]": "segment",
                "language": language,
                "temperature": str(self.options.get("temperature", 0.0))}
        if hints:
            data["prompt"] = hints[:900]                      # ~224 tokens
        r = requests.post(self.URL,
                          headers={"Authorization": f"Bearer {Config.GROQ_API_KEY}"},
                          files={"file": ("piece.mp3", audio, mime)},
                          data=data, timeout=180)
        _record_rate_headers(r.headers)                       # surfaced via /api/stt/status
        if r.status_code == 429:
            raise STTRateLimited(retry_after=float(r.headers.get("retry-after", 5)))
        r.raise_for_status()
        return [Segment(text=s["text"].strip(),
                        start_ms=int(s["start"] * 1000), end_ms=int(s["end"] * 1000),
                        provider=self.info.key, raw=s)
                for s in r.json().get("segments", []) if s.get("text", "").strip()]

    def health(self):
        if not Config.GROQ_API_KEY:
            return {"ok": False, "detail": "GROQ_API_KEY not set"}
        # cheap probe: 0.5s of silence
        ...
```

`groq_chunked` is the same class with `capability="stt_live"`, a smaller `max_bytes`, and `supports_live = True`. Keep them as separate registered drivers rather than one dual-purpose class — the Lab lists them independently and their option defaults genuinely differ.

**On `429`:** retry once after `retry_after`, then **fail over to the next available driver** (local, then browser) rather than dropping audio. In a live boardroom a dropped chunk is a hole in the record. Test this path; do not assume it.

### 4.5 Local Whisper drivers

Any OpenAI-compatible Whisper server works. Point `WHISPER_BASE_URL` at it:

```yaml
# docker-compose.yml
whisper:
  image: hwdsl2/whisper-server            # faster-whisper behind an OpenAI-compatible API
  ports: ["8001:8000"]
  environment: [ "WHISPER_MODEL=small" ]  # base/small on CPU; large-v3-turbo with a GPU
  volumes: [ "./.models/whisper:/models" ]
```

```python
@register
class LocalWhisperBatchSTT(STTDriver):
    info = DriverInfo(
        key="local_whisper_batch", capability="stt_batch",
        label="Local Whisper (on your hardware)",
        blurb="Free and fully private. No internet needed. Slower — minutes per meeting-hour on CPU.",
        is_local=True, requires_env=(),
        cost_hint="No marginal cost",
        options_schema={"model": {"type": "string", "default": "Systran/faster-whisper-small",
                                  "enum": ["Systran/faster-whisper-tiny", "Systran/faster-whisper-base",
                                           "Systran/faster-whisper-small", "Systran/faster-whisper-large-v3"]}})
    supports_timestamps = True

    def transcribe(self, audio, mime, *, hints="", language="en"):
        r = requests.post(f"{Config.WHISPER_BASE_URL}/audio/transcriptions",
                          files={"file": ("piece.wav", audio, mime)},
                          data={"model": self.options.get("model", Config.WHISPER_MODEL),
                                "response_format": "verbose_json", "language": language,
                                **({"prompt": hints[:900]} if hints else {})},
                          timeout=1800)                       # local large files are slow, not broken
        r.raise_for_status()
        return [...]                                          # identical parsing to Groq

    def health(self):
        try:
            r = requests.get(f"{Config.WHISPER_BASE_URL}/models", timeout=3)
            return {"ok": r.ok, "detail": "reachable" if r.ok else f"HTTP {r.status_code}"}
        except Exception as e:
            return {"ok": False, "detail": f"unreachable: {e.__class__.__name__}"}
    def available(self):
        return self.health()["ok"]
```

**Hardware reality, and be honest about it in the UI blurb:** on CPU-only hardware, `small` with int8 quantisation runs at roughly real time — usable for post-meeting work, marginal for a live room. `large-v3` does not keep up with a live room on CPU and will fall behind within minutes. There is also a cold-start cost: the first request after idle takes several seconds while weights load, so keep the container warm and show a "warming up" state rather than looking broken.

This is exactly why the **post-meeting local path is the strong one**: latency does not matter when the meeting is already over, the cost is zero, and the audio never leaves the building.

### 4.6 Chunking and stitching — the part that decides quality

**Live path (browser side).** `MediaRecorder` with a timeslice. Two traps:

1. **WebM headers.** Only the first blob from a `MediaRecorder` contains the EBML header; later blobs alone are undecodable. Keep the first blob in memory and prepend it to every subsequent chunk before upload. (Restarting the recorder each interval instead drops audio at every boundary.)
2. **Boundary word loss.** Whisper transcribes each chunk independently, so a word straddling a cut is mangled. Carry roughly 1.5 s of tail audio into the next chunk and de-duplicate server-side.

**Batch path (server side).** ffmpeg does the work:

```python
# backend/audio.py
def normalise(src: Path) -> Path:
    """Any container/codec → 16 kHz mono. Video in, audio out."""
    run(["ffmpeg", "-y", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000",
         "-c:a", "libmp3lame", "-b:a", "64k", str(dst)])

def split(src: Path, piece_seconds=600, overlap_seconds=2) -> list[Path]:
    """≤10-minute pieces with 2s overlap. At 64 kbps mono, 10 min ≈ 4.8 MB —
    comfortably inside the 25 MB per-request ceiling both engines share."""
```

**Stitching**, shared by both paths:

```python
# backend/stitch.py
def join(prev_text: str, next_text: str, max_overlap_words=40) -> str:
    """Find the longest suffix of prev that matches a prefix of next and drop the
    duplicate. difflib.SequenceMatcher — the same tool WP-8 uses for client-name
    matching, so no new dependency and one familiar failure mode instead of two."""
```

**Chunk sizes, derived from the free-tier budget rather than guessed:**

| Mode | Piece | Requests per audio-hour | Fits the Groq free tier? |
|---|---|---|---|
| Live dictation | 8 s | ~450 | Yes, comfortably |
| Live boardroom | 15 s | 240 | Yes — a 1-hour session is 240 requests and 3,600 audio-seconds, inside both the 2,000/day and 7,200/hour ceilings. About **eight one-hour sessions a day.** |
| Post-meeting batch | 600 s | 6 | Trivially. A 60-minute recording is six requests. |

The batch path is *dramatically* cheaper in request terms than the live path. Worth knowing when the free tier gets tight: if someone records the meeting anyway, post-meeting transcription costs a fortieth of the requests.

### 4.7 The polish stage — this is Ollama's job

```python
# backend/polish.py
def polish(text, names=(), driver_override=None):
    drv = providers.get('polish', override=driver_override)
    if drv.info.key == 'off' or not text.strip():
        return text, {"driver": "off"}
    prompt_tpl, prov = authoritative.resolve('polish_prompt')      # editable, A/B-able
    out = drv.complete(prompt_tpl.format(names=", ".join(names)) + "\n\n---\n" + text,
                       temperature=0.1)
    return out.strip(), {"driver": drv.info.key, "prompt": prov}
```

The default `polish_prompt` document:

```
You are cleaning a raw speech-to-text transcript from a client meeting.
Rules:
- Remove filler words and false starts. Do not remove content.
- Fix obvious mis-transcriptions of these known names: {names}
- Add sentence punctuation and paragraph breaks.
- Label speakers as Speaker 1 / Speaker 2 only where turn changes are unambiguous.
- NEVER add, infer, summarise, or invent anything that was not said.
Return only the cleaned transcript.
```

This is what closes the gap between raw Whisper output and a transcript a producer would have typed — at zero marginal cost on hardware GDF already owns.

**Polish runs once over the whole transcript, never per chunk.** Per-chunk polish destroys mid-sentence context, multiplies latency, and reads worse than the raw text. Raw segments are stored verbatim as evidence; the polished version is stored alongside as a derived field. Both are kept: the raw one is the record, the polished one is what the brief agent reads.

### 4.8 Endpoints

```
GET  /api/stt/status         current live/batch drivers, health, remaining free-tier budget, fallbacks
POST /api/stt/chunk          multipart audio (live path) → {segments:[...], provider, latency_ms}
POST /api/voice/token        Wispr Flow short-lived client token (only when a wispr driver is active)
```

All flagged with `@feature('voice')` and session-auth protected exactly like every other `/api/*` route. `GET /api/stt/status` is what lets the UI show an honest provider badge and a remaining-budget meter instead of failing mysteriously at request 2,001.

### 4.9 Wispr Flow driver (optional, keep the socket)

Wispr Flow is a hosted speech service that also cleans filler, fixes names from supplied context, and auto-formats — closer to "a producer's assistant typing what they said" than raw transcription. It offers a WebSocket path for streaming and a REST path (25 MB / 6 minutes per request, so long recordings need the same splitting as everything else), with two auth modes: server-side API key, or short-lived client tokens minted by your backend.

**Use API-key mode, server-brokered.** Client meeting audio is sensitive — names, budgets, internal decisions — and this app's existing pattern (session-cookie auth, no client-held secrets) already assumes secrets stay server-side.

Implement it as a driver for completeness so it can be evaluated in the Lab against Groq and local, but **do not make it the default**. It is a paid, cloud-only, usage-billed service with no built-in rate cap; if it wins the bake-off on quality, adopt it deliberately with a per-user daily cap in place.

### 4.10 Acceptance criteria

- [x] All seven drivers register and appear in `GET /api/providers`; unavailable ones report why.
- [x] Switching `stt_batch` changes which engine the next job uses, with no restart. *(Inherited from WP-2's resolution order; the Lab's per-column `override` uses the same path.)*
- [x] `stitch.join()` is unit-tested: overlapping pieces join with no repeated and no dropped words, including a repeated phrase inside the overlap. *(9 tests — one caught a real word-dropping bug, see below.)*
- [x] `audio.split()` produces pieces under 25 MB with the specified overlap. *(Measured on a 25-minute source: 3 pieces, 4.80 MB each, overlap at 598 s / 1196 s exactly as specified.)*
- [x] `polish` cleans a transcript without adding content; with `off` it is a pass-through. *(Verified live on Groq: filler removed, names cased correctly, every fact preserved.)*
- [x] Audio bytes are not persisted when `STT_KEEP_AUDIO=false` — asserted by tests that inspect the filesystem. *(Caught a real leak, see below.)*
- [x] `/api/stt/status` reports remaining free-tier budget parsed from response headers. *(Live: `x-ratelimit-remaining-requests: 1999` of 2000.)*
- [~] A `429` triggers one backoff retry then failover. **Implemented and structured for it (`transcribe.py::transcribe_piece`), but not exercised** — provoking a real 429 needs 2,000 requests. Unverified until it is fault-injected.
- [~] `hints` demonstrably improves a known-name transcription. **Implemented and wired** (`stt_hints.py`, fed from client/attendee/stakeholder/crew names), but no speech fixture exists in this environment to prove the accuracy gain — see the finding below, which is what testing it actually surfaced.
- [ ] A 15 s WebM chunk with a prepended header transcribes on both chunked drivers. **Deferred to WP-5**, which builds the browser-side `MediaRecorder` that produces those headers. The server endpoint (`POST /api/stt/chunk`) is done and verified with a WAV chunk.

### 4.11 Three findings from actually running this

**Whisper parrots the `hints` prompt back as transcription on non-speech audio.**
Confirmed against live Groq: six seconds of pure tone with hints
`"Aisha, Twiga Foods, Nairobi"` transcribed as exactly that string. Unguarded,
the single cheapest accuracy feature in the system would write names nobody said
into a client transcript — a direct breach of "never invent content in a
transcript." `whisper_api._looks_like_echoed_hints()` now drops output made
entirely of hint words, with regression tests. **Any future driver that accepts
a prompt needs the same guard.**

**Whisper emits a bare `"."` for silence.** Harmless in a batch transcript;
visibly broken in dictation, where every silent chunk would append punctuation.
Content-free segments are now dropped.

**The Lab leaked derived audio.** Passing `keep_audio=True` per driver (so every
column reads the same file) meant only the *original* was deleted, leaving ~14 MB
of normalised and split pieces on disk after each bake-off — violating the
retention criterion. Fixed by `transcribe.PreparedAudio`, which normalises and
splits **once** per run and owns cleanup of everything derived. Side benefit:
ffmpeg no longer re-runs per driver.

### 4.12 Scope notes

`stitch.find_overlap()` matches **exact token runs before fuzzy ones**. The
obvious single-pass implementation lets a near-miss at a longer overlap outrank
an exact match at a shorter one and swallow a real word — joining
"…for your time today" with "…for your time today lets begin" scored 0.897 at
size 9 (over threshold) while the true seam was the exact match at size 8,
silently dropping "lets". Two passes, exact first.

`local_whisper_*` overrides `available()` with a live probe rather than an env
check, since "is the server up" is the only meaningful availability question for
a self-hosted engine. It is timeboxed to 3 s because `registry.get()` calls it
on the resolution path.

The Wispr drivers are written against vendor docs and **not verified against a
live account** — no key exists in this environment. Response parsing is
provisional; check it before relying on them. They are deliberately not a
default: paid, cloud-only, usage-billed with no built-in cap.

---

## WP-5 — Voice dictation in `TranscriptDropArea` · 0.5–1 d

The insertion point is precise. `TranscriptDropArea` is a shared component in `frontend/src/pages/EngagementDetail.jsx`, used for both the Brief-stage and Proposal-stage transcript uploads. It already renders a drop zone, a `<textarea rows={4}>` bound to `transcript` / `setTranscript`, and a "Generate {stage.docType}" button gated on `!transcript.trim()`. A microphone control sits naturally between the drop zone and the textarea, writing into the **same `setTranscript` setter** the file-drop and paste paths already use — meaning **zero backend changes beyond WP-4**.

```jsx
// frontend/src/components/MicCaptureButton.jsx (NEW)
<MicCaptureButton
  scope={{ engagementId }}
  onText={(text) => setTranscript(prev => (prev ? prev + " " : "") + text)}
  onError={setError}
/>
```

Responsibilities, in order of importance:

1. **Permission handling** — request `getUserMedia` on click, never on mount. A denial produces a specific, actionable message, not a silent no-op.
2. **Rolling 8 s chunk upload** to `/api/stt/chunk`, appending returned text.
3. **Three-tier fallback**, visible as a small `ProviderBadge`: selected driver → next available server driver → browser `SpeechRecognition`. The browser tier is free, offline-capable, and the only one that survives a dead connection. Keep it even after choosing a favourite.
4. **Live state** — recording indicator, elapsed time, and an input level meter so a muted mic is obvious immediately rather than after ten silent minutes. Stop flushes the trailing partial chunk.
5. **Accessibility in the first commit**, not retrofitted in WP-13: `aria-label`, `aria-pressed` for recording state, and an `aria-live="polite"` region announcing "Recording started" / "Recording stopped, 240 words added".
6. **A driver switcher in the overflow menu** when `FEATURE_LAB` is on — try a different engine on the next dictation without leaving the page.

### 5.1 Acceptance criteria

- [ ] Dictating appends to the same `transcript` state that file-drop and paste use; the generate button ungates identically.
- [ ] Denying mic permission produces a specific message naming the fix.
- [ ] Killing the network mid-dictation degrades to browser Web Speech and says so in the badge.
- [ ] Stopping flushes the trailing partial chunk — no lost final sentence.
- [ ] Keyboard-operable end to end; a screen reader announces start and stop.

---

## WP-6 — Recording Studio: post-meeting transcription · 2.5–3 d

> *Requirement: "a transcription-after-meeting method, and also a transcription-after-meeting method that uses local models."*

Someone recorded the meeting on their phone, or in Zoom, or on a handheld. They upload the file afterwards and get a transcript — through **either** the cloud engine (fast) **or** the local engine (free and private), switchable per job.

### 6.1 Flow

```
/recordings  →  drop an audio or video file (mp3, m4a, wav, mp4, mov, webm)
                 │
                 ├─ engine: [ Groq (cloud, ~2 min) ▾ ]  ← defaults to the runtime setting,
                 │                                          overridable per job
                 ├─ attach to: [ engagement ▾ ] (optional — can decide later)
                 └─ [ Transcribe ]  ·  [ Transcribe with both and compare ]
                 ▼
        RecordingJob (queued) ── executor, semaphore(1) ── AgentLock('transcription')
                 │
                 ├─ ffmpeg: probe duration, normalise to 16 kHz mono, split into ≤10 min pieces
                 ├─ for each piece: driver.transcribe(hints=known names)  [progress: 3/7 pieces]
                 ├─ stitch with overlap de-duplication
                 └─ polish() once over the whole transcript
                 ▼
        Review screen: raw ⇄ polished toggle, inline edit, timestamps, ProviderBadge
                 │
                 └─ [ Attach to engagement ]  →  existing POST /api/engagements/<id>/transcripts
                                                  → brief or proposal generates exactly as today
```

The final hop is the important architectural decision: **the Recording Studio does not get its own brief agent.** It produces a transcript and posts it to the endpoint that already exists, so an uploaded-recording brief and a Fathom brief are the same object from the same code path. One pipeline, four inlets: manual paste, Fathom webhook, Recording Studio, Boardroom.

### 6.2 Data model

```python
class RecordingJob(Base):
    __tablename__ = 'recording_jobs'
    id             = Column(Integer, primary_key=True)
    engagement_id  = Column(Integer, ForeignKey('engagements.id'), nullable=True)
    client_id      = Column(Integer, ForeignKey('clients.id'), nullable=True)
    title          = Column(String(200))
    source_path    = Column(String(400))          # under UPLOAD_DIR; deleted per retention policy
    source_name    = Column(String(260))
    source_bytes   = Column(Integer)
    duration_sec   = Column(Integer)
    mime           = Column(String(60))
    driver_key     = Column(String(40), nullable=False)   # frozen at submit
    driver_options = Column(Text)
    polish_driver  = Column(String(40))
    language       = Column(String(10), default='en')
    status         = Column(String(20), default='queued')
    # queued | normalising | transcribing | polishing | ready | attached | failed | cancelled
    pieces_total   = Column(Integer, default=0)
    pieces_done    = Column(Integer, default=0)
    progress_pct   = Column(Integer, default=0)
    raw_text       = Column(Text)
    polished_text  = Column(Text)
    edited_text    = Column(Text)                 # human edits, if any — what actually gets attached
    latency_ms     = Column(Integer)
    error          = Column(Text)
    attached_transcript_id = Column(Integer, ForeignKey('transcripts.id'), nullable=True)
    comparison_run_id      = Column(Integer, ForeignKey('comparison_runs.id'), nullable=True)
    created_by     = Column(Integer, ForeignKey('users.id'))
    created_at     = Column(DateTime, default=datetime.datetime.utcnow)
    completed_at   = Column(DateTime)

class RecordingSegment(Base):
    __tablename__ = 'recording_segments'
    id         = Column(Integer, primary_key=True)
    job_id     = Column(Integer, ForeignKey('recording_jobs.id'), index=True)
    seq        = Column(Integer, nullable=False)
    text       = Column(Text, nullable=False)
    start_ms   = Column(Integer); end_ms = Column(Integer)
    speaker    = Column(String(40)); confidence = Column(Float)
    # UniqueConstraint('job_id','seq')
```

Storing segments rather than only the joined text buys click-to-timestamp in the review UI and makes re-stitching possible without re-transcribing.

### 6.3 The worker

```python
# backend/recordings.py (NEW)
_TRANSCRIBE_SEMAPHORE = threading.Semaphore(1)

def run_recording_job(job_id: int):
    """Runs on the shared ThreadPoolExecutor. The semaphore ensures at most ONE
    transcription job at a time, so a 90-minute upload cannot starve the brief and
    proposal agents that share the same three worker threads."""
    with _TRANSCRIBE_SEMAPHORE, agent_lock('transcription', 'recording_job', job_id, ttl_minutes=120):
        job = db_session.query(RecordingJob).get(job_id)
        try:
            _set(job, status='normalising')
            wav = audio.normalise(Path(job.source_path))
            job.duration_sec = audio.duration(wav)
            pieces = audio.split(wav, piece_seconds=600, overlap_seconds=2)
            _set(job, status='transcribing', pieces_total=len(pieces))

            drv = providers.get('stt_batch', override=job.driver_key,
                                options=json.loads(job.driver_options or '{}'))
            hints = build_hints(job)                       # client, talent, engagement vocabulary
            all_segments, offset_ms = [], 0
            for i, piece in enumerate(pieces):
                segs = _with_retry(drv.transcribe, piece.read_bytes(), "audio/mpeg",
                                   hints=hints, language=job.language)
                all_segments = stitch.merge(all_segments, segs, offset_ms)
                offset_ms += audio.duration_ms(piece) - OVERLAP_MS
                _set(job, pieces_done=i + 1, progress_pct=int((i + 1) / len(pieces) * 90))

            job.raw_text = " ".join(s.text for s in all_segments)
            _persist_segments(job.id, all_segments)

            _set(job, status='polishing', progress_pct=92)
            job.polished_text, _ = polish(job.raw_text, names=hints_list(job))
            _set(job, status='ready', progress_pct=100, completed_at=utcnow())
        except Exception as e:
            _set(job, status='failed', error=f"{e.__class__.__name__}: {e}")
            log.exception("recording job %s failed", job_id)
        finally:
            if not Config.STT_KEEP_AUDIO:
                _cleanup_audio(job)                        # source + normalised + pieces
            db_session.remove()
```

Five points that matter:

1. **The semaphore.** One transcription at a time. Without it, three concurrent uploads occupy all three executor threads and every brief in the system stops generating. This is a one-line guard against a very annoying outage.
2. **Per-piece retry with backoff**, then failover to the next available driver for the *remaining* pieces, with the switch recorded on the job. A partially cloud, partially local transcript is far better than a failed one.
3. **Progress is real**, computed from pieces done — not a fake animation. A 90-minute local transcription takes 20+ minutes and the user must be able to see it advancing or they will assume it hung and upload again.
4. **Resumability.** Because segments are persisted per piece, a failed job can retry from `pieces_done` rather than from zero. Worth the extra half hour.
5. **Audio deleted on completion** unless `STT_KEEP_AUDIO=true`. Text is the artefact; audio is a liability.

### 6.4 Endpoints

```
POST /api/recordings                        multipart upload + {driver_key?, options?, engagement_id?, title, language}
POST /api/recordings/compare                multipart upload + drivers[] → runs a ComparisonRun (WP-2) instead
GET  /api/recordings                        ?status=&engagement_id=
GET  /api/recordings/<id>                   job + progress + text + segments
PATCH /api/recordings/<id>                  save edited_text, title, engagement_id
POST /api/recordings/<id>/retry             re-run, optionally with a different driver
POST /api/recordings/<id>/attach            → creates the Transcript, fires the existing pipeline
POST /api/recordings/<id>/cancel
GET  /api/recordings/<id>/export            txt | md | srt
DELETE /api/recordings/<id>
```

Upload limits: reject over `MAX_UPLOAD_MB` (default 500) with a clear message, and stream to disk rather than buffering in memory — a single worker holding a 400 MB upload in RAM is how the box falls over.

### 6.5 Frontend

```
frontend/src/pages/Recordings.jsx           (NEW)  list + upload
frontend/src/pages/RecordingDetail.jsx      (NEW)  progress, review, edit, attach
frontend/src/components/UploadDropzone.jsx  (NEW)  drag-drop, duration probe, size guard
frontend/src/components/TranscriptReview.jsx(NEW)  raw ⇄ polished toggle, inline edit, timestamps
```

Details that decide whether it gets used:

- **The engine picker is right there on the upload form**, defaulted to the runtime setting, with each option's blurb, cost hint, and an estimated completion time computed from the file's duration: *"Groq (cloud) — about 2 minutes"* versus *"Local Whisper — about 22 minutes, free, nothing leaves this machine."* That estimate is the single most useful thing on the page.
- **"Transcribe with both and compare"** runs a WP-2 `ComparisonRun` and lands you in the diff view. This is the feature that lets you actually decide, on your own audio, in one click.
- **Progress with piece counts**, not a spinner: *"transcribing — piece 4 of 9."*
- **Raw ⇄ polished toggle** so you can see what the cleanup stage did, and edit either.
- **`ProviderBadge`** on every job: which engine, which model, how long it took.
- **Attach is deliberate.** The producer reviews before it feeds the brief agent.

### 6.6 Acceptance criteria

- [ ] A 60-minute MP3 transcribes end to end on `groq_batch` and on `local_whisper_batch`, producing comparable text.
- [ ] A video file (mp4/mov) has its audio extracted and transcribes correctly.
- [ ] Piece boundaries show no duplicated or dropped words — verified on a recording with continuous speech across a boundary.
- [ ] Three simultaneous uploads do not block brief generation: the semaphore serialises them and the other two show `queued`.
- [ ] Progress advances with piece completion; a failed piece retries and, on repeated failure, fails over to another driver with the switch recorded.
- [ ] "Transcribe with both and compare" produces a `ComparisonRun` with a working diff.
- [ ] Editing the transcript and attaching sends the **edited** text into the existing endpoint, and a brief generates from it identically to a Fathom-sourced one.
- [ ] Source audio is deleted on completion when `STT_KEEP_AUDIO=false`.
- [ ] An over-limit upload is rejected with a clear message before any file is written.
- [ ] With `FEATURE_RECORDINGS=false`, all recording routes return 404.

---

## WP-7 — Boardroom live transcription + Coverage Agent · 3.5–4 d

> *Requirement: "Add a button to lead to a live boardroom transcription page which mentions anything not talked about at the end of the meeting (authoritative data with boardroom instructions), then leads to brief generation."*

This is the highest-value feature in the blueprint, because it attacks the real failure mode of agency intake: a brief is only as good as the meeting, and meetings routinely end with two critical things never asked. Fathom and the Recording Studio capture what **was** said. The Boardroom catches what **wasn't**.

### 7.1 Flow

```
EngagementDetail  →  [ Start Boardroom Session ]
                              │
                              ▼
  /boardroom/:sessionId   ── LIVE ──────────────────────────────────────┐
                              │                                          │
   mic → 15s chunks → POST /api/boardroom/sessions/:id/chunk             │
                              │                                          │
                     TranscriptSegment rows                              │
                              │                                          │
       every ~90s or +1200 new words (server-debounced):                 │
       analyze_coverage(interim)  ← boardroom_protocol (WP-1)            │
       runs on the `coverage_llm` driver — cheap/local by default        │
                              │                                          │
       agenda checklist ticks live; unasked items stay amber ────────────┘
                              │
                       [ End Meeting ]
                              │
       analyze_coverage(final) — full model, whole transcript, every item
                              │
       ╔════════════════════════════════════════════════════════╗
       ║  NOT COVERED IN THIS MEETING                            ║
       ║  · Confirmed budget range                               ║
       ║  · Decision-maker & sign-off path                       ║
       ║  · Usage rights / territory                             ║
       ║  [ closing script, ready to read aloud ]                ║
       ╚════════════════════════════════════════════════════════╝
                              │
        [ Generate Production Brief ] → existing POST /api/engagements/:id/transcripts
                              ▼
                     Brief appears exactly as it does today
```

### 7.2 Data model

```python
class BoardroomSession(Base):
    __tablename__ = 'boardroom_sessions'
    id                = Column(Integer, primary_key=True)
    engagement_id     = Column(Integer, ForeignKey('engagements.id'), nullable=True)  # nullable: new-business pitch
    client_id         = Column(Integer, ForeignKey('clients.id'), nullable=True)
    title             = Column(String(200))
    meeting_kind      = Column(String(40), default='intake')   # intake | review | internal | pitch
    protocol_scope    = Column(String(20))      # which scope won, from resolve()
    protocol_version  = Column(Integer)         # FROZEN at session start — see §7.6
    status            = Column(String(20), default='live')     # live | ended | promoted | discarded
    stt_driver        = Column(String(40))
    coverage_driver   = Column(String(40))
    language          = Column(String(10), default='en')
    consent_ack_by    = Column(Integer, ForeignKey('users.id'))
    consent_ack_at    = Column(DateTime)
    planned_minutes   = Column(Integer)          # drives the T-5 nudge
    started_at        = Column(DateTime, default=datetime.datetime.utcnow)
    ended_at          = Column(DateTime)
    audio_seconds     = Column(Integer, default=0)
    raw_transcript    = Column(Text)             # assembled verbatim — the evidence
    polished_transcript = Column(Text)           # derived — what the brief agent reads
    promoted_transcript_id = Column(Integer, ForeignKey('transcripts.id'), nullable=True)
    created_by        = Column(Integer, ForeignKey('users.id'))

class TranscriptSegment(Base):
    __tablename__ = 'transcript_segments'
    id            = Column(Integer, primary_key=True)
    session_id    = Column(Integer, ForeignKey('boardroom_sessions.id'), index=True)
    seq           = Column(Integer, nullable=False)     # monotonic per session; the frontend polls on it
    text          = Column(Text, nullable=False)
    speaker_label = Column(String(40))
    source        = Column(String(20), default='stt')   # stt | typed | browser_stt
    started_ms    = Column(Integer); ended_ms = Column(Integer)
    confidence    = Column(Float); provider = Column(String(40))
    created_at    = Column(DateTime, default=datetime.datetime.utcnow)
    # UniqueConstraint('session_id','seq')

class CoverageCheck(Base):
    __tablename__ = 'coverage_checks'
    id               = Column(Integer, primary_key=True)
    session_id       = Column(Integer, ForeignKey('boardroom_sessions.id'), index=True)
    item_key         = Column(String(60), nullable=False)   # from the protocol JSON, not a table
    status           = Column(String(12), nullable=False)   # covered | partial | missing | unknown
    evidence         = Column(Text)         # the transcript span that satisfied it
    evidence_seq     = Column(Integer)      # which segment — enables click-to-scroll
    confidence       = Column(Float)
    suggested_prompt = Column(Text)         # the question to ask if still missing
    is_final         = Column(Boolean, default=False)
    driver_key       = Column(String(40))
    checked_at       = Column(DateTime, default=datetime.datetime.utcnow)
```

**Agenda items live in the authoritative protocol document, not in a table.** Editing the agenda is a WP-1 document edit with version history and no migration. That is the entire reason WP-1 comes first.

### 7.3 The `boardroom_protocol` document

```json
{
  "name": "GDF Client Intake Boardroom Protocol",
  "meeting_kind": "intake",
  "items": [
    { "key": "budget_range", "label": "Confirmed budget range", "required": true,
      "why": "Proposal pricing cannot be scoped without it; the Rate Card needs a band to fit.",
      "accept_when": "A figure or range with a currency, or an explicit statement that budget is not yet set.",
      "ask": "What budget range are we working within for this?" },
    { "key": "decision_maker", "label": "Decision-maker & sign-off path", "required": true,
      "why": "Proposals sent to the wrong person stall for weeks.",
      "accept_when": "A named person or role who signs off, and how approval reaches them.",
      "ask": "Who signs off on this, and what does that approval path look like?" },
    { "key": "deliverables", "label": "Deliverable list & formats", "required": true,
      "why": "Scope disputes start here.", "accept_when": "Each deliverable named with a format or spec.",
      "ask": "What exactly are we delivering, and in what formats?" },
    { "key": "timeline", "label": "Key dates and hard deadlines", "required": true,
      "why": "Drives casting availability and production scheduling.",
      "accept_when": "At least one dated milestone or a hard deadline.",
      "ask": "What are the hard dates we're working back from?" },
    { "key": "usage_rights", "label": "Usage rights, territory & duration", "required": true,
      "why": "The single most common source of post-delivery disputes.",
      "accept_when": "Media, territory and licence duration are all stated.",
      "ask": "Where will this run, in which markets, and for how long?" },
    { "key": "talent_needs", "label": "Talent / casting requirements", "required": false,
      "why": "Feeds the Casting Agent directly (WP-10).",
      "accept_when": "Roles, count, or a described profile.", "ask": "Who do we need on camera or on the crew?" },
    { "key": "brand_assets", "label": "Brand guidelines & asset availability", "required": false,
      "why": "Avoids a week lost waiting for logos and fonts.",
      "accept_when": "Confirmation that guidelines and assets exist and who supplies them.",
      "ask": "Do you have brand guidelines and assets ready, and who sends them over?" },
    { "key": "success_metric", "label": "How the client will judge success", "required": false,
      "why": "Sharpens the proposal's framing.", "accept_when": "A stated outcome or measure.",
      "ask": "How will you know this worked?" }
  ],
  "interim_check_seconds": 90,
  "interim_check_min_new_words": 1200,
  "closing_script": "Before we close — a few things we haven't covered yet: {missing}. Can we take those now, or should I follow up by email today?"
}
```

Different `meeting_kind` values resolve to different protocol documents. The **client-scoped override** is the killer use case: a client who always forgets to mention their legal review cycle gets an extra required item, forever, set once by the Account Manager.

### 7.4 The Coverage Agent

```python
# backend/agents.py
def analyze_coverage(session_id: int, final: bool = False) -> None:
    with agent_lock('boardroom_coverage', 'boardroom_session', session_id):
        session = db_session.query(BoardroomSession).get(session_id)
        protocol, prov = authoritative.resolve_version(
            'boardroom_protocol', session.protocol_scope, session.protocol_version)
        prompt_tpl, prompt_prov = authoritative.resolve('coverage_prompt')

        if final:
            transcript = _assemble(session_id)                       # everything
            items = protocol['items']                                # re-check all, authoritatively
            drv = providers.get('agent_llm')                         # the good model
        else:
            transcript = _assemble(session_id, since_seq=_last_checked_seq(session_id))
            settled = {c.item_key for c in _latest_checks(session_id) if c.status == 'covered'}
            items = [i for i in protocol['items'] if i['key'] not in settled]
            drv = providers.get('coverage_llm')                      # the cheap/local one
            if not items or not _debounce_ok(session, protocol):
                return

        raw = drv.complete(prompt_tpl.format(items=json.dumps(items), transcript=transcript,
                                             final=final), temperature=0.0)
        checks = _parse_coverage_json(raw)      # strict; one repair retry; else 'unknown'
        _persist_checks(session_id, checks, is_final=final, driver_key=drv.info.key)
        db_session.add(AgentEvent(
            engagement_id=session.engagement_id, agent='Coverage Agent',
            trigger='boardroom_coverage_final' if final else 'boardroom_coverage_interim',
            reasoning_summary=_summarise(checks),
            action=f"{sum(1 for c in checks if c['status'] == 'missing')} item(s) still uncovered",
            authoritative_refs=json.dumps([prov, prompt_prov]), tokens_used=drv.last_tokens))
        db_session.commit()
```

Five design rules, each earned:

1. **Interim checks are cheap and incremental; the final check is expensive and complete.** Interim runs the `coverage_llm` driver — local Ollama by default — over *new text only*, evaluating *only unsettled items*. The final run puts the full model over the whole transcript and every item, and overwrites the interim results. Interim output is a live hint; final output is the record. This is precisely the split the provider registry exists to make easy.
2. **`covered` is sticky within a session; `missing` is not.** An item satisfied at minute 5 does not become uncovered at minute 40. The final pass re-derives everything anyway, so stickiness is a pure cost optimisation.
3. **Structured output, defensively parsed.** Strict JSON array; on parse failure retry once with a repair prompt containing the malformed output; on second failure mark items `unknown` and log it. **A coverage check must never crash a live meeting**, and it must never silently report `covered` when it failed.
4. **Evidence is mandatory for `covered`.** The model must return the transcript span that satisfied the item. No evidence → downgrade to `partial`. This is the only defence against a model agreeing with itself, and it makes the UI clickable — jump to the moment it was discussed.
5. **Debounce server-side.** The interim endpoint is safe to call repeatedly; the server enforces `interim_check_seconds` and `interim_check_min_new_words` from the protocol and returns the last result when called too soon. Never trust a browser tab to rate-limit your model spend.

### 7.5 API

```
POST /api/boardroom/sessions               {engagement_id?, client_id?, title, meeting_kind, planned_minutes, consent_ack}
GET  /api/boardroom/sessions               ?status=&engagement_id=
GET  /api/boardroom/sessions/<id>          ?since_seq=   segments, coverage, status, budget meter
POST /api/boardroom/sessions/<id>/chunk    multipart audio → STT → segments
POST /api/boardroom/sessions/<id>/segments {text, speaker_label?, source}  typed notes / browser-STT text
POST /api/boardroom/sessions/<id>/coverage force an interim check (server-debounced)
POST /api/boardroom/sessions/<id>/end      final coverage + assemble + polish → coverage report
POST /api/boardroom/sessions/<id>/promote  → creates the Transcript and fires the existing brief pipeline
GET  /api/boardroom/sessions/<id>/export   md | pdf (reuses WeasyPrint)
POST /api/boardroom/sessions/<id>/discard  soft-delete, keeps the audit row
```

**Transport: polling, not SSE or WebSockets.** `GET /api/boardroom/sessions/<id>?since_seq=N` every 2 s matches the pattern `EngagementDetail.jsx` already uses, needs no new server machinery, and — decisively — does not hold a gunicorn thread open per attendee. With one worker and eight threads, three concurrent SSE sessions would consume most of the pool. Revisit only when the room count justifies it.

### 7.6 Freeze the protocol version at session start

`BoardroomSession` stores `protocol_scope` and `protocol_version` at creation, and every coverage check resolves *that exact version*. If someone edits the protocol mid-meeting, the live session is unaffected. Without this, the agenda could change under the producer's feet and the coverage report would be judged against a standard that did not exist when the meeting started. The UI shows the protocol read-only during a live session, with an "edit for next time" link into the WP-1 editor.

### 7.7 Frontend

```
frontend/src/pages/Boardroom.jsx                  (NEW)  the live page
frontend/src/components/LiveTranscript.jsx        (NEW)  auto-scroll with pause-on-scroll-up, speaker grouping
frontend/src/components/AgendaChecklist.jsx       (NEW)  live status pills + "Ask this" prompt buttons
frontend/src/components/CoverageReport.jsx        (NEW)  end-of-meeting modal + closing script
frontend/src/components/StartBoardroomButton.jsx  (NEW)  the entry point on EngagementDetail
```

Layout: transcript left (~60%), agenda checklist right (~40%), recording controls fixed at the bottom.

Details that decide whether producers actually use it:

- **The checklist is the product, not the transcript.** Amber = not yet raised, green = covered with evidence, half-green = partial. A producer glancing at the right rail mid-meeting should be able to steer the conversation.
- **"Ask this" buttons.** Each uncovered item shows its `ask` prompt with a copy button — the producer reads it aloud. This turns a passive checklist into an active meeting aid and is a two-hour build.
- **Five-minutes-remaining nudge.** When `planned_minutes` is set, at T-5 surface a toast listing still-missing required items. This is where the feature earns its keep.
- **Typed fallback always available.** A text input posting to `/segments` so the producer can capture something the mic missed — or run the entire session with no audio at all. The coverage agent does not care where text came from.
- **Manual promote, never automatic.** The producer reviews the polished transcript before "Generate Production Brief". Human approval gates on anything upstream of a client proposal.
- **`ProviderBadge`** showing which STT and coverage drivers this session is using, with a switcher when `FEATURE_LAB` is on.
- **`aria-live="polite"` on the missing-items region and status changes.** Built now, not in WP-13. The scrolling transcript itself is `aria-live="off"` with a "jump to latest" control — a continuously updating live region is unusable with a screen reader.

### 7.8 Privacy, consent and storage

- **Audio is not persisted** unless `STT_KEEP_AUDIO=true`. Default false.
- **Explicit consent acknowledgement** before the first chunk: a modal the producer confirms ("everyone present has been told this meeting is being transcribed"), stored as `consent_ack_by` / `consent_ack_at` and logged as an `AgentEvent`. Kenya's Data Protection Act (2019) makes lawful basis for processing personal data a real obligation, and client meeting audio contains plenty of it. Five minutes to build, very hard to retrofit credibly. Have someone with legal standing at GDF sign off on the wording.
- **Write batching.** Segments are written once per chunk (every 15 s), not per word. At one write per 15 s per session, SQLite's single-writer constraint is a non-issue for a handful of rooms — but this is the first feature with sustained write traffic, which is why §WP-14 treats Postgres as the next real step rather than a hypothetical one.

### 7.9 Effort

| Task | Time |
|---|---|
| Models, migration, `boardroom_protocol` + `coverage_prompt` seed documents | 4 h |
| Session CRUD, chunk ingest, segment assembly, polling endpoint | 6 h |
| `analyze_coverage` interim + final, prompt, strict JSON parsing, repair retry | 8 h |
| `Boardroom.jsx` shell, `LiveTranscript`, recording controls, provider/budget badges | 8 h |
| `AgendaChecklist` with live pills, "Ask this", T-5 nudge | 5 h |
| `CoverageReport` modal, closing script, export | 4 h |
| Promote → existing transcript pipeline + `StartBoardroomButton` | 3 h |
| Consent modal, discard, reconnect/error handling | 4 h |
| **Total** | **~3.5–4 days** |

### 7.10 Acceptance criteria

- [ ] A session runs 30 minutes on 15 s chunks with no gaps, no duplicated words at boundaries, and a monotonic `seq`.
- [ ] Killing the network for 60 s and restoring resumes without losing captured segments; the UI shows a reconnecting state.
- [ ] Interim checks respect the protocol's debounce; hammering `/coverage` produces no extra model calls.
- [ ] The final check re-evaluates every item and supersedes all interim results.
- [ ] `covered` without evidence is impossible — enforced in the parser, tested with a fabricated model response.
- [ ] A malformed model response yields `unknown` plus a logged `AgentEvent` — never a 500, never a false `covered`.
- [ ] Editing the protocol mid-session does not change the live session's agenda; the next session picks up the new version.
- [ ] Switching the `coverage_llm` driver changes which model runs interim checks, verified in `AgentEvent`.
- [ ] "Generate Production Brief" produces a brief structurally indistinguishable from a Fathom-sourced one, via the same endpoint.
- [ ] With `FEATURE_BOARDROOM=false`, all boardroom routes return 404 and no boardroom UI is reachable.
- [ ] No audio files remain on disk after a session when `STT_KEEP_AUDIO=false`.
- [ ] Keyboard-operable; the missing-items region is announced by a screen reader; the transcript region is not a shouting live region.

---

## WP-8 — Fathom zero-click matching · 0.5 d

⚠️ **Correction to a common assumption:** *"no human clicks Generate Proposal"* is **already true today** for the common case. `fathom_webhook()` calls `_attach_inbound(inbound, eng, auto=True)` — creating the `Transcript` row and submitting the agent job — the instant a meeting title unambiguously names one known client. By the time anyone opens the app, the brief or proposal is already generated. **The gap is not the automation; it is the narrowness of the match rule that decides whether automation fires.**

`_auto_match_client()` requires the client's exact name (3+ characters, case-insensitive substring) in the Fathom meeting title. *"Safaricom // Q3 Check-in"* matches. *"Q3 Check-in w/ Waweru"* — the client contact's name, not the client's — does not, and falls back to the manual Inbox attach.

### 8.1 Enhancement A — engagement tag (highest confidence, recommended default)

Producers add `[ENG-0042]` to the calendar invite title. Checked **before** name matching: it resolves straight to a specific engagement rather than a client, so it also disambiguates a client with more than one open engagement — something fuzzy name matching alone cannot solve, since `_open_engagement_for()` just grabs the most recent open one today.

```python
# backend/app.py — inside fathom_webhook(), before the fuzzy-match fallback
ENG_TAG = re.compile(r"\[ENG-(\d+)\]")

m = ENG_TAG.search(parsed['title'] or "")
if m:
    eng = db_session.query(Engagement).get(int(m.group(1)))
    if eng and eng.status in DISPATCHABLE_STATUSES and not _is_locked(eng.id):
        auto_processed = _attach_inbound(inbound, eng, user_id=None, auto=True)
```

### 8.2 Enhancement B — fuzzy name matching

```python
# backend/app.py — replaces the exact-substring check in _auto_match_client()
from difflib import SequenceMatcher

def _auto_match_client(title):
    if not title:
        return None
    cfg, _ = authoritative.resolve('fathom_matching')     # {"fuzzy_threshold":0.75,"min_client_name_length":3}
    scored = []
    for c in db_session.query(Client).all():
        if not c.name or len(c.name) < cfg['min_client_name_length']:
            continue
        ratio = SequenceMatcher(None, title.lower(), c.name.lower()).ratio()
        if ratio > cfg['fuzzy_threshold']:
            scored.append((ratio, c))
    # Zero or multiple matches → None → pending in the Inbox, human decides.
    # Fuzziness must NEVER turn an ambiguous case into a confident auto-attach.
    return scored[0][1] if len(scored) == 1 else None
```

The threshold lives in authoritative data because it is exactly the kind of number that gets tuned three times in the first month by someone who should not need a deploy to do it. The `client_match` capability (WP-2) lets you switch between `exact`, `fuzzy_difflib`, and `eng_tag_then_fuzzy` from the UI while you calibrate.

### 8.3 Confidence rule

Only auto-process on an `[ENG-XXXX]` tag match (deterministic) or a **single** fuzzy match above threshold. Two or more candidates above threshold, or zero, still fall through to the Inbox as pending. The human-in-the-loop path stays as the safety net for genuine ambiguity; it just stops being the default path. Attaching a transcript to the *wrong client* is the one failure mode worse than a human clicking Attach.

### 8.4 Producer-facing affordance

Show the `[ENG-0042]` tag prominently in the engagement view with a copy button and one line of explanation: *"Paste this into the calendar invite title and the transcript attaches itself."*

### 8.5 Acceptance criteria

- [x] A title containing `[ENG-42]` attaches to engagement 42 regardless of client name.
- [x] A title fuzzily matching exactly one client above threshold auto-attaches; two matches or zero go to the Inbox as pending.
- [x] Changing `fuzzy_threshold` in authoritative data changes behaviour with no deploy.
- [x] Switching the `client_match` driver to `exact` restores the previous behaviour exactly.
- [x] The engagement view shows the tag with a copy button.
- [x] Existing exact-match auto-attach behaviour is unchanged for titles that already worked.

### 8.6 Two implementation notes

**Exact substring is still tried first, at every mode.** The spec's
`_auto_match_client()` replaces the substring check with a pure ratio test. Done
literally, that *regresses* the cases that already worked: `SequenceMatcher`
compares whole strings, so a long title (`"Safaricom // Q3 Planning Session With
The Wider Team"`) scores well under 0.75 against `"Safaricom"` even though the
name is sitting right there. The implementation therefore tries exact substring
first, and only falls through to fuzzy when that yields nothing — and the fuzzy
pass scores each client name against the best-matching *window* of the title
rather than the whole string, for the same reason. `mode='exact'` skips the
fuzzy stage entirely.

**The threshold is schema-bounded.** `FathomMatchingSchema` constrains
`fuzzy_threshold` to 0.5–1.0. Authoritative data is meant to be tuned without a
deploy, but a threshold near zero would make *every* client a match and
auto-attach a client transcript to an arbitrary company — the one failure mode
the blueprint singles out as worse than a human clicking Attach. Tunable, not
foot-gun-able.

---

## WP-9 — Talent domain: talents, tokens, certifications, availability · 2–3 d

> *Requirement: "Talent acquisition — how to pick talent? Token based: talents get tokens from attending events, completing certifications, period from last job assigned. Talent availability and calendar. Talents can be in-house workers or contracted talents."*

WP-9 is the data and the rules. WP-10 is the agent that uses them. WP-11 is the talent's own view. Keep them separate — building all three at once is how the scoring logic ends up embedded in a React component.

### 9.1 Data model

```python
class Talent(Base):
    __tablename__ = 'talents'
    id              = Column(Integer, primary_key=True)
    full_name       = Column(String(120), nullable=False)
    email           = Column(String(200), unique=True, nullable=False)
    phone           = Column(String(40))
    engagement_type = Column(String(20), default='contract')   # inhouse | contract
    status          = Column(String(20), default='active')     # active | paused | archived
    discipline      = Column(String(60))        # 'DOP', 'Editor', 'Art Director', 'Sound', ...
    seniority       = Column(String(20))        # junior | mid | senior | lead
    day_rate_kes    = Column(Integer)
    city            = Column(String(60), default='Nairobi')
    bio             = Column(Text)
    avatar_url      = Column(String(300))
    last_assigned_at = Column(DateTime)         # denormalised; drives idle accrual
    avg_rating      = Column(Float)             # denormalised from completed assignments
    created_at      = Column(DateTime, default=datetime.datetime.utcnow)
    notes           = Column(Text)              # INTERNAL — never exposed to the talent

class Skill(Base):            # id, name (unique), category
class TalentSkill(Base):      # talent_id, skill_id, level 1-5, verified_by_enrollment_id (nullable)
class PortfolioItem(Base):    # talent_id, title, role, client_name, year, media_url, link,
                              # description, is_public, order_index, created_at
class Certification(Base):    # id, key, name, provider, category, token_award, validity_months,
                              # grants_skill_id (nullable), is_mock (default True)
class CertificationEnrollment(Base):
                              # id, talent_id, certification_id, status, enrolled_at, completed_at,
                              # expires_at, score, attempts, evidence_url, is_mock, completed_by
class Event(Base):            # id, name, kind, starts_at, ends_at, token_award, checkin_code, location
class EventAttendance(Base):  # id, event_id, talent_id, checked_in_at, method ('code'|'admin')

class AvailabilityBlock(Base):
    __tablename__ = 'availability_blocks'
    id        = Column(Integer, primary_key=True)
    talent_id = Column(Integer, ForeignKey('talents.id'), index=True)
    start_at  = Column(DateTime, nullable=False)
    end_at    = Column(DateTime, nullable=False)
    kind      = Column(String(20), nullable=False)     # available | busy | tentative | leave
    source    = Column(String(20), default='manual')   # manual | ics | assignment
    ref_id    = Column(Integer)                        # assignment id when source='assignment'
    note      = Column(String(200))

class TokenLedger(Base):
    __tablename__ = 'token_ledger'
    id         = Column(Integer, primary_key=True)
    talent_id  = Column(Integer, ForeignKey('talents.id'), index=True, nullable=False)
    delta      = Column(Integer, nullable=False)       # signed
    reason     = Column(String(40), nullable=False)
    ref_type   = Column(String(30))                    # 'event' | 'enrollment' | 'assignment' | 'manual'
    ref_id     = Column(Integer)
    note       = Column(String(200))
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    created_by = Column(Integer, ForeignKey('users.id'))
    expires_at = Column(DateTime)
    # UniqueConstraint('talent_id','reason','ref_type','ref_id')  ← idempotency: no double credit
```

**The ledger is append-only and the balance is derived. Never store a `tokens` integer on `Talent`.** A stored balance drifts, cannot be audited, and cannot answer *"why do I have 74 tokens?"* — the first question every talent will ask. That unique constraint is what stops a retried request awarding the same certification twice.

### 9.2 Token mechanics

The policy lives in the `talent_token_policy` authoritative document (WP-1), never in code:

```json
{
  "earn": {
    "event_attendance":             10,
    "certification_completed":      { "default": 25, "by_category": { "safety": 15, "craft": 30, "software": 20 } },
    "assignment_completed_on_time": 15,
    "client_rating_5":              10,
    "referral_hired":               20
  },
  "spend": { "assignment_accepted": -40, "no_show": -50, "late_cancellation": -25 },
  "idle_accrual": { "tokens_per_idle_day": 2, "starts_after_days": 3, "cap": 60 },
  "expiry_days": 365,
  "floor": 0,
  "decline_penalty": 0
}
```

```python
# backend/tokens.py (NEW)
def balance(talent, at=None) -> dict:
    """Returns the full breakdown, not just a number — the UI and the talent both need the 'why'."""
    policy, prov = authoritative.resolve('talent_token_policy')
    now = at or datetime.datetime.utcnow()

    ledger = db_session.query(func.coalesce(func.sum(TokenLedger.delta), 0)).filter(
        TokenLedger.talent_id == talent.id,
        or_(TokenLedger.expires_at.is_(None), TokenLedger.expires_at > now)).scalar()

    ia = policy['idle_accrual']
    idle_days = ((now - talent.last_assigned_at).days if talent.last_assigned_at
                 else (now - talent.created_at).days)
    idle = min(max(idle_days - ia['starts_after_days'], 0) * ia['tokens_per_idle_day'], ia['cap'])

    return {"total": max(policy.get('floor', 0), ledger + idle), "ledger": ledger,
            "idle": idle, "idle_days": idle_days, "policy_version": prov['version']}
```

Three decisions worth defending, because they will be questioned:

**Idle tokens are computed, never written.** No cron, no scheduler, no drift, no missed-run backfill. The value is a pure function of `last_assigned_at` and the policy — deterministic, testable, and instantly correct when the policy changes. Accepting an assignment naturally zeroes it. A nightly job writing rows would introduce infrastructure the current single-worker deployment does not have, for no benefit.

**Accepting an assignment costs tokens.** This is what makes the system a *fair-share queue* rather than a leaderboard. Without a spend, the same high-token talent wins every casting run forever and the mechanism collapses into "rank by seniority." With a spend, working draws down your priority and idleness rebuilds it — which is exactly the intent behind *"period from last job assigned."*

**Declining an offer costs nothing** (`decline_penalty: 0`, recommended). Penalising declines punishes talent for being honestly unavailable and teaches them to accept work they cannot do. Track declines for visibility — three in 90 days raises a soft flag for a human conversation — but do not price them. *Late* cancellation after accepting is different and is penalised, because that one has a real production cost.

### 9.3 Availability

Conflict = any overlap with an `AvailabilityBlock` of kind `busy` or `leave`, or with an active `Assignment` window.

```python
def is_available(talent, start, end) -> tuple[bool, str | None]:
    clash = db_session.query(AvailabilityBlock).filter(
        AvailabilityBlock.talent_id == talent.id,
        AvailabilityBlock.kind.in_(('busy', 'leave')),
        AvailabilityBlock.start_at < end, AvailabilityBlock.end_at > start).first()
    if clash:
        return False, f"{clash.kind} {clash.start_at:%d %b}–{clash.end_at:%d %b}"
    ...
```

**Absence of data means available.** Requiring talent to declare positive availability produces an empty bench within a fortnight; requiring them to declare *unavailability* matches how freelancers actually behave.

Accepting an assignment auto-creates a `busy` block with `source='assignment'`, so the calendar stays true without anyone maintaining it.

**Calendar import is mocked this cycle:** paste an `.ics` file or URL, parse with the `icalendar` package, create `busy` blocks with `source='ics'`. No Google OAuth. The parse path is real, so swapping in a live connector later touches one function.

### 9.4 Certifications and events — the mocks

`Certification` rows carry `is_mock=True`. The catalog is seeded from the `certification_catalog` authoritative document, which also carries the mock assessment questions:

```json
{
  "certifications": [
    { "key": "set_safety_l1", "name": "On-Set Safety Level 1", "provider": "GDF Academy",
      "category": "safety", "token_award": 15, "validity_months": 24,
      "grants_skill": "Set Safety", "pass_mark": 0.8, "cooldown_hours": 24,
      "questions": [ { "q": "...", "options": ["...", "...", "...", "..."], "answer": 2 } ] }
  ]
}
```

**Mock flow:** enroll → `in_progress` → answer the quiz → score ≥ `pass_mark` → `completed`, `expires_at = now + validity_months`, ledger credit, and optionally a `TalentSkill` row with `verified_by_enrollment_id` set. Verified-by-certification skills are what let WP-10's hard filter distinguish a claimed skill from a proven one.

**Event attendance mock:** an `Event` has a `checkin_code`; the talent enters it on the portal within the event window and receives the award. Admins can also mark attendance manually. The ledger's unique constraint makes both paths idempotent.

**Expiry runs lazily too:** an enrollment past `expires_at` no longer counts toward the hard filter, and its ledger row drops out of the balance via the `expires_at` filter already in `balance()`. Again: no cron.

### 9.5 API (internal roles)

```
GET/POST  /api/talents                  list — filter by discipline, type, status, skill, available_between
GET/PATCH /api/talents/<id>             detail: token breakdown, skills, availability, portfolio
GET       /api/talents/<id>/tokens      full ledger with running balance
POST      /api/talents/<id>/tokens      manual adjustment (Admin only, note required)
GET/POST  /api/talents/<id>/availability
GET/POST  /api/certifications           catalog admin
POST      /api/enrollments/<id>/complete  admin-side mock completion
GET/POST  /api/events                   + POST /api/events/<id>/attendance
GET       /api/skills
```

### 9.6 Acceptance criteria

- [ ] The balance is derived; there is no `tokens` column on `Talent` — grep the migration to prove it.
- [ ] Awarding the same certification twice creates one ledger row, not two.
- [ ] Idle accrual matches the policy exactly at 0, 3, 10 and 60+ idle days and caps correctly — one test per boundary.
- [ ] Changing `tokens_per_idle_day` in authoritative data changes every balance immediately, with no migration and no job.
- [ ] Ledger rows past `expires_at` drop out of the balance.
- [ ] Availability conflicts are detected for partial overlaps at both ends of a window.
- [ ] `.ics` import creates `busy` blocks with `source='ics'`.
- [ ] Seed data produces at least 12 talents with varied `last_assigned_at`, token histories, disciplines, and both engagement types.

---

## WP-10 — Casting Agent + assignment lifecycle · 2–2.5 d

### 10.1 Scoring — deterministic maths first, model second

**The model does not pick the talent.** A scoring function produces a ranked shortlist; the model writes the human-readable rationale and flags concerns. This split matters: scoring must be reproducible, testable, and explainable to a talent who was not chosen, and an LLM is none of those things. It is, however, very good at *"here is why this line-up hangs together and here is what worries me about it."*

```python
# backend/casting.py (NEW)
def score_pool(role, candidates, policy) -> list[dict]:
    # 1. HARD FILTERS — eliminate, never penalise
    eligible = [t for t in candidates
                if t.status == 'active'
                and has_required_skills(t, role['required_skills'])
                and is_available(t, role['start_at'], role['end_at'])[0]
                and (t.day_rate_kes or 0) <= role.get('max_day_rate_kes', 10**9)
                and active_assignment_count(t) < policy['max_concurrent_assignments_per_talent']]

    # 2. NORMALISE each component 0..1 across the eligible pool (min-max)
    # 3. WEIGHTED SUM
    w = policy['weights']
    for t in eligible:
        c = {"tokens":      norm(tokens.balance(t)['total'], all_totals),
             "skill_match": skill_match_ratio(t, role),        # verified skills weighted higher
             "rating":      norm(t.avg_rating or 3.0, 1, 5),
             "inhouse":     1.0 if t.engagement_type == 'inhouse' else 0.0,
             "rate_fit":    1.0 - norm(t.day_rate_kes, all_rates)}
        t.score = sum(w[k] * c[k] for k in w)
        t.why   = [{"component": k, "raw": round(c[k], 4), "weight": w[k],
                    "contribution": round(w[k] * c[k], 4)} for k in w]

    # 4. DETERMINISTIC TIE-BREAK: score → tokens → idle days → lower rate → id
    return sorted(eligible, key=lambda t: (-t.score, -t.tokens, -t.idle_days, t.day_rate_kes, t.id))
```

`casting_policy` (authoritative, WP-1):

```json
{
  "weights": { "tokens": 0.35, "skill_match": 0.30, "rating": 0.15, "inhouse": 0.10, "rate_fit": 0.10 },
  "shortlist_size": 3,
  "inhouse_first": true,
  "require_human_approval": true,
  "offer_expiry_hours": 48,
  "max_concurrent_assignments_per_talent": 2
}
```

`inhouse_first: true` applies a pre-sort rather than a weight bump when in-house staff are eligible — GDF pays them regardless, so leaving them on the bench while paying a contractor is a straight loss. Keeping it as a separate switch rather than folding it into the weights makes that policy decision visible and reversible.

Weights must sum to 1.0, validated by the WP-1 schema check, so a policy edit cannot silently break scoring.

**Optional `casting_rank` capability (Tier 2, WP-2):** register `weighted_score` (the above), `tokens_only`, `lottery` (weighted random — genuinely useful for fairness experiments), and `weighted_plus_llm_review` (score, then let the model re-rank the top five with a justification). Switchable in the Lab so the policy argument can be settled with evidence rather than opinion.

### 10.2 The agent run

```python
def run_casting(engagement_id, roles=None):
    with agent_lock('casting', 'engagement', engagement_id, engagement_id=engagement_id):
        eng = db_session.query(Engagement).get(engagement_id)
        policy, p_prov = authoritative.resolve('casting_policy', engagement=eng)
        roles = roles or extract_roles_from_brief(eng)     # agent_llm driver, structured JSON out
        result = {}
        for role in roles:
            ranked = score_pool(role, all_candidates(), policy)
            shortlist = ranked[:policy['shortlist_size']]
            result[role['key']] = {
                "shortlist": [serialise(t) for t in shortlist],
                "rationale": narrate(role, shortlist, eng),   # the model writes prose from the numbers
                "concerns":  flag_concerns(role, shortlist),  # "all three are contract; no in-house cover"
                "pool_size": len(ranked)}
        # persisted as CastingRun + AgentEvent with authoritative_refs
```

`extract_roles_from_brief` reads the Production Brief for required roles, skills, dates and headcount. When the brief is thin it returns what it found and marks the rest `needs_input` rather than inventing roles — an invented role produces a confidently wrong shortlist, which is worse than an empty one.

### 10.3 Assignment lifecycle

```
proposed ──(AM approves)──▶ approved ──(offer sent)──▶ offered
                                                          │
                          ┌───────────────────────────────┼──────────────┐
                          ▼                               ▼              ▼
                      accepted                        declined       expired (48h)
                          │                               │              │
                          ▼                               └──────────────┘
                       active ──▶ completed ──▶ rated      (next shortlist candidate surfaced)
                          │
                          └──▶ cancelled (late_cancellation penalty)
```

```python
class Assignment(Base):
    __tablename__ = 'assignments'
    id             = Column(Integer, primary_key=True)
    engagement_id  = Column(Integer, ForeignKey('engagements.id'), index=True)
    talent_id      = Column(Integer, ForeignKey('talents.id'), index=True)
    role_label     = Column(String(80)); role_key = Column(String(60))
    status         = Column(String(20), default='proposed')
    day_rate_kes   = Column(Integer); days = Column(Integer)
    start_at       = Column(DateTime); end_at = Column(DateTime)
    proposed_by    = Column(String(20))          # casting_agent | human
    score_snapshot = Column(Text)                # JSON: score + the full `why` breakdown
    offered_at     = Column(DateTime); expires_at = Column(DateTime)
    responded_at   = Column(DateTime); decline_reason = Column(String(200))
    completed_at   = Column(DateTime); rating = Column(Integer)

class CastingRun(Base):   # id, engagement_id, status, requested_roles, result, policy_version,
                          # rank_driver, agent_event_id, created_by, created_at
```

| Transition | Token effect | Side effect |
|---|---|---|
| `accepted` | `spend.assignment_accepted` | `busy` block created; `last_assigned_at` set (idle accrual resets) |
| `completed` on time | `earn.assignment_completed_on_time` | `avg_rating` recomputed on rating |
| rated 5 | `earn.client_rating_5` | — |
| `declined` | none | decline counter for the soft flag |
| `expired` | none | next shortlist candidate surfaced to the AM |
| `no_show` | `spend.no_show` | flagged for review |
| late cancel | `spend.late_cancellation` | availability block released |

Every token movement writes a `TokenLedger` row with `ref_type='assignment'` and `ref_id`, so a talent's ledger reads as a narrative of their year.

### 10.4 API and UI

```
POST  /api/engagements/<id>/casting      run the agent (202, async, like every other agent)
GET   /api/engagements/<id>/casting      latest run: shortlists, scores, why, concerns
POST  /api/assignments                   AM creates from a shortlist entry (status='approved')
POST  /api/assignments/<id>/offer        sends the offer email (WP-12 mailer)
POST  /api/assignments/<id>/respond      accept/decline (also reachable from the portal)
PATCH /api/assignments/<id>              status transitions, rating, completion
GET   /api/engagements/<id>/assignments
```

```
frontend/src/pages/Casting.jsx              (NEW)  per-engagement: roles, shortlists, run button
frontend/src/pages/TalentDirectory.jsx      (NEW)  internal bench browser with filters
frontend/src/components/TalentCard.jsx      (NEW)  photo, discipline, rate, availability, token badge
frontend/src/components/ScoreBreakdown.jsx  (NEW)  the `why` array as a stacked bar
```

`ScoreBreakdown` is not decoration. It is what an Account Manager points at when a producer asks why the agent picked someone, and what makes the token system feel like a system rather than a black box.

### 10.5 Acceptance criteria

- [ ] Scoring is a pure function: same pool, same policy, same date → identical order, every time.
- [ ] Hard filters eliminate; an unavailable or unqualified talent never appears with a low score.
- [ ] Weight changes in `casting_policy` change the ranking with no deploy; non-summing weights are rejected on save.
- [ ] Every shortlisted talent carries a complete `why` breakdown whose contributions sum to the score.
- [ ] Ties break deterministically through all five levels.
- [ ] No assignment reaches a talent without an explicit AM approval step.
- [ ] Accepting creates the availability block, sets `last_assigned_at`, and debits the ledger — all three in one transaction.
- [ ] An expired offer surfaces the next candidate without re-running the agent.
- [ ] A talent at `max_concurrent_assignments_per_talent` is filtered out.

---

## WP-11 — Talent-facing portal · 3–4 d

> *Requirement: "Talent facing system — auth, mock register for certification, update portfolio, features pertaining what it takes to get tokens and be picked for work."*

### 11.1 ⚠️ Prerequisite to verify on day one

The codebase references `session.get('role')` and `updated_by` user ids, but a `User` table is **not confirmed**. Check the repo first:

- **If `User` exists** → add roles `Producer`, `Talent`, `Admin`, plus a nullable `talent_id` FK.
- **If it does not** (role set in the session at a login stub) → introduce `User(id, email, password_hash, role, talent_id, is_active, last_login_at, created_at)` in WP-11's migration and keep existing session-role behaviour working unchanged for internal users. **Do not refactor internal auth in the same PR as the talent portal.**

### 11.2 Auth and the isolation invariant

Talents are external users on the public internet. Internal staff are not. Treat them differently.

```python
def require_talent(fn):
    @wraps(fn)
    def inner(*a, **kw):
        if session.get('role') != 'Talent' or not session.get('talent_id'):
            return jsonify({"error": "Talent login required."}), 401
        return fn(*a, **kw)
    return inner
```

**The invariant, stated once and tested:** every talent-portal query is filtered by `talent_id == session['talent_id']` **at the query level** — never by checking an id passed in the request. **There is no talent route that accepts a `talent_id` parameter.** Write the test that logs in as talent A and attempts to read talent B's ledger, portfolio, offers and availability; all four must 404.

Hardening, because this is the first genuinely public surface the system has ever had:

- `werkzeug.security.generate_password_hash` (already available via Flask), minimum 10 characters.
- Login rate limiting (`flask-limiter`, e.g. 10/hour/IP) and lockout after repeated failures.
- Session cookies `Secure`, `HttpOnly`, `SameSite=Lax`.
- CSRF token on all state-changing talent routes.
- ~~**Invite-only registration.**~~ **Superseded — open sign-up shipped.** `POST /api/talent/signup` lets a talent create their own account and use the portal immediately; the row is tagged `signup_source='self'` and the bench marks it *self-registered* so curation becomes a visible signal rather than a gate. The invite path still exists for the other direction (GDF added the profile first, and wants the person to take it over): `POST /api/talent/<id>/invite` emails a single-use, time-limited set-password token, and with `EMAIL_DRIVER=console` the link prints to stdout, so it stays testable with no vendor account.
  **The one case sign-up must not swallow:** an email already on the bench with no password set. Creating an account there would hand a curated profile to anyone who knows a crew member's address, so that request returns 202 and emails a claim link instead. Covered by `tests/test_talent_signup.py`.

### 11.3 Portal surface

| Route | Purpose |
|---|---|
| `/talent/login` · `/talent/set-password` | Auth and invite redemption |
| `/talent/dashboard` | Token balance with breakdown, current offers, next best action |
| `/talent/profile` | Contact details, discipline, seniority, day rate, bio, claimed skills |
| `/talent/portfolio` | Add / edit / reorder / delete items; `is_public` toggle |
| `/talent/certifications` | Catalog, enroll, take the mock assessment, see expiry dates |
| `/talent/events` | Upcoming events; enter a check-in code to claim attendance tokens |
| `/talent/availability` | Month calendar; mark busy/leave; paste `.ics` |
| `/talent/tokens` | Full ledger: date, reason, delta, running balance, expiry |
| `/talent/offers` | Pending offers with countdown; accept / decline with reason |
| `/talent/how-i-get-picked` | **Renders `talent_token_policy` + `casting_policy` live from WP-1** |

### 11.4 "How I get picked" — one source of truth

This page is the direct answer to *"features pertaining what it takes to get tokens and be picked for work,"* and the design rule is that it must **render the authoritative policy documents, not a hand-written copy of them.** A duplicated explanation drifts from the real weights within one edit, and the moment a talent notices, the whole mechanism loses legitimacy.

Rendered live:

1. **How tokens are earned** — every `earn` entry as a plain sentence with its value.
2. **How tokens are spent** — including that accepting work costs tokens, and *why*: it is a fair rotation, not a punishment.
3. **Idle accrual** — *"you earn N tokens per day after M days without an assignment, up to a cap of C"* — with the talent's own current idle figure beside it.
4. **What else counts** — the casting weights as a chart: tokens 35%, skill match 30%, rating 15%, in-house 10%, rate fit 10%.
5. **The hard requirements** — active status, required skills, no calendar conflict. **No token total overcomes a clash.**
6. **Their own position** — current balance, breakdown, and the highest-leverage next action: *"complete On-Set Safety L1: +15 tokens."*

Talent read access is a **whitelisted** endpoint: `GET /api/talent/policies` returns only `talent_token_policy` and `casting_policy`. The generic WP-1 route stays closed to the Talent role.

### 11.5 What the talent must never see

`Talent.notes` (internal), other talents' scores or ledgers, client rate cards, proposals, briefs, engagement financials, and their own raw score relative to named others. Show *their* components; never the leaderboard. A visible ranking turns a fair-rotation queue into a competitive one and invites gaming.

### 11.6 API

```
POST /api/talent/login · /logout · /set-password
GET/PATCH /api/talent/me
GET/POST/PATCH/DELETE /api/talent/portfolio
GET  /api/talent/certifications        POST /api/talent/certifications/<key>/enroll
POST /api/talent/certifications/<enrollment_id>/submit
GET  /api/talent/events                POST /api/talent/events/checkin
GET/POST /api/talent/availability      POST /api/talent/availability/import-ics
GET  /api/talent/tokens
GET  /api/talent/offers                POST /api/talent/offers/<id>/respond
GET  /api/talent/policies              whitelisted authoritative read
```

### 11.7 Acceptance criteria

- [ ] Talent A cannot read or write any of talent B's data through any route — proven by the four-way test in §11.2.
- [ ] No talent route accepts a `talent_id` parameter.
- [ ] Invite → set password → login works end to end with `EMAIL_DRIVER=console`.
- [ ] Mock certification: enroll → quiz → pass → ledger credit → skill verified → dashboard balance updates.
- [ ] Failing the quiz awards nothing and allows a retake after the cooldown.
- [ ] An event check-in code awards once; a second attempt is a friendly no-op, not an error or a double credit.
- [ ] Portfolio CRUD with reordering persists.
- [ ] "How I get picked" values change immediately after a `talent_token_policy` edit, with no code change.
- [ ] Accepting an offer from the portal drives the same state machine as the internal route.
- [ ] Login is rate-limited; talent cookies are `Secure`, `HttpOnly`, `SameSite=Lax`.
- [ ] With `FEATURE_TALENT_PORTAL=false`, `/api/talent/*` returns 404.

---

## WP-12 — Reviewed-then-emailed proposal delivery · 1–1.5 d

> *A "Send via Email" action that unlocks only after the Account Manager has approved the proposal.*

The work is genuinely new — no email code exists in the repo today — but small, precisely because **the approval gate and the PDF renderer are both already built** (§1.4, §1.5).

### 12.1 Data model change

```python
# backend/models.py — Client currently has id, name, industry, notes
contact_email = Column(String(200))    # NEW — required before Send Email can be used
```

Paired with a contact-email field on `ClientDetail.jsx`, since no email field exists anywhere in the frontend today either.

### 12.2 The mailer — a capability, not a hardcoded vendor

`email` is a WP-2 capability with drivers `console`, `sendgrid`, `postmark`, `resend`, `smtp`. `console` is the local default and prints the rendered message plus attachment filename to stdout.

```python
# backend/providers/email/base.py
class EmailDriver(Driver):
    @abstractmethod
    def send(self, *, to, subject, html_body, attachment=None, tag=None) -> dict: ...
```

**The mailer serves three senders, not one:** proposal delivery (here), talent invites (WP-11), and assignment offers (WP-10). The `tag` argument exists from the first commit so per-purpose deliverability can be tracked later.

**Provider guidance,** for the volume profile that actually applies — a handful of sends per week, not bulk marketing:

| Driver | Best for | Notes |
|---|---|---|
| `console` | Local development and CI | No account, no network. The default. |
| `sendgrid` | Shipping fastest | Mature Python SDK, well-documented Flask integration, generous free tier at low volume. |
| `postmark` | Deliverability-critical sends | Purpose-built for transactional mail, strict separation from bulk traffic. Smaller free tier; worth it for the single highest-stakes email the agency sends. |
| `resend` | Cleanest modern DX | Narrower feature set — no inbound parsing, no marketing tooling — which is a non-issue here. |

**Recommendation:** ship on `sendgrid`, keep `postmark` as a one-setting deliverability upgrade if proposal mail ever lands in spam. Because it is a registry driver, that swap is a dropdown, not a deploy.

### 12.3 The route — reusing the existing gate and PDF

```python
# backend/app.py — sits next to download_proposal_pdf()
@app.route('/api/engagements/<int:eng_id>/proposal/send-email', methods=['POST'])
@feature('email')
def send_proposal_email(eng_id):
    if session.get('role') != 'Account Manager':
        return jsonify({"error": "Account Manager role required."}), 403

    eng = db_session.query(Engagement).get(eng_id)
    proposal = (db_session.query(Proposal).filter_by(engagement_id=eng_id)
                .order_by(Proposal.id.desc()).first())

    # The SAME gate the PDF-download route and the frontend button already use.
    # Deliberately not a new rule.
    if not proposal or proposal.status != 'approved':
        return jsonify({"error": "The proposal must be approved before it can be emailed."}), 400
    if not eng.client.contact_email:
        return jsonify({"error": "This client has no contact email on file."}), 400

    with agent_lock('email_send', 'engagement', eng_id, ttl_minutes=2):   # no double-send
        html_content = build_proposal_pdf_html(proposal, eng.client.name)   # existing function
        pdf_buffer = io.BytesIO(); HTML(string=html_content).write_pdf(pdf_buffer)

        cover, cover_prov = authoritative.resolve('email_cover_note', engagement=eng)
        providers.get('email').send(
            to=eng.client.contact_email,
            subject=f"{eng.client.name} — Proposal from GDF Kenya",
            html_body=render_email_body(eng, proposal, cover),   # short cover note, not the full proposal
            attachment=(pdf_buffer.getvalue(), f"{eng.client.name}_Client_Proposal.pdf"),
            tag="proposal")

        db_session.add(AgentEvent(
            engagement_id=eng_id, agent='Account Manager (Human)', trigger='proposal_email_sent',
            reasoning_summary=f"Emailed the approved proposal to {eng.client.contact_email}.",
            action='Sent Proposal via Email',
            authoritative_refs=json.dumps([cover_prov]), tokens_used=0))
        db_session.commit()
    return jsonify({"message": "Proposal emailed."})
```

### 12.4 Frontend

The button belongs directly beside the existing Download PDF button in the approved-proposal panel of `EngagementDetail.jsx`, **sharing its exact gating variable** so both actions become available together by construction:

```jsx
<button
  onClick={handleSendEmail}
  disabled={!proposalApproved || isSendingEmail}
  aria-disabled={!proposalApproved || isSendingEmail}
  aria-describedby="send-email-help"
  title={!proposalApproved ? 'Approve the proposal before emailing it' : 'Send to client'}
>
  {isSendingEmail ? 'Sending…' : emailSent ? 'Sent ✓' : 'Send via Email'}
</button>
<span id="send-email-help" className="sr-only">
  {!proposalApproved ? 'Approve the proposal before emailing it' : 'Sends the approved proposal PDF to the client contact'}
</span>
```

**A confirmation step before the send** — recipient address, editable cover note — is worth the extra hour. The same "review before it leaves the building" instinct that governs the whole approval flow should extend to the one click that actually leaves the building.

### 12.5 Acceptance criteria

- [ ] An unapproved proposal returns 400 and sends nothing.
- [ ] A client with no `contact_email` returns 400 with a clear message.
- [ ] A non-Account-Manager receives 403.
- [ ] The attached PDF is byte-identical to the download route's output.
- [ ] Double-clicking Send produces exactly one email (the lock).
- [ ] Switching the `email` driver from `console` to `sendgrid` requires no code change.
- [ ] The send is recorded as an `AgentEvent` with the recipient and the cover-note version.
- [ ] The disabled button's reason is available to a screen reader via `aria-describedby`, not just `title`.

---

## WP-13 — Accessibility · 3–4 d

### 13.1 Fix the code; do not bolt on a widget

**Explicitly avoid "accessibility overlay" products** (accessiBe, UserWay, All-in-One Accessibility and similar one-line-of-code widgets). The accessibility community's consensus — backed by the WebAIM Million survey and a 700-signatory Overlay Fact Sheet — is that these modify visual presentation without fixing underlying markup, and in aggregate testing, sites carrying an overlay showed *more* detectable errors on average than sites without one. accessiBe itself was fined by the FTC for deceptive accessibility claims.

For a genuinely usable app, fix the source: semantic HTML, real ARIA, real keyboard support.

### 13.2 Tool stack

| Tool | Layer | Why it fits |
|---|---|---|
| `eslint-plugin-jsx-a11y` | Lint time | Free; catches missing `alt`, invalid ARIA roles, click handlers on non-interactive elements — in the IDE, before a PR exists. Drop-in for the existing ESLint config. |
| `@axe-core/react` | Dev runtime | Runs axe-core in the browser console while developing — the same engine behind Lighthouse's accessibility score, and the industry's lowest-false-positive automated checker. |
| `jest-axe` or Playwright + `@axe-core/playwright` | CI gate | Fails the build when an accessible component regresses. The frontend has no test suite today; this is the natural place to start one. |
| NVDA (free, Windows) / VoiceOver (macOS, iOS) | Manual | Automated tools catch an estimated 30–40% of real issues. The rest needs a human driving a screen reader through the Brief → Proposal → Boardroom flows. |

### 13.3 Where an AI agent genuinely helps

**Agent-assisted remediation loop.** Point a coding agent at the app with an accessibility-focused prompt encoding the rules below (name every control, manage focus on route change, never put a click handler on a non-interactive element). The agent scaffolds the fix, then writes the matching axe/Playwright check that proves it — turning a manual page-by-page audit into an iterate-and-verify loop.

**Not a priority here:** AI alt-text generation. The Exodus is a text-and-data product — briefs, proposals, pricing tables, transcripts. The only image surface is talent headshots. ARIA and keyboard navigation are worth far more; do not spend the budget on alt text first.

### 13.4 Concrete fixes mapped to real components

| Gap | Where | Fix |
|---|---|---|
| Processing / approval state isn't announced | `TranscriptDropArea` busy state, `handleApprove` / `handleRequestChanges` in `EngagementDetail.jsx` | Wrap the "is processing" and "Proposal Approved" blocks in `<div aria-live="polite" aria-atomic="true">` so screen readers hear "Generating brief, please wait…" and "Proposal approved" without hunting for it. |
| Icon-only buttons | Approve / Download / Send buttons across `EngagementDetail.jsx` and `Inbox.jsx` | `aria-label` on every icon button. |
| Disabled-button reasoning is invisible | The `proposalApproved`-gated Download PDF and Send Email buttons | The code already sets a `title` tooltip; mirror it into `aria-disabled` + `aria-describedby` pointing at a hidden span. `title` alone is not reliably read by screen readers. |
| Focus trapping | Any modal or slide-out panel — now including the consent modal, coverage report, and confirm-before-send | Focus-trap on open, focus-return on close, Escape to close. |
| **Live regions done wrong** | `LiveTranscript.jsx` (WP-7) | A continuously updating transcript must be `aria-live="off"` with a "jump to latest" control. Reserve `polite` for coverage status changes, the missing-items summary, and recording start/stop. Getting this backwards makes the Boardroom unusable with a screen reader. |
| No reduced-motion / contrast support | Global CSS | `prefers-contrast` and `prefers-reduced-motion` media queries. |

### 13.5 Effort

| Task | Time |
|---|---|
| Install and configure `eslint-plugin-jsx-a11y` + `@axe-core/react` | 2 h |
| `aria-label` pass across all interactive controls (old and new UI) | 1 d |
| `aria-live` regions for processing, approval, coverage, error states | half day |
| Keyboard navigation + focus trapping for all modals and panels | 1 d |
| `prefers-contrast` / `prefers-reduced-motion` CSS | half day |
| Playwright + axe CI check, agent-assisted remediation pass, manual NVDA/VoiceOver walkthrough | 1 d |
| **Total** | **~3–4 days** |

### 13.6 Priority order if the budget shrinks

1. **The talent portal** — the only public-facing surface, and therefore the real legal and reputational exposure.
2. **Boardroom controls and the coverage report** — the hardest components to get right and the ones used under time pressure.
3. Internal admin screens.

### 13.7 Acceptance criteria

- [ ] `eslint-plugin-jsx-a11y` passes with no errors; the rule set is committed.
- [ ] Playwright + axe runs in CI and fails on a deliberately introduced violation.
- [ ] Every interactive control has an accessible name.
- [ ] Every modal traps focus, returns it on close, and closes on Escape.
- [ ] The live transcript is not an announcing live region; coverage changes are.
- [ ] A full keyboard-only pass through: create engagement → upload transcript → approve proposal → send email.
- [ ] A manual NVDA or VoiceOver pass through the Boardroom and the talent portal, with findings logged.

---

## WP-14 — Local-first developer experience + deployment readiness · 2–2.5 d

> *Requirement: "System should work locally and be ready for the planned deployment."*

### 14.1 Repository shape

```
├── backend/          Flask + SQLAlchemy + Alembic
├── frontend/         React + Vite
├── docs/             this blueprint
├── docker-compose.yml   whisper + ollama (+ optional postgres)
├── Makefile
└── AGENTS.md
```

```yaml
# docker-compose.yml (NEW)
services:
  whisper:
    image: hwdsl2/whisper-server          # faster-whisper, OpenAI-compatible API
    ports: ["8001:8000"]
    environment: [ "WHISPER_MODEL=small" ]
    volumes: [ "./.models/whisper:/models" ]
  ollama:
    image: ollama/ollama
    ports: ["11434:11434"]
    volumes: [ "./.models/ollama:/root/.ollama" ]
  # postgres:                              # uncomment before the talent portal goes public
  #   image: postgres:16
  #   environment: { POSTGRES_PASSWORD: dev, POSTGRES_DB: exodus }
  #   ports: ["5432:5432"]
```

```make
# Makefile (NEW)
setup:      ## one-time
	cd backend && python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
	cd frontend && npm install
	cp backend/.env.example backend/.env
	docker compose up -d ollama && docker compose exec ollama ollama pull qwen2.5:7b-instruct

db:         ## migrate + seed
	cd backend && alembic upgrade head && python seed.py && python seed_authoritative.py

dev:        ## everything
	docker compose up -d whisper ollama
	cd backend && gunicorn -w 1 --threads 8 -b 0.0.0.0:5000 app:app &
	cd frontend && npm run dev

test:
	cd backend && pytest -q
	cd frontend && npm run lint && npx playwright test

offline:    ## prove it runs with no internet: local STT, local LLM, console email
	STT_LIVE_DRIVER=local_whisper_chunked STT_BATCH_DRIVER=local_whisper_batch \
	POLISH_DRIVER=ollama AGENT_LLM_DRIVER=ollama COVERAGE_LLM_DRIVER=ollama \
	EMAIL_DRIVER=console $(MAKE) dev
```

**`make offline` is a real deliverable, not a joke target.** Being able to demonstrate the whole system running with nothing but local models is worth a great deal in a pitch, and it is the honest test of whether the provider abstraction actually works.

### 14.2 Local gotchas — each costs an hour if undocumented

- **`getUserMedia` requires a secure context.** `http://localhost` counts as secure; `http://192.168.x.x` does **not**. Testing the Boardroom from a phone on the LAN needs the Cloudflare Tunnel HTTPS URL, not the LAN IP.
- **Vite proxy for `/api`** so cookies stay first-party in dev, mirroring the production Vercel rewrite. Without it, session auth silently fails in dev and works in production — a maddening class of bug.
- **`ffmpeg` must be on `PATH`** for chunk normalisation and splitting.
- **The first Whisper request after idle is slow** while weights load. Keep the container warm; show a warming state rather than an error.
- **`EMAIL_DRIVER=console`** means no vendor account is needed to develop or test WP-11 and WP-12 end to end.
- **`STT_LIVE_DRIVER=browser_webspeech`** lets voice and boardroom UI be developed with no STT backend at all.

### 14.3 Seed data

`backend/seed.py` must produce a system that is immediately demoable: 3 clients; 1 engagement in each pipeline status; 12 talents mixing in-house and contract across disciplines with `last_assigned_at` deliberately spread from yesterday to 90 days ago so idle accrual is visible; token ledgers with a realistic mix of reasons; 6 certifications with quiz content; 3 events; availability blocks including deliberate conflicts; two sample audio files for the Lab; and every authoritative document at version 1.

### 14.4 Test priorities

Build the pure-function tests first — cheap, and they protect what is hardest to debug in a browser.

| Priority | What |
|---|---|
| 1 | Token balance and idle accrual at boundaries (0, 3, 10, 60+ days, cap) |
| 1 | Casting score determinism, tie-breaks through all five levels, hard filters |
| 1 | Talent isolation: A cannot reach B's ledger, portfolio, offers, availability |
| 2 | Provider resolution order and unavailable-driver fallback |
| 2 | Authoritative scope resolution and schema rejection |
| 2 | Coverage JSON parsing, including malformed output and evidence-free `covered` |
| 2 | Lock acquire / release / release-on-exception / stale reap |
| 3 | Stitch overlap de-duplication; audio split sizes; 429 backoff and failover |
| 4 | Playwright smoke: recording upload, boardroom session, casting run, talent login |

### 14.5 Pre-deploy checklist

- [ ] **All flags off on first deploy.** Enable one per day, in build order, watching logs. This is the entire reason the flags exist.
- [ ] **Migrations run as a deploy step**, before the new code starts — never on app boot (two processes racing to migrate corrupts SQLite).
- [ ] **Back up `factoryos.db` before every migration:** `sqlite3 factoryos.db ".backup pre-wp7.db"`, plus an automated nightly copy off the host. This database now holds the talent bench and a year of token history, and it is a single file on one machine.
- [ ] **`/api/healthz`** returning database reachability, every provider driver's health, and pending-migration status.
- [ ] **Secrets server-side only.** `GROQ_API_KEY`, `NIM_API_KEY`, `SENDGRID_API_KEY`, `WISPRFLOW_API_KEY` never reach the browser. The only permitted client-held credential is a short-lived Wispr Flow session token.
- [ ] **Cost guards live before the flags flip:** per-user daily STT seconds, per-session audio cap, per-engagement model-token budget with a log warning at 80%.
- [ ] **`FEATURE_LAB=false` in production** once you have settled — or leave it on for admins only. Per-request driver overrides are a debugging tool, not a production API.
- [ ] **Talent portal hardening** per §11.2.
- [ ] **`UPLOAD_DIR` retention job** — recordings are large; delete source audio on completion and orphaned uploads after N days.
- [ ] **Structured logs** with a request id; `AgentEvent` rows for every agent action.

### 14.6 The SQLite decision

Today: one gunicorn worker, eight threads, single-writer SQLite — deliberate and documented. It survives WP-0 through WP-6 without strain.

**WP-6, WP-7 and WP-11 change the write profile for the first time.** A boardroom session writes every 15 seconds; a recording job writes per piece; a talent portal opens writes to people outside the office. None is heavy alone, but the ceiling moves from theoretical to reachable.

**Recommendation: ship WP-0 through WP-7 on SQLite; move to Postgres before WP-11 goes public.** If `DATABASE_URL` has been used consistently since WP-0 — which is the point of doing WP-0 first — the move is a config change plus a data copy. Watch three things that differ: SQLite is lenient about column types, `func.now()` semantics differ, and Postgres enforces constraints SQLite quietly ignores. Run the test suite against both in CI from WP-9 onward so this surfaces early rather than on deploy night.

Once on Postgres, raise workers to `2 × cores + 1` and the executor cap accordingly. **Not before** — extra workers on SQLite produce `database is locked`, not throughput.

### 14.7 When to graduate the agent infrastructure

`ASSUMPTIONS.md` already flags this honestly: the agent runs synchronously on upload, and in a real-world scenario this would be offloaded to a message queue with websockets. That instinct is right; the trigger is not yet met. With the Coverage Agent and the Casting Agent added, the system has four agent types and linear hand-offs.

| Trigger | Move to |
|---|---|
| More concurrent jobs than the worker threads absorb, or a job must survive a restart | Celery or RQ + Redis — task functions already take only primitive IDs, so they port almost unchanged |
| One agent's output must conditionally decide which agent runs next | LangGraph — deterministic graph, good audit trail, fits a tool where every step must be explainable to an Account Manager |
| 4+ agent types with genuinely shared, evolving state | A proper framework evaluation — not before |

Adding LangGraph today would be infrastructure in search of a problem.

### 14.8 Acceptance criteria

- [ ] `make setup && make db && make dev` brings the whole system up on a clean machine.
- [ ] `make offline` runs the full flow — dictation, recording transcription, boardroom, brief generation — with the network disconnected.
- [ ] `make test` passes.
- [ ] `/api/healthz` reports every driver's status and pending migrations.
- [ ] Every flag can be toggled independently with no errors in either state.
- [ ] A fresh clone reaches a working demo in under 15 minutes following `README` alone.

---

# Reference

## R1. Consolidated data model delta

| Table | WP | Purpose | Note |
|---|---|---|---|
| `authoritative_docs` | 1 | Versioned, scoped system knowledge | Immutable rows; edit = new version |
| `runtime_settings` | 2 | Current driver per capability | Cached 30 s |
| `setting_changes` | 2 | Who switched what, when, why | Append-only |
| `comparison_runs`, `comparison_results` | 2 | Lab bake-offs | Serialised, one driver at a time |
| `agent_locks` | 3 | Scoped concurrency control | Unique (scope, ref_type, ref_id); TTL reaper |
| `recording_jobs`, `recording_segments` | 6 | Post-meeting transcription | Resumable from `pieces_done` |
| `boardroom_sessions` | 7 | A live meeting | Freezes the protocol version at start |
| `transcript_segments` | 7 | Rolling live STT output | Unique (session_id, seq) |
| `coverage_checks` | 7 | What was and wasn't discussed | Evidence required for `covered` |
| `talents` | 9 | The bench | **No token column** — derived |
| `skills`, `talent_skills` | 9 | Capability matrix | Verified-by-certification flag |
| `portfolio_items` | 9 | Talent-maintained work samples | `is_public` toggle |
| `certifications`, `certification_enrollments` | 9 | Catalog + mock completion | `is_mock=True` this cycle |
| `events`, `event_attendance` | 9 | Attendance token source | Check-in code mock |
| `availability_blocks` | 9 | Calendar | Absence means available |
| `token_ledger` | 9 | Append-only token history | Unique (talent, reason, ref) for idempotency |
| `assignments` | 10 | Talent ↔ engagement lifecycle | Carries `score_snapshot` |
| `casting_runs` | 10 | Agent output, archived | Stores the policy version used |
| `users` | 11 | **Verify whether it exists first** | Gains `role`, `talent_id` |

**Column additions to existing tables**

| Table | Column | WP |
|---|---|---|
| `agent_events` | `authoritative_refs` (JSON text, nullable) | 1 |
| `clients` | `contact_email` | 12 |
| `engagements` | `is_processing` becomes derived from `agent_locks` | 3 |

Roughly **twenty-two new tables and three column changes** — all additive, all nullable-or-defaulted, all reachable via `alembic upgrade head` from the current schema.

## R2. Consolidated API surface

```
# WP-0
GET  /api/config                          GET  /api/healthz

# WP-1  authoritative data
GET  /api/authoritative                   GET  /api/authoritative/registry
GET  /api/authoritative/resolve/<key>     GET  /api/authoritative/<key>/versions
POST /api/authoritative                   POST /api/authoritative/<id>/activate

# WP-2  providers + Lab
GET  /api/providers                       GET  /api/providers/health
POST /api/providers/<capability>          POST /api/providers/<capability>/test
GET  /api/providers/history
POST /api/lab/transcribe                  POST /api/lab/generate
GET  /api/lab/runs                        GET  /api/lab/runs/<id>
POST /api/lab/runs/<id>/adopt

# WP-4/5  speech
GET  /api/stt/status                      POST /api/stt/chunk
POST /api/voice/token

# WP-6  recording studio
POST /api/recordings                      POST /api/recordings/compare
GET  /api/recordings                      GET  /api/recordings/<id>
PATCH /api/recordings/<id>                POST /api/recordings/<id>/retry
POST /api/recordings/<id>/attach          POST /api/recordings/<id>/cancel
GET  /api/recordings/<id>/export          DELETE /api/recordings/<id>

# WP-7  boardroom
POST /api/boardroom/sessions              GET  /api/boardroom/sessions
GET  /api/boardroom/sessions/<id>         POST /api/boardroom/sessions/<id>/chunk
POST /api/boardroom/sessions/<id>/segments POST /api/boardroom/sessions/<id>/coverage
POST /api/boardroom/sessions/<id>/end     POST /api/boardroom/sessions/<id>/promote
GET  /api/boardroom/sessions/<id>/export  POST /api/boardroom/sessions/<id>/discard

# WP-9/10  talent (internal)
GET/POST /api/talents                     GET/PATCH /api/talents/<id>
GET/POST /api/talents/<id>/tokens         GET/POST  /api/talents/<id>/availability
GET/POST /api/certifications              POST /api/enrollments/<id>/complete
GET/POST /api/events                      POST /api/events/<id>/attendance
GET      /api/skills
POST/GET /api/engagements/<id>/casting    GET  /api/engagements/<id>/assignments
POST     /api/assignments                 PATCH /api/assignments/<id>
POST     /api/assignments/<id>/offer      POST /api/assignments/<id>/respond

# WP-11  talent portal (talent session only; never accepts a talent_id parameter)
POST /api/talent/login · /logout · /set-password
GET/PATCH /api/talent/me
GET/POST/PATCH/DELETE /api/talent/portfolio
GET  /api/talent/certifications           POST /api/talent/certifications/<key>/enroll
POST /api/talent/certifications/<enrollment_id>/submit
GET  /api/talent/events                   POST /api/talent/events/checkin
GET/POST /api/talent/availability         POST /api/talent/availability/import-ics
GET  /api/talent/tokens                   GET  /api/talent/offers
POST /api/talent/offers/<id>/respond      GET  /api/talent/policies

# WP-12  email
POST /api/engagements/<id>/proposal/send-email
```

## R3. Environment, dependencies, flags

```bash
# backend/.env.example
SECRET_KEY=change-me
DATABASE_URL=sqlite:///factoryos.db          # postgresql+psycopg://... in production
APP_BASE_URL=http://localhost:5173
UPLOAD_DIR=./var/uploads
MAX_UPLOAD_MB=500

# --- model providers ---
NIM_API_KEY=
NIM_BASE_URL=https://integrate.api.nvidia.com/v1
NIM_MODEL=nvidia/llama-3.3-nemotron-super-49b-v1
NIM_SMALL_MODEL=
GROQ_API_KEY=
GROQ_LLM_MODEL=llama-3.3-70b-versatile
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:7b-instruct

# --- speech ---
GROQ_STT_MODEL=whisper-large-v3-turbo
WHISPER_BASE_URL=http://localhost:8001/v1     # faster-whisper server, NOT ollama
WHISPER_MODEL=Systran/faster-whisper-small
WISPRFLOW_API_KEY=
STT_KEEP_AUDIO=false
STT_DAILY_SECONDS_PER_USER=7200

# --- email ---
SENDGRID_API_KEY=
POSTMARK_SERVER_TOKEN=
RESEND_API_KEY=
EMAIL_FROM=proposals@gdfkenya.com

# --- default driver per capability (runtime settings override these) ---
STT_LIVE_DRIVER=groq_chunked                  # groq_chunked | local_whisper_chunked | wispr_stream | browser_webspeech | off
STT_BATCH_DRIVER=groq_batch                   # groq_batch | local_whisper_batch | wispr_batch | off
POLISH_DRIVER=ollama                          # ollama | nim | groq_llm | off
AGENT_LLM_DRIVER=nim_nemotron                 # nim_nemotron | ollama | groq_llm
COVERAGE_LLM_DRIVER=ollama                    # nim_nemotron | nim_small | ollama | groq_llm
EMAIL_DRIVER=console                          # console | sendgrid | postmark | resend | smtp
CLIENT_MATCH_DRIVER=eng_tag_then_fuzzy        # exact | fuzzy_difflib | eng_tag_then_fuzzy

# --- existing ---
FATHOM_WEBHOOK_SECRET=

# --- feature flags: all default false, enable one at a time ---
FEATURE_AUTH_DATA=false
FEATURE_LAB=false
FEATURE_VOICE=false
FEATURE_RECORDINGS=false
FEATURE_BOARDROOM=false
FEATURE_TALENT=false
FEATURE_TALENT_PORTAL=false
FEATURE_EMAIL=false
```

```txt
# backend/requirements.txt — additions
alembic                 # WP-0 migrations
icalendar               # WP-9 .ics import
flask-limiter           # WP-11 login rate limiting
sendgrid                # WP-12, only when EMAIL_DRIVER=sendgrid
pytest, pytest-cov      # dev
# system dependency: ffmpeg
```

```jsonc
// frontend/package.json — additions
"eslint-plugin-jsx-a11y", "@axe-core/react", "@axe-core/playwright",   // WP-13
"date-fns"                                                            // calendars, countdowns
```

## R4. The switchable-options catalog

Everything you can change from the UI once WP-2 lands, and where each one is defined.

| Capability | Drivers | Where set | Built in |
|---|---|---|---|
| `stt_live` | `groq_chunked`, `local_whisper_chunked`, `wispr_stream`, `browser_webspeech`, `off` | Provider Settings, per-request in Lab | WP-4 |
| `stt_batch` | `groq_batch`, `local_whisper_batch`, `wispr_batch`, `off` | Provider Settings, per-job on the upload form | WP-4, WP-6 |
| `polish` | `ollama`, `nim`, `groq_llm`, `off` | Provider Settings | WP-4 |
| `agent_llm` | `nim_nemotron`, `ollama`, `groq_llm` | Provider Settings, Lab bake-off | WP-2 |
| `coverage_llm` | `nim_nemotron`, `nim_small`, `ollama`, `groq_llm` | Provider Settings, per-session | WP-7 |
| `email` | `console`, `sendgrid`, `postmark`, `resend`, `smtp` | Provider Settings | WP-12 |
| `client_match` | `exact`, `fuzzy_difflib`, `eng_tag_then_fuzzy` | Provider Settings | WP-8 |
| `casting_rank` *(Tier 2)* | `weighted_score`, `tokens_only`, `lottery`, `weighted_plus_llm_review` | Provider Settings | WP-10 |
| `diarization` *(Tier 2)* | `off`, `heuristic_llm`, `pyannote_local` | Provider Settings | later |

**Not drivers, but editable at runtime via authoritative data (WP-1):**

| Thing | Document key |
|---|---|
| Brief / proposal / coverage / polish prompts (with A/B variants) | `brief_prompt`, `proposal_prompt`, `coverage_prompt`, `polish_prompt` |
| Boardroom agenda and closing script | `boardroom_protocol` |
| Fathom fuzzy threshold | `fathom_matching` |
| Token earn/spend values, idle accrual, expiry | `talent_token_policy` |
| Casting weights, shortlist size, offer expiry | `casting_policy` |
| Certification catalog and quiz content | `certification_catalog` |
| Rate card, past projects, brand voice, email cover note | `rate_card`, `past_projects`, `brand_voice`, `email_cover_note` |

**Driver options** (model name, temperature, chunk seconds, Whisper model size) are per-driver forms inside Provider Settings, defined by each driver's `options_schema`.

## R5. Open decisions

| # | Decision | Blocks | Recommendation |
|---|---|---|---|
| 1 | Does a `User` table already exist, or is role kept in the session only? | WP-11 (hard block) | Verify on day one. If absent, create it in WP-11's migration; do not refactor internal auth in the same PR. |
| 2 | Does the deploy box have a GPU? | WP-4 | Decides whether local Whisper is a viable production engine or only an offline fallback. Check specs before WP-4 starts. |
| 3 | Production default for `stt_batch` | WP-6 | Ship on `groq_batch`, then settle it with a real Lab bake-off on your own recordings. That is what the Lab is for. |
| 4 | Is `assignment_accepted: -40` the right spend? | WP-10 tuning | Ship the mechanism; calibrate after a month of real bench data. It lives in authoritative data precisely so this is a policy edit, not a deploy. |
| 5 | Should declining an offer cost tokens? | WP-10 | **No.** Penalising declines teaches talent to accept work they cannot do. Track for a soft flag; do not price. |
| 6 | Postgres now or before WP-11? | WP-0 vs WP-11 | Use `DATABASE_URL` from WP-0 so the switch is configuration. Migrate before the talent portal goes public. |
| 7 | Recording consent wording and retention period | WP-7 | Have someone with legal standing at GDF sign off. Kenya's Data Protection Act (2019) applies. Default: text kept, audio never stored. |
| 8 | Who may edit authoritative documents? | WP-1 | Account Manager + Admin write; internal roles read; Talent reads only the two whitelisted policy keys. |
| 9 | Boardroom sessions with no engagement (new-business pitch)? | WP-7 | **Allow it.** Both `engagement_id` and `client_id` are nullable; promote later. A lot of the intake value is there. |
| 10 | Leave `FEATURE_LAB` on in production? | WP-14 | Admin-only. It is genuinely useful for diagnosing a bad transcript in the field, but per-request driver overrides should not be a public API. |
| 11 | Mock certifications long-term, or a real provider integration? | WP-9 scope | `is_mock=True` everywhere now means a real integration later is additive, not a rewrite. |
| 12 | Swahili / Sheng localisation at launch? | WP-11 scope | Not for v1, but keep UI strings in one module rather than inline so it stays a one-week job later. |

## R6. Deliberately out of scope

Named so nobody loses a week to them.

- **Real-time speaker diarisation.** Whisper does not diarise. Doing it properly needs pyannote and a GPU. The polish pass labels obvious turn changes, which is enough for a brief.
- **Live translation.** A mixed English/Swahili/Sheng boardroom transcribed *and* translated live produces a transcript nobody trusts. Transcribe in the spoken language; translate afterwards if ever asked.
- **Talent payments, invoicing, payroll.** Assignments carry a day rate for scoring only. Money is a separate system and a much larger regulatory surface.
- **A public talent marketplace.** Sign-up is now open (see §11.2) — anyone can join the bench and be considered. What is still explicitly out of scope is the *marketplace*: public talent profiles, clients browsing or booking crew directly, ratings visible between talents. GDF still does the casting; open registration only changed who may put their hand up.
- **AI alt-text generation.** Text-and-data product. ARIA and keyboard navigation are worth far more.
- **LangGraph / CrewAI.** Four agents, linear hand-offs. Revisit at the triggers in §14.7.
- **Runtime-switchable database or auth.** Security and persistence surfaces get exactly one code path.

---

*The Exodus (FactoryOS) · GDF Kenya · July 28, 2026 · Internal use only*
*Companion: `AGENTS.md` at the repository root.*
