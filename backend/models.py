from sqlalchemy import Column, Integer, String, Text, ForeignKey, JSON, DateTime, Boolean, Float, Index, UniqueConstraint
from sqlalchemy.orm import relationship
import datetime
from database import Base

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True)
    password_hash = Column(String(128))
    role = Column(String(20)) # 'Producer' or 'Account Manager'

class Client(Base):
    __tablename__ = 'clients'
    id = Column(Integer, primary_key=True)
    name = Column(String(100))
    industry = Column(String(100))
    notes = Column(Text)
    contact_email = Column(String(200))   # WP-12: required before a proposal can be emailed
    contact_name = Column(String(120))

class Engagement(Base):
    __tablename__ = 'engagements'
    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey('clients.id'))
    status = Column(String(50)) # awaiting_transcript | brief_ready | awaiting_review_transcript | proposal_ready | in_review | approved
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    is_processing = Column(Boolean, default=False)
    processing_error = Column(Text)

    client = relationship("Client", backref="engagements")

class Transcript(Base):
    __tablename__ = 'transcripts'
    id = Column(Integer, primary_key=True)
    engagement_id = Column(Integer, ForeignKey('engagements.id'))
    kind = Column(String(50)) # client_meeting | brief_review_meeting
    raw_text = Column(Text)
    uploaded_at = Column(DateTime, default=datetime.datetime.utcnow)
    uploaded_by = Column(Integer, ForeignKey('users.id'))
    meeting_date = Column(String(100))       # agent-extracted, only when explicitly stated in the transcript
    duration_minutes = Column(Integer)       # agent-extracted, only when explicitly stated
    attendees = Column(JSON)                 # list of strings
    summary = Column(Text)                   # short agent-generated recap of this specific meeting

class Brief(Base):
    __tablename__ = 'briefs'
    id = Column(Integer, primary_key=True)
    engagement_id = Column(Integer, ForeignKey('engagements.id'))
    transcript_id = Column(Integer, ForeignKey('transcripts.id'))
    structured_json = Column(JSON)
    rendered_markdown = Column(Text)
    work_type = Column(String(50))
    version = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    completeness = Column(JSON)  # cached RAG completeness-check result, see rag.py

class Proposal(Base):
    __tablename__ = 'proposals'
    id = Column(Integer, primary_key=True)
    engagement_id = Column(Integer, ForeignKey('engagements.id'))
    brief_id = Column(Integer, ForeignKey('briefs.id'))
    review_transcript_id = Column(Integer, ForeignKey('transcripts.id'), nullable=True)
    structured_json = Column(JSON)
    rendered_markdown = Column(Text)
    pricing_line_items = Column(JSON)
    status = Column(String(50)) # draft | in_review | approved
    version = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    completeness = Column(JSON)  # cached RAG completeness-check result, see rag.py

class RateCardItem(Base):
    __tablename__ = 'rate_card_items'
    id = Column(Integer, primary_key=True)
    category = Column(String(50))
    description = Column(String(200))
    unit = Column(String(50))
    rate_kes = Column(Integer)

class PastProject(Base):
    __tablename__ = 'past_projects'
    id = Column(Integer, primary_key=True)
    client_type = Column(String(50))
    work_type = Column(String(50))
    summary = Column(Text)
    deliverables_used = Column(Text) # Stored as JSON or comma separated
    typical_pricing_notes = Column(Text)

class RequirementDocument(Base):
    """Agency-uploaded authoritative reference material describing what a complete
    Production Brief / Client Proposal must contain — the corpus the simple RAG
    completeness check (see rag.py) retrieves against. A global reference table like
    RateCardItem/PastProject, not tied to any one engagement."""
    __tablename__ = 'requirement_documents'
    id = Column(Integer, primary_key=True)
    title = Column(String(200))
    doc_type = Column(String(50))  # 'brief' | 'proposal' | 'general' (applies to both)
    raw_text = Column(Text)
    is_active = Column(Boolean, default=True)  # soft-delete — this app never hard-deletes
    uploaded_at = Column(DateTime, default=datetime.datetime.utcnow)
    uploaded_by = Column(Integer, ForeignKey('users.id'))
    # Editable in place from the Playbook. Unlike AuthoritativeDoc these are not
    # versioned — they are a free-text corpus, not a pinned agent instruction —
    # so the audit trail is just "who last touched it, when".
    updated_at = Column(DateTime)
    updated_by = Column(Integer, ForeignKey('users.id'))

