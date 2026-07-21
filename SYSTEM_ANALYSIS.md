# FactoryOS — Full System Analysis

> Snapshot taken 2026-07-21 (branch `main`, commit `f68bb3f`). Written as the reference
> for planning major upgrades. File/line references are to this snapshot.

## 1. What the system is

FactoryOS is an internal tool for GDF Kenya (a communications agency) that turns raw
client-meeting transcripts into structured documents via an LLM pipeline with a human
approval loop:

1. **Agent 1 — Brief Generator**: Producer pastes the first client-meeting transcript →
   structured **Production Brief**.
2. **Agent 2 — Proposal Generator** (internally two LLM calls): Producer pastes the
   brief-review-meeting transcript → a **Signal Extractor** call distills the transcript
   into 9 buckets (decisions, changed requirements, budget/timeline signals, …), then the
   proposal call merges brief + signals + agency rate card into a **Client Proposal**
   with pricing line items.
3. **Human review**: Account Manager approves, or sends back with notes (which re-runs
   Agent 2 and creates a new proposal version).

Both documents export to styled PDFs. There is a global search bar and a (currently
UI-less) analytics endpoint.

## 2. Stack & processes

| Layer | Tech |
|---|---|
| Backend | Flask 3.1.3, SQLAlchemy 2.0.51 (classic `declarative_base` + `scoped_session`, **not** Flask-SQLAlchemy), SQLite, Pydantic 2 (LLM output validation), WeasyPrint 69 (PDF), flask-cors, python-dotenv, Werkzeug password hashing, cookie sessions |
| LLM | NVIDIA NIM chat-completions API (`https://integrate.api.nvidia.com/v1/chat/completions`), default model `meta/llama-3.1-70b-instruct`, temperature 0.2, max_tokens 4096, `requests` with 60 s timeout |
| Frontend | React 18 + Vite 6, Tailwind 3 (dark zinc/indigo theme), react-router-dom 7, lucide-react icons. No state library — plain `fetch` with `credentials: 'include'` |

**Processes** ([start_servers.sh](start_servers.sh)): kills anything on ports 5000/5173,
starts Flask (`:5000`, logs `/tmp/backend_run.log`) and Vite (`:5173`,
`/tmp/frontend_run.log`), then health-checks both. Demo credentials: `producer`/`demo`
and `am`/`demo`.

**Config** ([backend/.env](backend/.env), loaded by `load_dotenv()` at the top of
[app.py](backend/app.py) *before* `agents.py` is imported, because `agents.py` reads
`NIM_API_KEY` at import time):

- `NIM_API_KEY` — currently **empty**, so both agents run in placeholder/dummy mode.
- `NIM_MODEL` — optional override.
- `SECRET_KEY` — falls back to a hardcoded demo value.
- `DATABASE_URL` — currently set to `sqlite:///./test.db` (see Bug #2 below — this
  breaks the app).

**Dependencies**: [backend/requirements.txt](backend/requirements.txt) is the
authoritative pinned list (regenerated from the working venv). The root
[requirements.txt](requirements.txt) is a stale older copy (lists unused
Flask-SQLAlchemy, missing weasyprint) and should be deleted or replaced.

## 3. Database schema ([models.py](backend/models.py))

SQLite via `create_all()` — **no migration tooling**. Tables:

- `users` — id, username (unique), password_hash, role (`Producer` | `Account Manager`)
- `clients` — id, name, industry, notes
- `engagements` — id, client_id → clients, **status** (the pipeline state machine),
  relationship `client` (backref `engagements`). *No created_at column.*
- `transcripts` — id, engagement_id, kind (`client_meeting` | `brief_review_meeting`),
  raw_text, uploaded_at, uploaded_by → users
- `briefs` — id, engagement_id, transcript_id, **structured_json** (JSON),
  rendered_markdown, work_type, version (default 1), created_at
- `proposals` — id, engagement_id, brief_id, review_transcript_id (nullable),
  **structured_json**, rendered_markdown, **pricing_line_items** (JSON list of
  `{category, description, qty, rate_kes}`), status (`draft` | `in_review` |
  `approved`), version, created_at
- `rate_card_items` — category, description, unit, rate_kes
- `past_projects` — client_type, work_type, summary, deliverables_used (JSON-as-text),
  typical_pricing_notes
- `agent_events` — engagement_id, agent, trigger, reasoning_summary, action,
  tokens_used (always written as 0), created_at — powers the Activity Log and
  analytics activity feed

Documents are immutable-append: a send-back creates a *new* `proposals` row with
`version + 1`; "latest" is picked by `id desc` in most endpoints and by `version` in
analytics.

