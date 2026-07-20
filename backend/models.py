from sqlalchemy import Column, Integer, String, Text, ForeignKey, JSON, DateTime
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
    
    client = relationship("Client", backref="engagements")

class Transcript(Base):
    __tablename__ = 'transcripts'
    id = Column(Integer, primary_key=True)
    engagement_id = Column(Integer, ForeignKey('engagements.id'))
    kind = Column(String(50)) # client_meeting | brief_review_meeting
    raw_text = Column(Text)
    uploaded_at = Column(DateTime, default=datetime.datetime.utcnow)
    uploaded_by = Column(Integer, ForeignKey('users.id'))

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