class ReferenceDocument(Base):
    """Optional engagement-scoped reference material (proposal templates, client RFPs,
    brand/background docs) fed INTO brief/proposal generation for structure and content
    enrichment. The input-side counterpart of RequirementDocument, which only grades
    output after generation."""
    __tablename__ = 'reference_documents'
    id = Column(Integer, primary_key=True)
    engagement_id = Column(Integer, ForeignKey('engagements.id'))
    title = Column(String(200))
    purpose = Column(String(50))  # 'structure' (template/example) | 'content' (background material)
    raw_text = Column(Text)
    is_active = Column(Boolean, default=True)  # soft-delete — this app never hard-deletes
    uploaded_at = Column(DateTime, default=datetime.datetime.utcnow)
    uploaded_by = Column(Integer, ForeignKey('users.id'))

class InboundTranscript(Base):
    """A meeting transcript pushed into the system automatically (currently only by
    the Fathom webhook, see fathom.py) rather than pasted in by a user. Lands in the
    Transcript Inbox where it can be assigned to a teammate, attached to an
    engagement (which creates a normal Transcript row and kicks off the same agent
    pipeline as a manual upload), or dismissed. When the meeting title confidently
    matches exactly one client, the webhook attaches and processes it immediately —
    so the brief is already waiting when someone opens the app."""
    __tablename__ = 'inbound_transcripts'
    id = Column(Integer, primary_key=True)
    source = Column(String(20), default='fathom')
    external_id = Column(String(100), unique=True)  # Fathom recording_id — dedupes webhook retries
    title = Column(String(300))
    share_url = Column(String(500))
    recorded_by = Column(String(200))               # name/email of the Fathom user who recorded
    meeting_date = Column(String(100))
    duration_minutes = Column(Integer)
    attendees = Column(JSON)                        # list of strings
    is_external_meeting = Column(Boolean)           # False = internal-only invitees (likely not client work)
    raw_text = Column(Text)
    summary = Column(Text)                          # Fathom's own meeting summary, if sent
    status = Column(String(20), default='pending')  # pending | processed | dismissed
    assigned_to = Column(Integer, ForeignKey('users.id'), nullable=True)
    engagement_id = Column(Integer, ForeignKey('engagements.id'), nullable=True)  # set once attached
    transcript_id = Column(Integer, ForeignKey('transcripts.id'), nullable=True)  # the Transcript created on attach
    auto_matched = Column(Boolean, default=False)   # True when the webhook attached it without a human
    received_at = Column(DateTime, default=datetime.datetime.utcnow)


