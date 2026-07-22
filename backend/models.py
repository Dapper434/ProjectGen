from sqlalchemy import Column, Integer, String, Text, ForeignKey, JSON, DateTime, Boolean
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
