# FactoryOS — Pitch Prep / System Understanding

Working doc to help answer the judging criteria in [judging.md](judging.md). Everything below is
grounded in the actual code (`backend/`, `frontend/`) as of 2026-07-22 — not aspirational. Places
where you need to supply real-world detail (e.g. exact numbers from your own experience shadowing
the agency) are marked `TODO`.

---

## 1. One-liner

FactoryOS is an internal tool for a creative/communications agency (GDF Kenya) that turns raw
client-meeting transcripts into structured, agency-ready **Production Briefs** and **Client
Proposals** using an LLM pipeline, with a human Account Manager approval gate before anything
reaches a client.

It is not a chatbot and not client-facing — it's a producer/AM workflow tool that sits *between*
"we had a meeting" and "here's a polished document," a step that today is done by hand.

---

## 2. Problem statement

At a comms agency, every engagement runs through the same manual bottleneck:

1. A producer sits in (or listens back to) a client intake call.
2. They hand-write a Production Brief — objectives, deliverables, timeline, budget, risks — by
   re-reading notes or re-listening to the recording.
3. A second "brief review" meeting happens where the client changes scope, answers open questions,
   or adds requirements.
4. The producer has to reconcile the *new* meeting against the *old* brief, cross-reference the
   agency rate card and past project pricing patterns by memory/spreadsheet, and hand-write a full
   Client Proposal with a pricing table.
5. This entire translation loop repeats **every round**, for **every client**, and the only record
   of "what changed and why" lives in someone's head or a Slack thread.

The cost isn't the meetings — it's the hours of manual write-up between meetings, done by people
whose actual value-add is strategic thinking, not transcription. It's also inconsistent: brief
quality depends on who wrote it and how much they remembered.

`TODO`: this is where your Mike-shadowing numbers go — how long did the write-up actually take
him for one round, and how many rounds does a typical engagement go through? That real number is
far more persuasive than anything below.

---

## 3. The solution

FactoryOS replaces the manual write-up step with a **two-stage agent pipeline plus a mandatory
human approval gate** — it automates the translation, not the judgment:

1. **Producer uploads Transcript 1** (client intake call) → **Brief Generator** agent produces a
   structured Production Brief in seconds (objectives, audience, deliverables, timeline, budget,
   stakeholders, risks, open questions — nothing invented, gaps are explicitly flagged as
   "needs follow-up" rather than guessed).
2. Optionally, more intake-round transcripts can **refine** that same brief (targeted edits, not a
   rewrite) before the engagement is ready to move on — real engagements aren't always one call.
3. **Producer uploads Transcript 2** (brief-review meeting) → a **Signal Extraction** step first
   distills the noisy transcript into decisions / new requirements / budget & timeline signals /
   creative feedback / action items / resolved & unresolved questions, discarding small talk and
   crosstalk. A **Proposal Generator** agent then merges the original brief with those signals,
   the agency's live rate card, and both agency-wide and this-specific-client's past-project
   history into one coherent, priced Client Proposal — every change from the brief is logged in an
   explicit changelog, nothing is silently overwritten.
4. **Account Manager reviews.** They can **Approve** it, or **send it back with notes** — a
   Revision agent applies *only* the requested change (copy-everything-else-verbatim), never a
   silent full rewrite. Nothing reaches a client without this human sign-off.
5. Both documents export to client-ready **PDF** (WeasyPrint).

---

## 4. How it works (pipeline / state machine)

Each `Engagement` (one client relationship, one round of work) moves through:

```
awaiting_transcript → brief_ready → awaiting_review_transcript → proposal_ready → in_review → approved
```

- `awaiting_transcript`: nothing uploaded yet.
- `brief_ready`: Brief Generator has run; can accept more transcripts to refine the brief, or an
  explicit "Move to Proposal Stage" action advances it.