class Talent(Base):
    """The agency's crew bench — freelancers and staff the Resource Planner draws
    from once a client accepts a proposal (Part 2 of the pipeline). A global
    reference table like RateCardItem/PastProject, seeded via seed_talents.py."""
    __tablename__ = 'talents'
    id = Column(Integer, primary_key=True)
    name = Column(String(100))
    title = Column(String(100))          # e.g. 'Video Producer', 'Creative Director'
    skills = Column(JSON)                # list of skill phrases, matched against proposal deliverables
    day_rate_kes = Column(Integer)
    availability = Column(String(20), default='available')  # 'available' | 'on_project'
    available_from = Column(String(50))  # human-readable, only when on_project
    location = Column(String(100))
    years_experience = Column(Integer)
    highlight = Column(Text)             # one-line credential shown on the talent card
    is_active = Column(Boolean, default=True)  # soft-delete — this app never hard-deletes

    # --- WP-9 additions -----------------------------------------------------
    # Added as nullable columns rather than re-modelling this table: staffing.py
    # and seed_talents.py already depend on the shape above, and the blueprint's
    # own §1.8 note says extend the existing Part 2 subsystem additively.
    # Field mapping for anyone reading the WP-9 spec: `full_name` is `name`,
    # `discipline` is `title`, `city` is `location`, `bio` is `highlight`.
    email = Column(String(200))
    phone = Column(String(40))
    engagement_type = Column(String(20), default='contract')  # inhouse | contract
    status = Column(String(20), default='active')             # active | paused | archived
    seniority = Column(String(20))                            # junior | mid | senior | lead
    avatar_url = Column(String(300))
    last_assigned_at = Column(DateTime)   # denormalised; drives idle-token accrual
    avg_rating = Column(Float)            # denormalised from completed assignments
    notes = Column(Text)                  # INTERNAL — never exposed to the talent
    portal_password_hash = Column(String(200))   # WP-11; null until they register or redeem an invite
    portal_invited_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    # 'self' when the talent registered themselves through the portal, 'agency'
    # (or NULL, for every row that predates open sign-up) when someone at GDF
    # added them. Casting does not read this — it is a curation signal for the
    # bench, so a producer can tell a vetted crew member from a walk-in.
    signup_source = Column(String(20))

    # Named explicitly: SQLite batch migrations cannot alter an unnamed constraint.
    __table_args__ = (UniqueConstraint('email', name='uq_talent_email'),)


class Skill(Base):
    __tablename__ = 'skills'
    id = Column(Integer, primary_key=True)
    name = Column(String(80), unique=True, nullable=False)
    category = Column(String(40))


class TalentSkill(Base):
    """A skill claimed by (or proven for) one talent.

    `verified_by_enrollment_id` is what lets the Casting Agent's hard filter tell
    a claimed skill from a certified one."""
    __tablename__ = 'talent_skills'
    id = Column(Integer, primary_key=True)
    talent_id = Column(Integer, ForeignKey('talents.id'), index=True)
    skill_id = Column(Integer, ForeignKey('skills.id'), index=True)
    level = Column(Integer, default=3)     # 1-5
    verified_by_enrollment_id = Column(Integer, ForeignKey('certification_enrollments.id'), nullable=True)

    __table_args__ = (UniqueConstraint('talent_id', 'skill_id', name='uq_talent_skill'),)


class PortfolioItem(Base):
    __tablename__ = 'portfolio_items'
    id = Column(Integer, primary_key=True)
    talent_id = Column(Integer, ForeignKey('talents.id'), index=True)
    title = Column(String(200))
    role = Column(String(120))
    client_name = Column(String(120))
    year = Column(Integer)
    media_url = Column(String(400))
    link = Column(String(400))
    description = Column(Text)
    is_public = Column(Boolean, default=True)
    order_index = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class Certification(Base):
    __tablename__ = 'certifications'
    id = Column(Integer, primary_key=True)
    key = Column(String(60), unique=True, nullable=False)
    name = Column(String(160))
    provider = Column(String(120))
    category = Column(String(40))
    token_award = Column(Integer, default=25)
    validity_months = Column(Integer, default=24)
    grants_skill_id = Column(Integer, ForeignKey('skills.id'), nullable=True)
    is_mock = Column(Boolean, default=True)


class CertificationEnrollment(Base):
    __tablename__ = 'certification_enrollments'
    id = Column(Integer, primary_key=True)
    talent_id = Column(Integer, ForeignKey('talents.id'), index=True)
    certification_id = Column(Integer, ForeignKey('certifications.id'), index=True)
    status = Column(String(20), default='in_progress')   # in_progress | completed | failed | expired
    enrolled_at = Column(DateTime, default=datetime.datetime.utcnow)
    completed_at = Column(DateTime)
    expires_at = Column(DateTime)
    score = Column(Float)
    attempts = Column(Integer, default=0)
    evidence_url = Column(String(400))
    is_mock = Column(Boolean, default=True)
    completed_by = Column(Integer, ForeignKey('users.id'), nullable=True)