### Engagement status state machine

```
awaiting_transcript ──upload #1 (Agent 1)──▶ brief_ready ──upload #2 (Agent 2)──▶ proposal_ready
                                                                                    │
                             AM approve ◀── in_review ◀── AM send_back (Agent 2 rerun)
                                 │
                                 ▼
                             approved
```

`awaiting_review_transcript` is declared in the stage list (backend
`PIPELINE_STAGES`, frontend `Dashboard.jsx`) and accepted by the upload endpoint, but
**nothing ever sets it** — the pipeline goes straight `brief_ready → proposal_ready`.
Dead state, kept for UI/analytics compatibility.

## 4. API surface ([app.py](backend/app.py))

| Route | Method | Auth check | Purpose |
|---|---|---|---|
| `/api/login` | POST | — | Verifies password hash; stores `user_id` + **role chosen in the login form** (client-supplied role overrides the DB role) in the session cookie |
| `/api/logout` | POST | — | Clears session |
| `/api/me` | GET | session | Current username + role |
| `/api/engagements` | GET | none | List all (id, client_name, status) |
| `/api/engagements` | POST | none | Create engagement for `client_id`, status `awaiting_transcript` |
| `/api/clients` | GET | none | List clients (for pickers) |
| `/api/clients` | POST | none | Create client; case-insensitive name match **reuses** an existing client (200 + `reused: true`) instead of duplicating |
| `/api/engagements/<id>` | GET | none | Engagement + latest brief + latest proposal + all events |
| `/api/engagements/<id>/transcripts` | POST | session | **The core dispatch**: if status `awaiting_transcript` → Agent 1 flow (save transcript, generate brief, status→`brief_ready`, log event); if `brief_ready`/`awaiting_review_transcript` → Agent 2 flow (save transcript, generate proposal, status→`proposal_ready`, log 2 events: Proposal Generator + Signal Extractor); else 400 |
| `/api/engagements/<id>/proposals/review` | POST | session + role == `Account Manager` | `approve` → proposal & engagement `approved`; `send_back` (notes required by UI) → re-runs Agent 2 with `additional_notes`, new proposal row v+1, status `in_review` |
| `/api/rate-card` | GET | none | Rate card list |
| `/api/analytics` | GET | none | Funnel per stage, pipeline value vs approved revenue (from latest proposal per engagement), work-type mix, avg turnaround per hop (transcript→brief, brief→proposal, proposal→approval), send-back rate, proposals table, 12 most recent events. **No frontend consumes this yet.** |
| `/api/search?q=` | GET | none | ≥2 chars; `ilike` over client names, brief markdown, proposal markdown *and* pricing JSON cast to string; dedupes per engagement; previews summarize the *latest* proposal version; max 10 results |
| `/api/engagements/<id>/brief/pdf` | GET | none | WeasyPrint PDF (indigo accent) built from `brief.structured_json` |
| `/api/engagements/<id>/proposal/pdf` | GET | none | WeasyPrint PDF (emerald accent) from `proposal.structured_json` + pricing table with computed totals |

Error handling: agent failures roll back the DB session and return 500 with the
exception text. All list/detail endpoints are unauthenticated (prototype posture,
acknowledged in [ASSUMPTIONS.md](ASSUMPTIONS.md)).

## 5. Agent pipeline ([agents.py](backend/agents.py))