- `awaiting_review_transcript` → `proposal_ready`: Proposal Generator has run.
- `in_review`: with the Account Manager; can bounce back to `proposal_ready` via a revision.
- `approved`: done — and can spin off a new engagement ("Start Next Round for {client}") for the
  next phase of work with the same client.

Under the hood (`backend/agents.py`, `backend/app.py`):

- **LLM**: NVIDIA NIM, model `nvidia/nemotron-3-super-120b-a12b` (a reasoning model) — real API
  calls, not a mock, via `NIM_API_KEY`.
- **Structured output, validated**: every agent call is constrained to a Pydantic schema
  (`ProductionBriefSchema`, `SignalExtractionSchema`, `ProposalSchema`). If validation fails, the
  system automatically retries once with the model's reasoning turned up (`enable_thinking: full`)
  and the validation error fed back in-context, before falling back to a visible error state —
  never a silent bad document.
- **Reasoning-effort tiering for cost/latency**: pure extraction calls run with reasoning off,
  synthesis calls (pricing math, merging signals) run with light reasoning, and full reasoning is
  reserved as the retry-escalation path rather than the default for every call.
- **No wasted generation**: the LLM only ever produces structured JSON — the human-readable
  Markdown/PDF documents are rendered deterministically in Python from that JSON, so the model
  never burns tokens re-authoring a duplicate prose document.
- **Async by default**: uploads and revisions run in a background thread pool; the API returns
  immediately and the UI polls `is_processing` — producers aren't stuck on a blocking spinner.
- **Continuity context**: proposal/brief generation is fed both a generic "past projects" reference
  library and this specific client's own engagement history, so a repeat client gets consistent
  scoping/pricing instead of a cold start every time.
- **Audit trail**: every agent action (which agent, what triggered it, a reasoning summary, tokens
  used) is logged to `AgentEvent` and shown as an activity feed — an AM can see *why* a document
  looks the way it does.

---

## 5. Core features (what a demo should show)

- Brief generation from a raw transcript.
- Multi-round brief refinement (more than one intake call before scoping is locked).
- Proposal generation that reconciles a brief + a second messy transcript + rate card + past-work
  patterns into one priced document.
- Account Manager review loop: approve, or send back with notes for a targeted revision.
- Full changelog / "what changed since the brief" transparency, carried into a "Carry Into Next
  Meeting" view.
- Client 360 view (`/clients/:id`): every engagement for a client, rollup pipeline/revenue stats,
  relationship-wide open items.
- Admin "Agency Pulse" analytics (`/analytics`, Admin role only): pipeline funnel, pipeline value
  vs. approved revenue, work-type mix, turnaround time per pipeline hop, send-back/friction rate,
  agency-wide recent activity.
- Global search across clients/engagements/briefs/proposals.
- PDF export of both documents.
- Three roles: Producer, Account Manager, Admin.

---

## 6. Tech & AI use (for "quality of implementation" / "AI use")

- **Backend**: Flask + SQLAlchemy + SQLite, Pydantic for schema validation, cookie-session auth.
- **Frontend**: React + Vite + Tailwind.
- **AI**: NVIDIA NIM hosted Nemotron reasoning model, called directly (no agent framework) with
  explicit system/user prompts per stage, structured-JSON contracts, validation-driven retry with
  reasoning escalation, and a deliberate reasoning-effort budget per call type (see §4). This is a
  "know exactly what each call is for" design, not a single do-everything agent loop — each stage
  (brief, signal extraction, proposal, revision, refinement) is its own narrowly-scoped prompt with
  its own schema, which is what makes the "copy verbatim unless explicitly asked to change it"
  revision behavior reliable.

---

## 7. Practicality & real-world fit

- Built against a real agency's actual workflow (GDF Kenya) and real seeded scenarios (KCB Bank
  Group, Safaricom, EABL) with realistic rate cards and past-project patterns, not a generic demo.
- Human approval is structurally required before anything is client-facing — the tool accelerates
  the grunt work, it doesn't remove the accountable human from the loop.
- Live LLM key, not a stub — the demo reflects real model latency/behavior, not canned output.