class Event(Base):
    __tablename__ = 'events'
    id = Column(Integer, primary_key=True)
    name = Column(String(200))
    kind = Column(String(40))
    starts_at = Column(DateTime)
    ends_at = Column(DateTime)
    token_award = Column(Integer, default=10)
    checkin_code = Column(String(40))
    location = Column(String(160))


class EventAttendance(Base):
    __tablename__ = 'event_attendance'
    id = Column(Integer, primary_key=True)
    event_id = Column(Integer, ForeignKey('events.id'), index=True)
    talent_id = Column(Integer, ForeignKey('talents.id'), index=True)
    checked_in_at = Column(DateTime, default=datetime.datetime.utcnow)
    method = Column(String(20), default='code')   # code | admin

    __table_args__ = (UniqueConstraint('event_id', 'talent_id', name='uq_event_attendance'),)


class AvailabilityBlock(Base):
    """Absence of data means available. Requiring talent to declare positive
    availability produces an empty bench within a fortnight; requiring them to
    declare *un*availability matches how freelancers actually behave."""
    __tablename__ = 'availability_blocks'
    id = Column(Integer, primary_key=True)
    talent_id = Column(Integer, ForeignKey('talents.id'), index=True)
    start_at = Column(DateTime, nullable=False)
    end_at = Column(DateTime, nullable=False)
    kind = Column(String(20), nullable=False)      # available | busy | tentative | leave
    source = Column(String(20), default='manual')  # manual | ics | assignment
    ref_id = Column(Integer)                       # assignment id when source='assignment'
    note = Column(String(200))


class TokenLedger(Base):
    """Append-only. **The balance is derived; there is deliberately no `tokens`
    column on Talent.** A stored balance drifts, cannot be audited, and cannot
    answer "why do I have 74 tokens?" — the first question every talent asks.

    The unique constraint is the idempotency guard: a retried request cannot
    award the same certification twice."""
    __tablename__ = 'token_ledger'
    id = Column(Integer, primary_key=True)
    talent_id = Column(Integer, ForeignKey('talents.id'), index=True, nullable=False)
    delta = Column(Integer, nullable=False)        # signed
    reason = Column(String(40), nullable=False)
    ref_type = Column(String(30))                  # event | enrollment | assignment | manual
    ref_id = Column(Integer)
    note = Column(String(200))
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    created_by = Column(Integer, ForeignKey('users.id'), nullable=True)
    expires_at = Column(DateTime)

    __table_args__ = (
        UniqueConstraint('talent_id', 'reason', 'ref_type', 'ref_id', name='uq_token_award'),
    )