Shared plumbing:
- `call_nim_api(system, user)` — single non-streaming chat completion.
- Fence stripping: first attempt slices `[7:-3]` / `[3:-3]` off ```` ```json ````
  fences (brittle re: trailing whitespace); the retry path uses the more robust
  `_extract_json()`.
- **Validate → retry → fallback** pattern in both agents: parse JSON, validate with
  Pydantic; on any failure retry once with the error text appended to the user prompt;
  on second failure return a stub document containing the error message (so the
  pipeline never hard-fails, it just produces a visibly broken doc).
- **No API key → deterministic placeholder documents** (every section "Not specified —
  needs follow-up" / "Dummy"). This is the current running mode.

`generate_brief(transcript, client_name)`
- Output contract (`ProductionBriefSchema`): exactly `{work_type, rendered_markdown}`;
  `work_type` ∈ {change-management campaign, employee engagement, creator campaign,
  video production, event}.
- The prompt mandates a fixed 10-section markdown template (Client Overview, Project
  Summary, Objectives, Target Audience, Deliverables, Creative Direction, Timeline,
  Budget, Constraints, Open Questions) and forbids inventing missing info — gaps go
  to Open Questions.

`extract_meeting_signals(transcript)` → markdown with 9 fixed buckets (Decisions,
New/Changed Requirements, Budget Signals, Timeline Signals, Creative Feedback, Action
Items, Questions Raised, Questions Answered, Flagged as Unclear). Ambiguity must be
flagged, not resolved. Logged to the activity feed as agent "Signal Extractor".

`generate_proposal(new_transcript, brief, client_name, past_projects, rate_card, additional_notes)`
- Calls `extract_meeting_signals` first; manager send-back notes are appended to the
  signals block as "## Manager Additional Notes".
- Prompt: brief is baseline, signals win on conflict but changes must be listed in a
  "What Changed" section; pricing must come from the rate card items (serialized as
  text lines).
- Output contract (`ProposalSchema`): `{rendered_markdown, pricing: [PricingLineItem]}`;
  `extracted_signals` is attached afterwards so `app.py` can log it.
- ⚠️ `past_projects` is accepted **but never used in the prompt** (see Bug #5).

`render_brief_markdown()` is dead code — nothing calls it.

## 6. Frontend ([frontend/src/](frontend/src/))

Routing ([App.jsx](frontend/src/App.jsx)): `/login`; everything else nested under
[Layout](frontend/src/components/Layout.jsx) which fetches `/api/me` on mount and
redirects to `/login` on 401 (this is the entire auth guard). `/` → `/dashboard`;
`/engagements` reuses the Dashboard component; `/engagements/new`;
`/engagements/:id`. Layout passes `user` down via router outlet context.

- [Login.jsx](frontend/src/pages/Login.jsx) — prefilled `producer`/`demo`, role
  dropdown sent with login (demo role switcher).
- [Dashboard.jsx](frontend/src/pages/Dashboard.jsx) — engagement cards grid with
  client-side status-filter pills (counts computed in a memo; empty stages disabled).
- [NewEngagement.jsx](frontend/src/pages/NewEngagement.jsx) — two sequential POSTs:
  create/reuse client, then create engagement; navigates to the new detail page.
- [EngagementDetail.jsx](frontend/src/pages/EngagementDetail.jsx) — the workhorse:
  - Upload box (shown in `awaiting_transcript`/`brief_ready`/`awaiting_review_transcript`)
    posts to the shared transcripts endpoint; **backend status decides** whether it
    becomes a brief or a proposal.
  - Brief panel renders `rendered_markdown` inside a `<pre>` (no markdown renderer),
    with a "Create Proposal" textarea inline when no proposal exists yet.
  - Proposal panel renders `<ProposalReport …/>` — **currently undefined, crashes**
    (Bug #1).
  - Review buttons (AM only, proposal not yet approved): Approve / Send Back, notes
    collected via `window.prompt`.
  - PDF download via blob + temporary `<a download>`, filename parsed from
    Content-Disposition.
  - Failure UX gap: `handleUpload` ignores non-OK responses — the spinner stops and
    nothing tells the user the agent failed.
- [SearchBar.jsx](frontend/src/components/SearchBar.jsx) — 250 ms debounce, ≥2 chars,
  results grouped by client, full keyboard navigation (arrows/enter/escape),
  click-outside to close, match-type chips (Client/Brief/Proposal).

The API base URL `http://localhost:5000` is hardcoded in every fetch call
(~10 sites across 6 files).

## 7. PDF generation ([app.py](backend/app.py#L601-L787))

Built directly from `structured_json` (not from the markdown): a shared CSS shell
(`PDF_STYLE` with `ACCENT_*` placeholder substitution, A4, page-numbered footer,
gradient banner) plus per-document body builders:

- `build_brief_pdf_html` — objectives/audience/deliverables bullets, timeline+budget
  info boxes, stakeholder tags, risks callout, open questions. Indigo accent.
- `build_proposal_pdf_html` — approach, scoped deliverables, phased timeline, team
  tags, pricing table with per-line `qty × rate_kes` and grand total. Emerald accent;
  "Approved" badge when applicable.

All values are HTML-escaped (`_esc`). [test_pdf_gen.py](backend/test_pdf_gen.py) is a
manual smoke script (an older markdown-based layout, not the current builders).

## 8. Seed data ([seed.py](backend/seed.py))

Wipes all tables, then creates: 2 users; 3 clients (KCB Bank, Safaricom, EABL); one
fully-populated Safaricom engagement `in_review` (both transcripts, brief, proposal
with 3 pricing lines totalling KES 950,000); one empty KCB engagement
`awaiting_transcript` for the live demo; 7 rate-card items; 2 past projects.
The live `factoryos.db` currently holds 12 engagements / 6 briefs / 2 proposals from
manual testing.

