# AGENTS.md — The Exodus (FactoryOS)

Rules of engagement for any coding agent working in this repository. This file stays loaded in every session. It is short on purpose.

**Full specification: `docs/THE_EXODUS_Master_Implementation_Blueprint.md`.** Read the specific `WP-n` section for whatever you are building. Do not work from this file alone — it contains the rules, not the designs.

**Before starting WP-9, WP-10, or WP-11:** the blueprint's §1 predates an already-shipped "Part 2" subsystem — `backend/staffing.py`, the `Talent` and `StaffingPlan` models, `seed_talents.py`, and `GET /api/talents` / `POST .../staffing`. It does deterministic skill/title-matched crew assignment today. Extend it additively (new nullable columns, new modules) rather than re-modelling `Talent` from scratch — see the note in blueprint §1.8.

---

## 1. What this system is

The Exodus turns client meeting transcripts into Production Briefs and Client Proposals for GDF Kenya, a creative agency in Nairobi.

- **Product name: The Exodus. Engineering codename: FactoryOS.** Use "The Exodus" in anything a user reads; "FactoryOS" only for the repo, module names, and internal docs.
- **Stack:** Flask + SQLAlchemy + SQLite backend; React 18 + Vite + Tailwind frontend; NVIDIA NIM (Nemotron) for agents; WeasyPrint for PDFs; Fathom webhook for transcript intake.
- **Deploy:** Vercel (frontend) → `/api/*` rewrite → Cloudflare Tunnel → gunicorn, **one worker, eight threads**.
- **Existing agents** in `agents.py`: `generate_brief`, `refine_brief`, `extract_meeting_signals`, `generate_proposal`, `revise_proposal`. All run on a shared `ThreadPoolExecutor(max_workers=3)` and log to `AgentEvent`.

**What is being added:** voice dictation, post-meeting transcription (cloud and local), a live Boardroom page that reports what a meeting failed to cover, a provider registry that makes every engine switchable from the UI, a system-wide authoritative-data layer, token-based talent casting, a talent portal, reviewed-then-emailed proposal delivery, and an accessibility pass.

---

## 2. Non-negotiable invariants

Breaking any of these is a rejected PR, regardless of whether tests pass.

1. **Human approval gates stay.** Nothing client-facing — a proposal, an email, a talent offer, a transcript feeding the brief agent — leaves the system without an explicit human action. Automation prepares; a human releases.
2. **Every agent action writes an `AgentEvent`**, including which authoritative document versions it read (`authoritative_refs`) and which driver it used. The audit log is this product's credibility.
3. **Additive migrations only.** No dropped columns, no renamed tables, no destructive defaults. SQLite cannot `ALTER COLUMN`; new columns are nullable or carry a server default. Alembic runs with `render_as_batch=True`.
4. **One gunicorn worker while the database is SQLite.** Do not add worker processes, a second thread pool, or a background scheduler. Background work goes through the existing `ThreadPoolExecutor` and the `AgentLock` pattern.
5. **Task functions take primitive IDs, never live ORM objects.** They re-query on their own thread and call `db_session.remove()` in a `finally` block. Routes return **202** and the frontend polls; an HTTP request never waits on a model call.
6. **Secrets stay server-side.** No API key ever reaches the browser. The only permitted client-held credential is a short-lived, scoped session token.
7. **Policy lives in authoritative data, not in code.** Thresholds, weights, token values, agenda items, prompts: if a human might reasonably want to change it without a deploy, it belongs in an `AuthoritativeDoc`.
8. **Integrations are drivers, not hardcoded calls.** Anything with more than one plausible implementation — speech, LLMs, email, matching — registers with the provider registry and is switchable at runtime. Never call a vendor SDK directly from a route.
9. **Talent data is isolated at the query level.** Every talent-portal query filters on `session['talent_id']`. No talent route accepts a `talent_id` parameter, ever.
10. **New features ship behind a feature flag, default off**, enforced on the backend (route returns **404**, not 403) and the frontend (UI absent).
11. **Never invent content in a transcript, brief, or coverage check.** Cleanup passes remove filler and fix spelling; they do not summarise, infer, or add. A coverage item with no supporting evidence is `partial`, never `covered`.

---

## 3. Working loop

1. Confirm the WP's dependencies are merged. If not, stop and say so.
2. Read the WP section in the blueprint. **Restate the scope in two sentences before writing code.**
3. Build in this order: **migration → models → service module → route → frontend → test**.
4. Work through the WP's acceptance criteria explicitly. Any box you cannot check, say so in the PR rather than quietly skipping it.
5. One WP per branch: `wp-6-recording-studio`, `wp-7-boardroom`.

**Before opening a PR:**

```bash
cd backend  && venv/bin/alembic upgrade head && venv/bin/pytest -q
cd frontend && npm run build
```

`alembic revision --autogenerate` on a clean tree must produce an **empty** diff — both `upgrade()` and `downgrade()` bodies just `pass`. If not, models and migrations have drifted. Generate new migrations against an **empty** database (`DATABASE_URL=sqlite:///tmp.db alembic upgrade head` first), not your dev copy, or Alembic will emit spurious type-change churn from SQLite's loose typing.

`npm run lint` is currently **broken** — ESLint 9 needs an `eslint.config.js` and the repo only has the old format. Fixing it is unclaimed work; don't let a lint failure block you, and don't silently drop the lint step from this file either.

---

## 4. Where things go