class Assignment(Base):
    """One talent's place on one engagement — WP-10's lifecycle."""
    __tablename__ = 'assignments'
    id = Column(Integer, primary_key=True)
    engagement_id = Column(Integer, ForeignKey('engagements.id'), index=True)
    talent_id = Column(Integer, ForeignKey('talents.id'), index=True)
    role = Column(String(120))
    # shortlisted | offered | accepted | declined | cancelled | completed | no_show
    status = Column(String(20), default='shortlisted')
    rate_kes = Column(Integer)
    start_at = Column(DateTime)
    end_at = Column(DateTime)
    score = Column(Float)                  # the deterministic score that ranked them
    score_breakdown = Column(JSON)
    rationale = Column(Text)               # the model's human-readable "why this line-up"
    concerns = Column(Text)
    offered_at = Column(DateTime)
    responded_at = Column(DateTime)
    completed_at = Column(DateTime)
    rating = Column(Integer)
    created_by = Column(Integer, ForeignKey('users.id'), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class CastingRun(Base):
    __tablename__ = 'casting_runs'
    id = Column(Integer, primary_key=True)
    engagement_id = Column(Integer, ForeignKey('engagements.id'), index=True)
    roles = Column(JSON)                   # the role briefs the run was asked to fill
    status = Column(String(20), default='running')
    result = Column(JSON)                  # ranked shortlist per role, with breakdowns
    rationale = Column(Text)
    tokens_used = Column(Integer)
    created_by = Column(Integer, ForeignKey('users.id'), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class StaffingPlan(Base):
    """The production plan assembled when a client accepts a proposal: who's on the
    crew (matched from the Talent pool), what tools/equipment the deliverables call
    for, and the kickoff checklist. Built deterministically by staffing.py — not an
    LLM call — so the result is instant and repeatable."""
    __tablename__ = 'staffing_plans'
    id = Column(Integer, primary_key=True)
    engagement_id = Column(Integer, ForeignKey('engagements.id'))
    proposal_id = Column(Integer, ForeignKey('proposals.id'))
    plan = Column(JSON)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class AgentEvent(Base):
    __tablename__ = 'agent_events'
    id = Column(Integer, primary_key=True)
    engagement_id = Column(Integer, ForeignKey('engagements.id'))
    agent = Column(String(50))
    trigger = Column(String(100))
    reasoning_summary = Column(Text)
    action = Column(String(200))
    tokens_used = Column(Integer)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    # JSON list of {"key","scope","scope_id","version","label"} — which authoritative
    # document versions this run actually read. Nullable: older rows and any run that
    # touched no authoritative data (e.g. before WP-1 seeding) simply have none. See
    # authoritative.py build_refs().
    authoritative_refs = Column(Text)


class RuntimeSetting(Base):
    """The currently selected driver for one pluggable capability — WP-2. Sits
    between the env default and a per-request override in the resolution order
    (see providers/registry.py get()). Changing a row here takes effect on the
    next request with no restart."""
    __tablename__ = 'runtime_settings'
    id = Column(Integer, primary_key=True)
    capability = Column(String(40), unique=True, nullable=False)
    driver_key = Column(String(40), nullable=False)
    options = Column(Text)                  # JSON
    updated_by = Column(Integer, ForeignKey('users.id'), nullable=True)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow)


class SettingChange(Base):
    """Append-only audit of every driver switch, so "who moved us to the local
    model on Tuesday, and why" is answerable. Never updated, never deleted."""
    __tablename__ = 'setting_changes'
    id = Column(Integer, primary_key=True)
    capability = Column(String(40))
    from_driver = Column(String(40))
    to_driver = Column(String(40))
    options = Column(Text)                  # JSON
    changed_by = Column(Integer, ForeignKey('users.id'), nullable=True)
    changed_at = Column(DateTime, default=datetime.datetime.utcnow)
    reason = Column(String(200))


class ComparisonRun(Base):
    """One Lab bake-off: the same input pushed through several drivers so they can
    be compared side by side before committing to one (WP-2 §2.6)."""
    __tablename__ = 'comparison_runs'
    id = Column(Integer, primary_key=True)
    capability = Column(String(40))         # 'stt_batch' | 'agent_llm'
    input_kind = Column(String(20))         # 'audio' | 'transcript'
    input_ref = Column(String(300))         # file path or transcript id
    input_meta = Column(Text)               # JSON: duration, size, source
    status = Column(String(20), default='running')  # running | done | error
    created_by = Column(Integer, ForeignKey('users.id'), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class ComparisonResult(Base):
    """One driver's column in a ComparisonRun."""
    __tablename__ = 'comparison_results'
    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey('comparison_runs.id'), index=True)
    driver_key = Column(String(40))
    label = Column(String(60))
    options = Column(Text)                  # JSON
    status = Column(String(20))             # pending | ok | error
    output = Column(Text)
    error = Column(Text)
    latency_ms = Column(Integer)
    word_count = Column(Integer)
    tokens_used = Column(Integer)
    est_cost_usd = Column(Float)
    metrics = Column(Text)                  # JSON: diff stats vs the reference column


class RecordingJob(Base):
    """A post-meeting recording being turned into a transcript — WP-6.

    The Recording Studio deliberately has no brief agent of its own: it produces
    text and posts it to the transcript endpoint that already exists, so an
    uploaded-recording brief and a Fathom brief are the same object from the
    same code path. One pipeline, four inlets."""
    __tablename__ = 'recording_jobs'
    id = Column(Integer, primary_key=True)
    engagement_id = Column(Integer, ForeignKey('engagements.id'), nullable=True)
    client_id = Column(Integer, ForeignKey('clients.id'), nullable=True)
    title = Column(String(200))
    source_path = Column(String(400))       # under UPLOAD_DIR; deleted per retention policy
    source_name = Column(String(260))
    source_bytes = Column(Integer)
    duration_sec = Column(Integer)
    mime = Column(String(60))
    driver_key = Column(String(40), nullable=False)   # frozen at submit, not resolved later
    driver_options = Column(Text)
    polish_driver = Column(String(40))
    language = Column(String(10), default='en')
    # queued | normalising | transcribing | polishing | ready | attached | failed | cancelled
    status = Column(String(20), default='queued')
    pieces_total = Column(Integer, default=0)
    pieces_done = Column(Integer, default=0)
    progress_pct = Column(Integer, default=0)
    raw_text = Column(Text)
    polished_text = Column(Text)
    edited_text = Column(Text)              # human edits — this is what actually gets attached
    latency_ms = Column(Integer)
    error = Column(Text)
    attached_transcript_id = Column(Integer, ForeignKey('transcripts.id'), nullable=True)
    comparison_run_id = Column(Integer, ForeignKey('comparison_runs.id'), nullable=True)
    created_by = Column(Integer, ForeignKey('users.id'), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    completed_at = Column(DateTime)


class RecordingSegment(Base):
    """One timestamped chunk of a RecordingJob's transcript.

    Stored rather than only the joined text: it buys click-to-timestamp in the
    review UI, and lets a failed job resume from `pieces_done` instead of
    re-transcribing from zero."""
    __tablename__ = 'recording_segments'
    id = Column(Integer, primary_key=True)
    job_id = Column(Integer, ForeignKey('recording_jobs.id'), index=True)
    seq = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    start_ms = Column(Integer)
    end_ms = Column(Integer)
    speaker = Column(String(40))
    confidence = Column(Float)

    __table_args__ = (
        UniqueConstraint('job_id', 'seq', name='uq_recording_segment_seq'),
    )


class BoardroomSession(Base):
    """A live client meeting being transcribed and coverage-checked — WP-7.

    `protocol_version` is FROZEN at session start: every coverage check resolves
    that exact version, so editing the agenda mid-meeting cannot change the
    standard a live session is judged against."""
    __tablename__ = 'boardroom_sessions'
    id = Column(Integer, primary_key=True)
    engagement_id = Column(Integer, ForeignKey('engagements.id'), nullable=True)  # nullable: new-business pitch
    client_id = Column(Integer, ForeignKey('clients.id'), nullable=True)
    title = Column(String(200))
    meeting_kind = Column(String(40), default='intake')   # intake | review | internal | pitch
    protocol_scope = Column(String(20))
    protocol_version = Column(Integer)
    status = Column(String(20), default='live')           # live | ended | promoted | discarded
    stt_driver = Column(String(40))
    coverage_driver = Column(String(40))
    language = Column(String(10), default='en')
    consent_ack_by = Column(Integer, ForeignKey('users.id'), nullable=True)
    consent_ack_at = Column(DateTime)
    planned_minutes = Column(Integer)                     # drives the T-5 nudge
    started_at = Column(DateTime, default=datetime.datetime.utcnow)
    ended_at = Column(DateTime)
    audio_seconds = Column(Integer, default=0)
    raw_transcript = Column(Text)                         # verbatim — the evidence
    polished_transcript = Column(Text)                    # derived — what the brief agent reads
    promoted_transcript_id = Column(Integer, ForeignKey('transcripts.id'), nullable=True)
    created_by = Column(Integer, ForeignKey('users.id'), nullable=True)


class TranscriptSegment(Base):
    """One captured utterance in a boardroom session. `seq` is monotonic per
    session — the frontend polls on it rather than holding a socket open."""
    __tablename__ = 'transcript_segments'
    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey('boardroom_sessions.id'), index=True)
    seq = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    speaker_label = Column(String(40))
    source = Column(String(20), default='stt')            # stt | typed | browser_stt
    started_ms = Column(Integer)
    ended_ms = Column(Integer)
    confidence = Column(Float)
    provider = Column(String(40))
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    __table_args__ = (
        UniqueConstraint('session_id', 'seq', name='uq_transcript_segment_seq'),
    )


class CoverageCheck(Base):
    """Whether one protocol item has been covered. `evidence` is mandatory for
    'covered' — without it the parser downgrades to 'partial', which is the only
    real defence against a model agreeing with itself."""
    __tablename__ = 'coverage_checks'
    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey('boardroom_sessions.id'), index=True)
    item_key = Column(String(60), nullable=False)         # from the protocol JSON, not a table
    status = Column(String(12), nullable=False)           # covered | partial | missing | unknown
    evidence = Column(Text)
    evidence_seq = Column(Integer)                        # enables click-to-scroll
    confidence = Column(Float)
    suggested_prompt = Column(Text)
    is_final = Column(Boolean, default=False)
    driver_key = Column(String(40))
    checked_at = Column(DateTime, default=datetime.datetime.utcnow)