## 9. Bugs, dead ends, and inconsistencies (fix before/during upgrades)

1. **Proposal view crashes (P0).** [EngagementDetail.jsx:278](frontend/src/pages/EngagementDetail.jsx#L278)
   renders `<ProposalReport …/>`, but commit `a30d683` ("merge") deleted the
   definitions of `ProposalReport`, `BriefReport`, `ReportSection`, and `BulletList`
   that commit `247e1e7` had added, while leaving this call site. Any engagement with
   a proposal (e.g. seeded Safaricom) throws `ReferenceError: ProposalReport is not
   defined`. Recover the components from `git show 247e1e7` or rewrite.
2. **App and seed point at different databases (P0).** [backend/.env](backend/.env)
   sets `DATABASE_URL=sqlite:///./test.db`, which `flask run` picks up via
   `load_dotenv()` — but `test.db` doesn't exist and `flask run` never calls
   `init_db()` (only `seed.py` and `python app.py` do), so every request will 500
   with "no such table". Meanwhile `seed.py` doesn't load `.env` at all, so it seeds
   `factoryos.db`. Fix: clear the `DATABASE_URL` line (falls back to
   `factoryos.db`), and add `load_dotenv()` to `seed.py` so both always agree.
3. **`structured_json` contract mismatch (P1).** The PDF builders, search previews,
   and seed data expect rich keys (`objectives`, `audience`, `deliverables`,
   `timeline_signals`, `budget_signals`, `key_stakeholders`, `risks`,
   `open_questions` on briefs; `approach`, `scoped_deliverables`, `phased_timeline`,
   `team_shape` on proposals). But the LLM schemas only produce
   `{work_type, rendered_markdown}` and `{rendered_markdown, pricing}` — so for any
   *agent-generated* document the PDFs render mostly "Not specified"/empty sections
   and search previews are bare. Only the hand-seeded Safaricom docs look right.
   Upgrade path: extend the agent output schemas (and Pydantic models) to emit the
   structured fields the renderers already expect.
4. **Analytics endpoint is orphaned.** `/api/analytics` is complete and useful but no
   page calls it (Layout even imports the `BarChart3` icon and never uses it). An
   analytics dashboard page is a ready-made upgrade.
5. **Past projects are fetched but ignored.** `app.py` queries `PastProject.limit(3)`
   and passes them to `generate_proposal`, whose prompt never includes them — despite
   the README advertising "patterns from Past Projects". Wire them into the prompt.
6. **Login logs credentials.** `app.py` `print()`s the submitted username *and
   password* (and other debug lines) on every login. Remove before anything
   non-local.
7. **Client-supplied role.** The role dropdown at login overrides the DB role in the
   session — by design for the demo, but it means anyone can self-elevate to Account
   Manager. Replace with DB-role-only when auth gets real.
8. **Silent agent failure in UI.** Non-OK responses to transcript upload are swallowed
   (no alert/toast); backend 500s include raw exception text.
9. **Stale root [requirements.txt](requirements.txt)** (see §2).
10. **Dead code / dead state**: `render_brief_markdown()` unused;
    `awaiting_review_transcript` never set; `tokens_used` always 0;
    `test_pdf_gen.py` tests a superseded layout.
11. **Brittle fence stripping** on the first parse attempt (`[7:-3]` slicing);
    a response with trailing whitespace after the closing fence fails and burns the
    retry. Use `_extract_json()` on the first attempt too.
12. **No `created_at` on engagements** — limits analytics (no engagement age/velocity).
13. **Everything-public API** — most GET/POST endpoints skip the session check
    (prototype-acceptable, but the first thing to change for multi-user).

## 10. Upgrade levers (observations, not a plan)

- **Contract unification (Bug #3) is the keystone**: once agents emit the full
  structured schema, the on-screen report components (recoverable from `247e1e7`),
  PDFs, and search previews all light up for real data.
- **Auth**: real sessions/JWT, server-side roles, per-endpoint guards; drop the demo
  role switcher.
- **Async agents**: uploads currently block a Flask worker for up to ~2 LLM calls ×
  60 s. ASSUMPTIONS.md already sketches the target (queue + progress push).
- **Migrations**: introduce Alembic before touching the schema.
- **Frontend**: central API client with a configurable base URL (or a Vite dev-server
  proxy), real markdown rendering, error toasts, an Analytics page for the existing
  endpoint.
- **LLM layer**: `call_nim_api` is a single choke point — swapping providers/models or
  adding JSON-mode/structured-output support only touches `agents.py`; token usage is
  already modeled in `agent_events` but never populated.