`ASSUMPTIONS.md` documents deliberate prototype shortcuts (cookie-based auth instead of full
OAuth/multi-tenant isolation, SQLite over a production DB, JSON columns instead of full
normalization) — worth having a one-line answer ready ("what would you harden first for
production") rather than treating it as a gap you didn't think about.

---

## 8. Innovation / what's actually clever here

Things that are easy to undersell in a demo but are the real engineering substance:

- **Targeted-edit revision pattern**: the revision/refinement agents are prompted to copy
  everything verbatim except the specific field the change touches, with an explicit
  self-check instruction ("a response whose changelog is missing the new entry is wrong —
  re-check before responding"). This is what stops "AM asks for one small pricing tweak" from
  turning into "the whole proposal gets silently reworded."
- **Signal extraction as its own stage**: rather than feeding a raw, noisy transcript straight into
  proposal generation, there's a dedicated distillation step that explicitly buckets ambiguity into
  "flagged unclear" instead of letting the model guess and move on.
- **Deterministic rendering**: separating "what the model decides" (structured JSON) from "how it's
  displayed" (Python-rendered Markdown/PDF) — removes an entire class of latency/cost and drift
  between what's on screen and what's in the database.
- **Relationship memory**: a client's own history, not just a generic reference library, is fed
  forward — repeat engagements get continuity instead of a blank slate.

---

## 9. Potential impact

The concrete, demoable numbers live behind `GET /api/analytics` (`Analytics.jsx`, "Agency Pulse"):

- **Turnaround time per pipeline hop** — transcript→brief, brief→proposal, proposal→approval
  (average hours).
- **Pipeline value vs. approved revenue** (KES), computed from live proposal pricing.
- **Send-back / friction rate** — share of proposals that needed at least one AM-requested
  revision.
- **Work-type mix** and **pipeline funnel** (count of engagements per stage).

Pull the live numbers from your own seeded/demo data right before presenting — they'll be more
convincing than a static claim, and they update as you use the app.

Framed for impact: less producer time on transcription-to-document translation → more time on
strategic client work and change management, which is the agency's actual value proposition (see
README.md's framing: "time lost to write-ups is time lost to strategic thinking").

---

## 10. Known limitations (have an honest answer ready)

- Auth is a simple username/password + cookie session for three demo users — no real multi-tenant
  isolation, no OAuth. Deliberate prototype scope, documented in `ASSUMPTIONS.md`.
- SQLite + JSON columns, not a normalized production schema — fine for a single-agency prototype,
  wouldn't scale to multi-tenant SaaS as-is.
- Schema migrations are a hand-rolled idempotent script (`backend/migrate_schema.py`), not Alembic.
- Analytics endpoint access is gated only in the frontend (route/nav check), not the API itself —
  acceptable for a single-agency internal tool, not for anything exposed beyond it.
- No automated test suite beyond a manual PDF-generation script (`backend/test_pdf_gen.py`).

If asked "what would you build next" — multi-tenant auth, a real task queue instead of an in-process
thread pool for agent runs, and API-level role enforcement are the honest next three.

---

## 11. Suggested problem/solution framing for slides

- **Problem** (short, story form): a producer spends hours turning one client call into a brief,
  then does it *again* reconciling a second call into a proposal — every round, every client,
  translation work eating time that should go to strategy. `TODO`: anchor with your real timing
  number from watching Mike do this.
- **Solution** (one sentence): FactoryOS turns those two translation steps into a two-agent
  pipeline with a mandatory human approval gate, so producers upload a transcript instead of
  writing a document.
- **Core features to name** (3-4 max, not the whole list above): brief generation, proposal
  generation reconciling brief + new signals + rate card + history, AM approve/revise loop,
  PDF export.
- **Live demo path**: mirrors `README.md` §"Demo Instructions" — Producer uploads transcript 1
  (brief), uploads transcript 2 (proposal), logs out, AM logs in and approves. Under 2 minutes.