class AgentLock(Base):
    """One row per in-flight agent job — see WP-3. Replaces the single
    `Engagement.is_processing` boolean, which could only say "something is busy"
    and so serialised genuinely independent agents behind one flag, with no
    timeout if a worker died mid-call.

    Uniqueness is enforced by the database (`uq_agent_lock`), not by an
    application-level check-then-insert, so two threads racing to acquire the
    same lock cannot both win. `expires_at` makes a dead worker self-healing:
    the next acquire reaps the stale row and logs an AgentEvent.

    `Engagement.is_processing` is kept in sync as a derived convenience value so
    the existing polling/spinner code keeps working untouched."""
    __tablename__ = 'agent_locks'
    id = Column(Integer, primary_key=True)
    engagement_id = Column(Integer, ForeignKey('engagements.id'), nullable=True)
    scope = Column(String(40), nullable=False)          # brief | proposal | transcription | boardroom_coverage | casting | email_send
    ref_type = Column(String(30))                       # engagement | boardroom_session | recording_job | casting_run
    ref_id = Column(Integer)
    locked_at = Column(DateTime, default=datetime.datetime.utcnow)
    locked_by = Column(Integer, ForeignKey('users.id'), nullable=True)
    expires_at = Column(DateTime)

    __table_args__ = (
        UniqueConstraint('scope', 'ref_type', 'ref_id', name='uq_agent_lock'),
    )