```
backend/
  app.py                routes only — thin. Business logic does not live here.
  config.py             every env var, one place                        [WP-0]
  models.py             SQLAlchemy models
  agents.py             model-calling agent functions
  authoritative.py      resolve(), REGISTRY, schema validation          [WP-1]
  providers/
    base.py             Driver ABC, DriverInfo
    registry.py         CAPABILITIES, register(), get()                 [WP-2]
    stt/                groq_chunked · groq_batch · local_whisper_* · wispr_* · browser
    llm/                nim · ollama · groq_llm
    email/              console · sendgrid · postmark · resend · smtp
  locks.py              agent_lock() context manager                    [WP-3]
                        task functions get @_with_lock(scope) in app.py
  audio.py              ffmpeg normalise / probe / split                [WP-4]
  stitch.py             overlap-aware segment joining                   [WP-4]
  polish.py             transcript cleanup                              [WP-4]
  recordings.py         post-meeting job worker                         [WP-6]
  tokens.py             balance(), award(), spend()                     [WP-9]
  casting.py            scoring — a pure function                       [WP-10]
  fathom.py             Fathom webhook (exists)
  staffing.py           deterministic crew matching (exists — see §1 note)
  rag.py                completeness check (exists)
  migrations/           Alembic
  tests/                pytest — conftest.py points at a temp DB
frontend/src/
  pages/                route-level components
  components/           reusable
  lib/                  api client, config context, formatters
```

**One third-party integration per module**, mirroring the existing `fathom.py` pattern. Integration code never goes in `app.py`.

---

## 5. Conventions

**Backend**
- Async work returns 202 immediately; the frontend polls existing status fields.
- Errors return `{"error": "Human-readable sentence."}` with a real status code. No stack traces to the client.
- Role checks are decorators, not inline `if` statements.
- Every third-party call: explicit `timeout=`, one retry with backoff, and a defined fallback driver. Never an unbounded call in a request path.
- Model output that must be structured: strict JSON parse → one repair retry → a safe default that is **clearly marked as a failure**. Never a silent success.
- A driver that cannot run reports it through `health()` / `available()`. It never raises at call time.

**Frontend**
- No new state library. Component state and the existing polling pattern.
- Every interactive control gets an `aria-label` and keyboard operability **in the commit that creates it**. WP-13 is a verification pass, not a cleanup crew.
- `aria-live="polite"` for status changes only. A continuously updating transcript is `aria-live="off"` with a "jump to latest" control.
- Show a `ProviderBadge` wherever a driver produced an artefact — the user should never have to guess which engine wrote something.
- No accessibility overlay widgets. Ever. Fix the markup.

**Prompts**
- Agent prompts live in authoritative documents so a human can tune and A/B them. Never inline in a route.
- Every prompt states what the model must **not** do. Invention is the failure mode that matters here.

---

## 6. Test priorities

Pure-function tests first — cheap, and they protect what is hardest to debug in a browser.

| Priority | What |
|---|---|
| 1 | Token balance and idle accrual at boundaries (0, 3, 10, 60+ days, cap) |
| 1 | Casting score determinism, tie-breaks through all five levels, hard filters |
| 1 | Talent isolation: A cannot reach B's ledger, portfolio, offers, availability |
| 2 | Provider resolution order and unavailable-driver fallback |
| 2 | Authoritative scope resolution (engagement > client > global) and schema rejection |
| 2 | Coverage JSON parsing: malformed output, and evidence-free `covered` |
| 2 | Lock acquire / release / release-on-exception / stale reap |
| 3 | Stitch overlap de-duplication, audio split sizes, 429 backoff and failover |
| 4 | Playwright smoke: recording upload, boardroom session, casting run, talent login |

---

## 7. Things that will look like good ideas and are not

- **Using Ollama for speech-to-text.** It has no ASR endpoint. Local STT is faster-whisper behind an OpenAI-compatible server; Ollama does the *text* stage.
- **Calling Groq or NIM directly from a route.** Everything goes through the provider registry, or it is not switchable and the Lab cannot see it.
- **Per-chunk transcript polishing.** Destroys context, multiplies latency, reads worse than raw. Polish once, at the end.
- **SSE or WebSockets for the boardroom.** One worker, eight threads. Polling is correct here.
- **Running transcription jobs without the semaphore.** Three concurrent uploads would occupy all three executor threads and stop every brief in the system.
- **Storing a `tokens` integer on `Talent`.** The ledger is the truth; the balance is derived.
- **A nightly cron for idle token accrual.** It is a pure function of `last_assigned_at`.
- **Letting the LLM pick the talent.** Deterministic scoring picks; the model writes the rationale.
- **Deleting the browser Web Speech fallback** because a better engine exists. It is the only tier that survives a dead connection.
- **Adding LangGraph or CrewAI.** Four agents, linear hand-offs. Not yet.
- **Refactoring internal auth in the same PR as the talent portal.**
- **Treating fuzzy matching as permission to auto-attach an ambiguous meeting.** Zero or multiple matches always fall through to a human.

---

## 8. When to stop and ask

Stop and ask the human rather than guessing when:

- A change would break one of the §2 invariants.
- The blueprint and the code disagree about what already exists. **The code wins; report the discrepancy.**
- A WP's dependency is not merged.
- A schema change cannot be made additively.
- Something touches money, client contact details, legal or consent wording, or a talent's rejection.
- A vendor API behaves differently from the blueprint's description. The vendor details were accurate as of July 2026 and may have moved — note it explicitly rather than working around it silently.