class AuthoritativeDoc(Base):
    """Versioned, scoped system knowledge (prompts, rate cards, protocols, policies)
    that agents and humans both read from one place instead of code constants —
    see docs/THE_EXODUS_Master_Implementation_Blueprint.md WP-1. Documents are
    immutable: editing creates version N+1 and deactivates version N rather than
    updating `body` in place, so `AgentEvent.authoritative_refs` can answer "which
    rate card did this proposal actually use?" months later. Resolution
    (backend/authoritative.py resolve()) is most-specific-active-wins across
    scope_type: engagement overrides client overrides global — no merging."""
    __tablename__ = 'authoritative_docs'
    id = Column(Integer, primary_key=True)
    key = Column(String(60), nullable=False, index=True)
    scope_type = Column(String(20), nullable=False, default='global')  # global | client | engagement
    scope_id = Column(Integer, nullable=True)
    title = Column(String(160), nullable=False)
    fmt = Column(String(10), nullable=False, default='markdown')  # markdown | json
    body = Column(Text, nullable=False)
    version = Column(Integer, nullable=False, default=1)
    is_active = Column(Boolean, nullable=False, default=True)
    label = Column(String(40))     # optional variant tag, e.g. 'concise' — used by the Lab (WP-2)
    note = Column(Text)            # changelog line for this version
    updated_by = Column(Integer, ForeignKey('users.id'), nullable=True)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow)

    __table_args__ = (
        Index('ix_auth_lookup', 'key', 'scope_type', 'scope_id', 'is_active'),
        UniqueConstraint('key', 'scope_type', 'scope_id', 'version', name='uq_auth_doc_version'),
    )
