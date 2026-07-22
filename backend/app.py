import os
from dotenv import load_dotenv

# Load backend/.env (if present) before anything reads os.environ — this must happen
# before agents.py is imported, since it reads NIM_API_KEY at module-import time.
load_dotenv()

from flask import Flask, request, jsonify, session, send_file
from flask_cors import CORS
from database import db_session, init_db
from models import User, Client, Engagement, Transcript, Brief, Proposal, RateCardItem, PastProject, AgentEvent, RequirementDocument, ReferenceDocument, InboundTranscript, Talent, StaffingPlan
from werkzeug.security import check_password_hash
from sqlalchemy import cast, String, func
from weasyprint import HTML
from concurrent.futures import ThreadPoolExecutor
import io
import html
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY') or 'super-secret-demo-key'
CORS(app, supports_credentials=True)

# Production runs behind HTTPS everywhere (Vercel rewrite -> Tailscale Funnel),
# and the Vercel proxy makes all browser traffic same-origin — so Lax + Secure
# is enough; no cross-site cookie contortions needed. Off in dev (plain http).
if os.environ.get('PRODUCTION') == '1':
    app.config.update(SESSION_COOKIE_SECURE=True, SESSION_COOKIE_SAMESITE='Lax')

@app.teardown_appcontext
def shutdown_session(exception=None):
    db_session.remove()

# ---------------------------------------------------------------------------
# Background agent processing
# ---------------------------------------------------------------------------
# Agent calls are real LLM round trips (seconds to ~1-2 minutes). Running them
# inline would block a Flask worker thread for the whole duration, so the two
# upload/review endpoints dispatch them here and return immediately; the
# frontend polls GET /api/engagements/<id> and watches `is_processing`.
#
# Rules for every function below (see SYSTEM_ANALYSIS-adjacent plan notes):
#   - only primitives (ids, strings) are passed in — never ORM objects or
#     anything tied to the request/session context, since this runs on a
#     different thread after the request has already returned.
#   - each function re-queries fresh ORM objects via `db_session`, which is
#     thread-local (no scopefunc configured in database.py), so this is safe
#     without any Flask app-context plumbing.
#   - `db_session.remove()` runs in a `finally:` — required because the pool
#     reuses OS threads across jobs, and `@app.teardown_appcontext` only fires
#     for request contexts, never for executor threads.
#   - failures are caught and written to `processing_error` instead of raised,
#     since there is no HTTP request left to receive them.
_executor = ThreadPoolExecutor(max_workers=3)


def _client_relationship_context(client_id, exclude_engagement_id):
    """Short text summary of a client's other engagements, for feeding into the brief/
    proposal prompts as continuity context — distinct from the agency-wide PastProject
    reference table, this is specific to *this* client's own history."""
    engagements = db_session.query(Engagement).filter(
        Engagement.client_id == client_id,
        Engagement.id != exclude_engagement_id
    ).order_by(Engagement.id.desc()).limit(5).all()

    lines = []
    for eng in engagements:
        brief = db_session.query(Brief).filter_by(engagement_id=eng.id).order_by(Brief.id.desc()).first()
        if not brief:
            continue
        proposal = db_session.query(Proposal).filter_by(engagement_id=eng.id).order_by(Proposal.id.desc()).first()
        work_type = (brief.work_type or 'unspecified').replace('-', ' ')
        line = f"- [{eng.status}] {work_type} engagement"
        if proposal:
            approach = (proposal.structured_json or {}).get('approach')
            if approach:
                line += f": {approach}"
        lines.append(line)

    return chr(10).join(lines)


def _reference_material_for(eng_id, query_text):
    """Excerpt block from this engagement's active ReferenceDocuments (templates, RFPs,
    background material) for feeding INTO generation prompts. Empty string when none
    exist — generation proceeds identically without them."""
    from rag import build_reference_context
    docs = db_session.query(ReferenceDocument).filter_by(
        engagement_id=eng_id, is_active=True
    ).order_by(ReferenceDocument.id).all()
    return build_reference_context(query_text, docs)


def _fail_processing(eng_id, error):
    db_session.rollback()
    eng = db_session.query(Engagement).get(eng_id)
    if eng:
        eng.is_processing = False
        eng.processing_error = str(error)
        db_session.commit()


def _process_brief_generation(eng_id, transcript_id):
    from agents import generate_brief
    try:
        eng = db_session.query(Engagement).get(eng_id)
        transcript = db_session.query(Transcript).get(transcript_id)
        client_history = _client_relationship_context(eng.client_id, exclude_engagement_id=eng_id)
        reference_material = _reference_material_for(eng_id, transcript.raw_text)

        brief_json = generate_brief(transcript.raw_text, eng.client.name, client_history=client_history, reference_material=reference_material)
        tokens = brief_json.pop('_tokens_used', 0)

        transcript.meeting_date = brief_json.get('meeting_date')
        transcript.duration_minutes = brief_json.get('duration_minutes')
        transcript.attendees = brief_json.get('attendees') or []
        transcript.summary = brief_json.get('summary')

        brief = Brief(
            engagement_id=eng_id,
            transcript_id=transcript_id,
            structured_json=brief_json,
            rendered_markdown=brief_json.get('rendered_markdown', ''),
            work_type=brief_json.get('work_type', 'unknown')
        )
        eng.status = 'brief_ready'
        eng.is_processing = False
        eng.processing_error = None
        db_session.add(brief)

        db_session.add(AgentEvent(
            engagement_id=eng_id,
            agent='Brief Generator',
            trigger='client_meeting_transcript_upload',
            reasoning_summary='Processed initial client transcript to generate structured production brief.',
            action='Created Brief',
            tokens_used=tokens
        ))
        db_session.commit()
    except Exception as e:
        _fail_processing(eng_id, f"Agent failed: {e}")
    finally:
        db_session.remove()


def _process_brief_refinement(eng_id, transcript_id):
    from agents import refine_brief
    try:
        eng = db_session.query(Engagement).get(eng_id)
        transcript = db_session.query(Transcript).get(transcript_id)
        existing_brief = db_session.query(Brief).filter_by(engagement_id=eng_id).order_by(Brief.id.desc()).first()
        if not existing_brief:
            raise RuntimeError("No existing brief to refine")

        brief_json = refine_brief(existing_brief, transcript.raw_text, eng.client.name)
        tokens = brief_json.pop('_tokens_used', 0)

        transcript.meeting_date = brief_json.get('meeting_date')
        transcript.duration_minutes = brief_json.get('duration_minutes')
        transcript.attendees = brief_json.get('attendees') or []
        transcript.summary = brief_json.get('summary')

        new_brief = Brief(
            engagement_id=eng_id,
            transcript_id=transcript_id,
            structured_json=brief_json,
            rendered_markdown=brief_json.get('rendered_markdown', ''),
            work_type=brief_json.get('work_type') or existing_brief.work_type,
            version=(existing_brief.version or 1) + 1
        )
        # Status stays 'brief_ready' — refining doesn't advance the pipeline; the
        # producer still has to explicitly move to the proposal stage.
        eng.is_processing = False
        eng.processing_error = None
        db_session.add(new_brief)

        db_session.add(AgentEvent(
            engagement_id=eng_id,
            agent='Brief Generator',
            trigger='additional_client_meeting_transcript_upload',
            reasoning_summary='Refined the production brief with an additional client meeting transcript.',
            action='Refined Brief',
            tokens_used=tokens
        ))
        db_session.commit()
    except Exception as e:
        _fail_processing(eng_id, f"Agent failed: {e}")
    finally:
        db_session.remove()


def _process_proposal_generation(eng_id, transcript_id):
    from agents import generate_proposal
    try:
        eng = db_session.query(Engagement).get(eng_id)
        transcript = db_session.query(Transcript).get(transcript_id)
        brief = db_session.query(Brief).filter_by(engagement_id=eng_id).order_by(Brief.id.desc()).first()
        if not brief:
            raise RuntimeError("No brief found for this engagement")

        past_projects = db_session.query(PastProject).limit(3).all()
        rate_card = db_session.query(RateCardItem).all()
        client_history = _client_relationship_context(eng.client_id, exclude_engagement_id=eng_id)
        reference_material = _reference_material_for(eng_id, f"{brief.rendered_markdown}\n\n{transcript.raw_text}")

        proposal_json = generate_proposal(transcript.raw_text, brief, eng.client.name, past_projects, rate_card, client_history=client_history, reference_material=reference_material)
        signal_tokens = proposal_json.pop('_signal_tokens_used', 0)
        proposal_tokens = proposal_json.pop('_proposal_tokens_used', 0)
        extracted_signals = proposal_json.get('extracted_signals', {})
        extracted_signals_markdown = proposal_json.get('extracted_signals_markdown', '')

        transcript.meeting_date = extracted_signals.get('meeting_date')
        transcript.duration_minutes = extracted_signals.get('duration_minutes')
        transcript.attendees = extracted_signals.get('attendees') or []
        transcript.summary = extracted_signals.get('summary')

        proposal = Proposal(
            engagement_id=eng_id,
            brief_id=brief.id,
            review_transcript_id=transcript_id,
            structured_json=proposal_json,
            rendered_markdown=proposal_json.get('rendered_markdown', ''),
            pricing_line_items=proposal_json.get('pricing', []),
            status='draft'
        )
        eng.status = 'proposal_ready'
        eng.is_processing = False
        eng.processing_error = None
        db_session.add(proposal)

        db_session.add(AgentEvent(
            engagement_id=eng_id,
            agent='Proposal Generator',
            trigger='review_meeting_transcript_upload',
            reasoning_summary='Combined brief, review notes, rate card, and past projects to draft a full client proposal.',
            action='Created Proposal',
            tokens_used=proposal_tokens
        ))
        db_session.add(AgentEvent(
            engagement_id=eng_id,
            agent='Signal Extractor',
            trigger='review_meeting_transcript_upload',
            reasoning_summary=extracted_signals_markdown,
            action='Extracted Meeting Signals',
            tokens_used=signal_tokens
        ))
        db_session.commit()
    except Exception as e:
        _fail_processing(eng_id, f"Agent failed: {e}")
    finally:
        db_session.remove()


def _process_proposal_revision(eng_id, proposal_id, notes):
    from agents import revise_proposal
    try:
        eng = db_session.query(Engagement).get(eng_id)
        proposal = db_session.query(Proposal).get(proposal_id)
        rate_card = db_session.query(RateCardItem).all()

        proposal_json = revise_proposal(proposal, notes, eng.client.name, rate_card)
        tokens = proposal_json.pop('_tokens_used', 0)

        new_proposal = Proposal(
            engagement_id=eng_id,
            brief_id=proposal.brief_id,
            review_transcript_id=proposal.review_transcript_id,
            structured_json=proposal_json,
            rendered_markdown=proposal_json.get('rendered_markdown', ''),
            pricing_line_items=proposal_json.get('pricing', []),
            status='in_review',
            version=proposal.version + 1
        )
        eng.status = 'in_review'
        eng.is_processing = False
        eng.processing_error = None
        db_session.add(new_proposal)

        db_session.add(AgentEvent(
            engagement_id=eng_id,
            agent='Proposal Generator',
            trigger='manager_send_back',
            reasoning_summary=f'Applied Account Manager requested changes to the existing proposal: {notes}',
            action='Revised Proposal',
            tokens_used=tokens
        ))
        db_session.commit()
    except Exception as e:
        _fail_processing(eng_id, f"Agent failed on revision: {e}")
    finally:
        db_session.remove()


def _transcript_dispatch_for(status):
    """(transcript_kind, background_task) for a new transcript landing on an
    engagement in `status`, or None if the state can't accept one.
    awaiting_transcript: first client-meeting transcript, generates the brief.
    brief_ready: a brief already exists but the producer hasn't yet moved to the
      proposal stage — another client-meeting transcript here *refines* the brief
      (multi-round intake) rather than jumping to the proposal.
    awaiting_review_transcript: the producer explicitly advanced past the brief —
      this transcript is the review meeting and generates the proposal."""
    return {
        'awaiting_transcript': ('client_meeting', _process_brief_generation),
        'brief_ready': ('client_meeting', _process_brief_refinement),
        'awaiting_review_transcript': ('brief_review_meeting', _process_proposal_generation),
    }.get(status)


# ---------------------------------------------------------------------------
# Requirements completeness check (simple RAG)
# ---------------------------------------------------------------------------

COMPLETENESS_MODELS = {'brief': Brief, 'proposal': Proposal}


def _requirement_docs_for(doc_type):
    return db_session.query(RequirementDocument).filter(
        RequirementDocument.is_active == True,  # noqa: E712
        RequirementDocument.doc_type.in_([doc_type, 'general'])
    ).all()


def _requirement_fingerprint(doc_type):
    q = db_session.query(func.count(RequirementDocument.id), func.max(RequirementDocument.id)).filter(
        RequirementDocument.is_active == True,  # noqa: E712
        RequirementDocument.doc_type.in_([doc_type, 'general'])
    )
    count, max_id = q.one()
    return {"count": count or 0, "max_id": max_id or 0}


def _process_completeness_check(doc_type, doc_id):
    from rag import check_completeness
    Model = COMPLETENESS_MODELS[doc_type]
    try:
        doc_row = db_session.query(Model).get(doc_id)
        requirement_docs = _requirement_docs_for(doc_type)
        result = check_completeness(doc_type, doc_row.rendered_markdown, requirement_docs)
        doc_row.completeness = {
            **result,
            "pending": False,
            "computed_at": datetime.now().isoformat(),
            "doc_fingerprint": _requirement_fingerprint(doc_type),
        }
        db_session.commit()
    except Exception as e:
        db_session.rollback()
        doc_row = db_session.query(Model).get(doc_id)
        if doc_row:
            doc_row.completeness = {
                "pending": False, "complete": None, "missing": [],
                "notes": f"Completeness check failed: {e}",
                "computed_at": datetime.now().isoformat(),
                "doc_fingerprint": _requirement_fingerprint(doc_type),
            }
            db_session.commit()
    finally:
        db_session.remove()


def _completeness_response(eng_id, doc_type, force):
    fingerprint = _requirement_fingerprint(doc_type)
    if fingerprint['count'] == 0:
        return jsonify({"available": False})

    Model = COMPLETENESS_MODELS[doc_type]
    doc_row = db_session.query(Model).filter_by(engagement_id=eng_id).order_by(Model.id.desc()).first()
    if not doc_row:
        return jsonify({"available": False})

    cached = doc_row.completeness or {}

    if cached.get('pending'):
        return jsonify({"available": True, "pending": True})

    has_result = 'computed_at' in cached
    stale = has_result and cached.get('doc_fingerprint') != fingerprint

    if has_result and not force and not stale:
        return jsonify({"available": True, "pending": False, "stale": False, **{k: v for k, v in cached.items() if k != 'doc_fingerprint'}})

    if has_result and not force and stale:
        return jsonify({"available": True, "pending": False, "stale": True, **{k: v for k, v in cached.items() if k != 'doc_fingerprint'}})

    # Never checked, or a forced/stale recheck was requested.
    doc_row.completeness = {"pending": True}
    db_session.commit()
    _executor.submit(_process_completeness_check, doc_type, doc_row.id)
    return jsonify({"available": True, "pending": True})


@app.route('/api/engagements/<int:eng_id>/brief/completeness', methods=['GET'])
def get_brief_completeness(eng_id):
    return _completeness_response(eng_id, 'brief', request.args.get('refresh') == '1')


@app.route('/api/engagements/<int:eng_id>/proposal/completeness', methods=['GET'])
def get_proposal_completeness(eng_id):
    return _completeness_response(eng_id, 'proposal', request.args.get('refresh') == '1')


@app.route('/api/requirements', methods=['GET', 'POST'])
def requirements_list():
    if request.method == 'POST':
        role = session.get('role')
        if role not in ('Account Manager', 'Admin'):
            return jsonify({"error": "Account Manager or Admin role required."}), 403

        user_id = session.get('user_id')
        if not user_id:
            return jsonify({"error": "Unauthorized"}), 401

        data = request.get_json(silent=True) or {}
        title = (data.get('title') or '').strip()
        doc_type = data.get('doc_type')
        raw_text = (data.get('raw_text') or '').strip()

        if doc_type not in ('brief', 'proposal', 'general'):
            return jsonify({"error": "doc_type must be one of: brief, proposal, general"}), 400
        if not title or not raw_text:
            return jsonify({"error": "Title and document text are required"}), 400

        doc = RequirementDocument(title=title, doc_type=doc_type, raw_text=raw_text, uploaded_by=user_id)
        db_session.add(doc)
        db_session.commit()
        return jsonify({"id": doc.id}), 201

    docs = db_session.query(RequirementDocument).filter_by(is_active=True).order_by(RequirementDocument.uploaded_at.desc()).all()
    return jsonify([
        {
            "id": d.id,
            "title": d.title,
            "doc_type": d.doc_type,
            "uploaded_at": d.uploaded_at.isoformat() if d.uploaded_at else None,
            "uploaded_by": (db_session.query(User).get(d.uploaded_by).username if d.uploaded_by else None),
            "length": len(d.raw_text or ''),
        } for d in docs
    ])


@app.route('/api/requirements/<int:doc_id>/deactivate', methods=['POST'])
def deactivate_requirement(doc_id):
    role = session.get('role')
    if role not in ('Account Manager', 'Admin'):
        return jsonify({"error": "Account Manager or Admin role required."}), 403

    doc = db_session.query(RequirementDocument).get(doc_id)
    if not doc:
        return jsonify({"error": "Not found"}), 404

    doc.is_active = False
    db_session.commit()
    return jsonify({"message": "Deactivated"})


# Reference documents are engagement-scoped working material (templates, client RFPs,
# background docs) that enrich generation — unlike RequirementDocuments, which grade
# output. Any logged-in role can manage them, same trust level as uploading transcripts.
@app.route('/api/engagements/<int:eng_id>/references', methods=['GET', 'POST'])
def engagement_references(eng_id):
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    eng = db_session.query(Engagement).get(eng_id)
    if not eng:
        return jsonify({"error": "Engagement not found"}), 404

    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        title = (data.get('title') or '').strip()
        purpose = data.get('purpose')
        raw_text = (data.get('raw_text') or '').strip()

        if purpose not in ('structure', 'content'):
            return jsonify({"error": "purpose must be one of: structure, content"}), 400
        if not title or not raw_text:
            return jsonify({"error": "Title and document text are required"}), 400

        doc = ReferenceDocument(engagement_id=eng_id, title=title, purpose=purpose, raw_text=raw_text, uploaded_by=user_id)
        db_session.add(doc)
        db_session.commit()
        return jsonify({"id": doc.id}), 201

    docs = db_session.query(ReferenceDocument).filter_by(
        engagement_id=eng_id, is_active=True
    ).order_by(ReferenceDocument.uploaded_at.desc()).all()
    return jsonify([
        {
            "id": d.id,
            "title": d.title,
            "purpose": d.purpose,
            "uploaded_at": d.uploaded_at.isoformat() if d.uploaded_at else None,
            "uploaded_by": (db_session.query(User).get(d.uploaded_by).username if d.uploaded_by else None),
            "length": len(d.raw_text or ''),
        } for d in docs
    ])


@app.route('/api/references/<int:ref_id>/deactivate', methods=['POST'])
def deactivate_reference(ref_id):
    if not session.get('user_id'):
        return jsonify({"error": "Unauthorized"}), 401

    doc = db_session.query(ReferenceDocument).get(ref_id)
    if not doc:
        return jsonify({"error": "Not found"}), 404

    doc.is_active = False
    db_session.commit()
    return jsonify({"message": "Deactivated"})


@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    if not data:
        return jsonify({"error": "No JSON data"}), 400

    username = data.get('username')
    password = data.get('password')

    user = db_session.query(User).filter_by(username=username).first()

    if user and check_password_hash(user.password_hash, password):
        session['user_id'] = user.id
        # Role always comes from the DB record — the login form doesn't (and
        # shouldn't) let a client choose its own role.
        session['role'] = user.role
        return jsonify({"message": "Logged in successfully", "role": session['role']})

    return jsonify({"error": "Invalid credentials"}), 401

@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({"message": "Logged out"})

@app.route('/api/me', methods=['GET'])
def me():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"error": "Not logged in"}), 401
    
    user = db_session.query(User).get(user_id)
    return jsonify({
        "username": user.username,
        "role": session.get('role')
    })

@app.route('/api/engagements', methods=['GET', 'POST'])
def engagements_list():
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        client_id = data.get('client_id')

        if not isinstance(client_id, int):
            return jsonify({"error": "A valid client_id is required"}), 400

        client = db_session.get(Client, client_id)
        if not client:
            return jsonify({"error": "Client not found"}), 404
        
        new_eng = Engagement(client_id=client.id, status='awaiting_transcript')
        db_session.add(new_eng)
        db_session.commit()
        return jsonify({"id": new_eng.id, "client_name": client.name, "status": new_eng.status})
        
    # GET method
    engagements = db_session.query(Engagement).all()
    result = []
    for eng in engagements:
        result.append({
            "id": eng.id,
            "client_name": eng.client.name,
            "status": eng.status
        })
    return jsonify(result)

@app.route('/api/clients', methods=['GET', 'POST'])
def clients_list():
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        name = (data.get('name') or '').strip()
        industry = (data.get('industry') or '').strip()
        notes = (data.get('notes') or '').strip()

        if not name:
            return jsonify({"error": "Company name is required"}), 400

        # A company name is not a unique identifier — the same client legitimately gets
        # multiple engagements over time. Reuse the existing record instead of blocking
        # (or worse, encouraging a near-duplicate name typed to route around a 409).
        existing_client = db_session.query(Client).filter(Client.name.ilike(name)).first()
        if existing_client:
            return jsonify({"id": existing_client.id, "name": existing_client.name, "reused": True}), 200

        client = Client(name=name, industry=industry or None, notes=notes or None)
        db_session.add(client)
        db_session.commit()
        return jsonify({"id": client.id, "name": client.name, "reused": False}), 201

    clients = db_session.query(Client).order_by(Client.name.asc()).all()
    return jsonify([
        {"id": client.id, "name": client.name}
        for client in clients
    ])

def _carry_forward_items(brief, proposal):
    """Open items that should be raised in the *next* meeting for this engagement:
    the brief's open questions, plus (once a proposal exists) whatever it still
    couldn't resolve and whatever the review-meeting signal extraction flagged as
    raised-but-unresolved or genuinely unclear. Deduped case-insensitively since the
    same item often gets restated across stages."""
    items = []
    seen = set()

    def add_all(source_list, label):
        for item in (source_list or []):
            if not item:
                continue
            key = item.strip().lower()
            if key and key not in seen:
                seen.add(key)
                items.append({"text": item, "source": label})

    if proposal:
        # The proposal stage already reconciled the brief's open questions (resolving
        # what it could, carrying the rest into remaining_open_questions) — trust that
        # as the current state instead of re-surfacing raw brief questions it already
        # addressed or superseded (e.g. a question about a deliverable that got cut).
        data = proposal.structured_json or {}
        add_all(data.get('remaining_open_questions'), 'Proposal')
        signals = data.get('extracted_signals') or {}
        add_all(signals.get('questions_raised'), 'Review Meeting')
        add_all(signals.get('flagged_unclear'), 'Review Meeting')
    elif brief:
        add_all((brief.structured_json or {}).get('open_questions'), 'Brief')

    return items


@app.route('/api/clients/<int:client_id>', methods=['GET'])
def get_client_detail(client_id):
    """The full interaction history with a client across every engagement/workflow
    it's had — not just the currently-open one — plus a relationship-wide rollup
    and carry-forward list deduped across all of them."""
    client = db_session.query(Client).get(client_id)
    if not client:
        return jsonify({"error": "Client not found"}), 404

    engagements = db_session.query(Engagement).filter_by(client_id=client_id).order_by(Engagement.id.desc()).all()

    engagement_summaries = []
    carry_forward_raw = []
    approved_revenue_kes = 0
    pipeline_value_kes = 0
    last_activity_at = None

    for eng in engagements:
        brief = db_session.query(Brief).filter_by(engagement_id=eng.id).order_by(Brief.id.desc()).first()
        proposal = db_session.query(Proposal).filter_by(engagement_id=eng.id).order_by(Proposal.id.desc()).first()

        value_kes = _line_item_total(proposal.pricing_line_items) if proposal else 0
        if proposal and proposal.status == 'approved':
            approved_revenue_kes += value_kes
        elif proposal:
            pipeline_value_kes += value_kes

        for item in _carry_forward_items(brief, proposal):
            carry_forward_raw.append({**item, "engagement_id": eng.id})

        latest_event = db_session.query(AgentEvent).filter_by(engagement_id=eng.id).order_by(AgentEvent.created_at.desc()).first()
        if latest_event and (last_activity_at is None or latest_event.created_at > last_activity_at):
            last_activity_at = latest_event.created_at

        engagement_summaries.append({
            "id": eng.id,
            "status": eng.status,
            "created_at": eng.created_at.isoformat() if eng.created_at else None,
            "work_type": brief.work_type if brief else None,
            "has_brief": bool(brief),
            "has_proposal": bool(proposal),
            "proposal_status": proposal.status if proposal else None,
            "value_kes": value_kes,
        })

    seen = set()
    carry_forward = []
    for item in carry_forward_raw:
        key = item['text'].strip().lower()
        if key not in seen:
            seen.add(key)
            carry_forward.append(item)

    return jsonify({
        "id": client.id,
        "name": client.name,
        "industry": client.industry,
        "notes": client.notes,
        "engagements": engagement_summaries,
        "carry_forward": carry_forward,
        "rollup": {
            "engagement_count": len(engagements),
            "approved_revenue_kes": approved_revenue_kes,
            "pipeline_value_kes": pipeline_value_kes,
            "last_activity_at": last_activity_at.isoformat() if last_activity_at else None,
        }
    })


@app.route('/api/engagements/<int:eng_id>', methods=['GET'])
def get_engagement(eng_id):
    eng = db_session.query(Engagement).get(eng_id)
    if not eng:
        return jsonify({"error": "Not found"}), 404
    
    brief = db_session.query(Brief).filter_by(engagement_id=eng_id).order_by(Brief.id.desc()).first()
    proposal = db_session.query(Proposal).filter_by(engagement_id=eng_id).order_by(Proposal.id.desc()).first()
    events = db_session.query(AgentEvent).filter_by(engagement_id=eng_id).order_by(AgentEvent.created_at.asc()).all()
    transcripts = db_session.query(Transcript).filter_by(engagement_id=eng_id).order_by(Transcript.uploaded_at.asc()).all()

    return jsonify({
        "id": eng.id,
        "client_id": eng.client_id,
        "client_name": eng.client.name,
        "client_industry": eng.client.industry,
        "client_notes": eng.client.notes,
        "status": eng.status,
        "is_processing": bool(eng.is_processing),
        "processing_error": eng.processing_error,
        "carry_forward": _carry_forward_items(brief, proposal),
        "brief": {
            "id": brief.id,
            "structured_json": brief.structured_json,
            "rendered_markdown": brief.rendered_markdown
        } if brief else None,
        "proposal": {
            "id": proposal.id,
            "structured_json": proposal.structured_json,
            "rendered_markdown": proposal.rendered_markdown,
            "pricing_line_items": proposal.pricing_line_items,
            "status": proposal.status
        } if proposal else None,
        "transcripts": [
            {
                "id": t.id,
                "kind": t.kind,
                "uploaded_at": t.uploaded_at.isoformat() if t.uploaded_at else None,
                "meeting_date": t.meeting_date,
                "duration_minutes": t.duration_minutes,
                "attendees": t.attendees,
                "summary": t.summary,
            } for t in transcripts
        ],
        "events": [
            {
                "agent": e.agent,
                "reasoning_summary": e.reasoning_summary,
                "created_at": e.created_at.isoformat()
            } for e in events
        ]
    })

@app.route('/api/engagements/<int:eng_id>/transcripts', methods=['POST'])
def upload_transcript(eng_id):
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json
    raw_text = data.get('raw_text')
    if not raw_text:
        return jsonify({"error": "No transcript provided"}), 400

    eng = db_session.query(Engagement).get(eng_id)
    if not eng:
        return jsonify({"error": "Engagement not found"}), 404

    if eng.is_processing:
        return jsonify({"error": "This engagement is already being processed"}), 409

    dispatch = _transcript_dispatch_for(eng.status)
    if not dispatch:
        return jsonify({"error": "Invalid engagement state for upload"}), 400
    kind, task = dispatch

    # Commit the transcript insert in its own short transaction — the agent call
    # that follows can take up to ~2 minutes, and SQLite only allows one writer
    # at a time, so nothing should hold a write lock open for that whole span.
    transcript = Transcript(engagement_id=eng_id, kind=kind, raw_text=raw_text, uploaded_by=user_id)
    db_session.add(transcript)
    eng.is_processing = True
    eng.processing_error = None
    db_session.commit()

    _executor.submit(task, eng_id, transcript.id)

    return jsonify({"processing": True}), 202


@app.route('/api/engagements/<int:eng_id>/advance', methods=['POST'])
def advance_engagement(eng_id):
    """Explicit producer action to move a refinable brief into the proposal stage —
    what makes the 'awaiting_review_transcript' status (previously declared but never
    set) real: brief_ready allows more intake transcripts until this is called."""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    eng = db_session.query(Engagement).get(eng_id)
    if not eng:
        return jsonify({"error": "Engagement not found"}), 404
    if eng.status != 'brief_ready':
        return jsonify({"error": "Engagement is not ready to advance to the proposal stage"}), 400

    eng.status = 'awaiting_review_transcript'
    db_session.commit()
    return jsonify({"status": eng.status})

# ---------------------------------------------------------------------------
# Fathom transcript inbox
# ---------------------------------------------------------------------------
# Zoom meetings recorded by Fathom arrive here automatically via webhook (see
# fathom.py for verification/parsing and how to register the webhook). Each one
# lands as an InboundTranscript in the inbox, where it can be assigned to a
# teammate, attached to an engagement, or dismissed. Attaching creates a normal
# Transcript row and runs the exact same agent pipeline as a manual paste-upload
# — which stage (brief vs proposal) is decided by the engagement's status, just
# like manual uploads. When the meeting title names exactly one known client,
# the webhook attaches and processes immediately so the brief/proposal is
# already generated by the time someone opens the app.

DISPATCHABLE_STATUSES = ('awaiting_transcript', 'brief_ready', 'awaiting_review_transcript')


def _attach_inbound(inbound, eng, user_id=None, auto=False):
    """Create a real Transcript from an inbound item and kick off background agent
    processing. Caller must already have checked eng.is_processing. Returns False
    when the engagement's state can't accept a transcript."""
    dispatch = _transcript_dispatch_for(eng.status)
    if not dispatch:
        return False
    kind, task = dispatch

    transcript = Transcript(
        engagement_id=eng.id, kind=kind, raw_text=inbound.raw_text, uploaded_by=user_id,
        # Prefill from Fathom's calendar metadata so the meeting card isn't empty
        # while the agent runs; the agent overwrites these with what the transcript
        # itself states once processing finishes.
        meeting_date=inbound.meeting_date,
        duration_minutes=inbound.duration_minutes,
        attendees=inbound.attendees or [],
    )
    db_session.add(transcript)
    eng.is_processing = True
    eng.processing_error = None
    db_session.flush()

    inbound.status = 'processed'
    inbound.engagement_id = eng.id
    inbound.transcript_id = transcript.id
    inbound.auto_matched = auto

    db_session.add(AgentEvent(
        engagement_id=eng.id,
        agent='Fathom Intake',
        trigger='fathom_webhook' if auto else 'inbox_attach',
        reasoning_summary=(
            f"Meeting '{inbound.title or 'Untitled'}' arrived from Fathom and was "
            + ("auto-matched to this client by meeting title." if auto else "attached from the transcript inbox.")
        ),
        action='Ingested Fathom Transcript',
        tokens_used=0
    ))
    db_session.commit()

    _executor.submit(task, eng.id, transcript.id)
    return True


def _auto_match_client(title):
    """The single client whose name appears in the meeting title, or None when zero
    or several match — anything ambiguous stays in the inbox for a human."""
    if not title:
        return None
    title_lower = title.lower()
    matches = [
        c for c in db_session.query(Client).all()
        if c.name and len(c.name) >= 3 and c.name.lower() in title_lower
    ]
    return matches[0] if len(matches) == 1 else None


def _open_engagement_for(client_id):
    return db_session.query(Engagement).filter(
        Engagement.client_id == client_id,
        Engagement.status.in_(DISPATCHABLE_STATUSES),
        Engagement.is_processing == False  # noqa: E712
    ).order_by(Engagement.id.desc()).first()


@app.route('/api/webhooks/fathom', methods=['POST'])
def fathom_webhook():
    # No session auth — Fathom calls this. Authenticity comes from the HMAC
    # signature instead (skipped only when FATHOM_WEBHOOK_SECRET is unset, i.e. dev).
    from fathom import verify_signature, parse_meeting_payload
    if not verify_signature(request.headers, request.get_data()):
        return jsonify({"error": "Invalid webhook signature"}), 401

    data = request.get_json(silent=True) or {}
    parsed = parse_meeting_payload(data)

    if not parsed['raw_text']:
        # Nothing to ingest — webhook probably created without include_transcript.
        return jsonify({"message": "No transcript in payload — ignored"}), 200

    if parsed['external_id']:
        existing = db_session.query(InboundTranscript).filter_by(external_id=parsed['external_id']).first()
        if existing:  # Fathom retries deliveries — dedupe on recording id
            return jsonify({"message": "Already received", "id": existing.id}), 200

    inbound = InboundTranscript(source='fathom', **parsed)
    db_session.add(inbound)
    db_session.commit()

    # Auto-attach only external meetings whose title names exactly one known
    # client; everything else waits in the inbox for a human decision.
    auto_processed = False
    if parsed['is_external_meeting']:
        client = _auto_match_client(parsed['title'])
        if client:
            eng = _open_engagement_for(client.id)
            if not eng:
                eng = Engagement(client_id=client.id, status='awaiting_transcript')
                db_session.add(eng)
                db_session.commit()
            auto_processed = _attach_inbound(inbound, eng, user_id=None, auto=True)

    return jsonify({"id": inbound.id, "auto_processed": auto_processed}), 201


def _inbox_item_json(item, include_raw=False):
    assignee = db_session.query(User).get(item.assigned_to) if item.assigned_to else None
    payload = {
        "id": item.id,
        "source": item.source,
        "title": item.title,
        "share_url": item.share_url,
        "recorded_by": item.recorded_by,
        "meeting_date": item.meeting_date,
        "duration_minutes": item.duration_minutes,
        "attendees": item.attendees or [],
        "is_external_meeting": bool(item.is_external_meeting),
        "summary": item.summary,
        "preview": _snippet(item.raw_text, 180),
        "status": item.status,
        "assigned_to": {"id": assignee.id, "username": assignee.username} if assignee else None,
        "engagement_id": item.engagement_id,
        "auto_matched": bool(item.auto_matched),
        "received_at": item.received_at.isoformat() if item.received_at else None,
    }
    if include_raw:
        payload["raw_text"] = item.raw_text
    return payload


@app.route('/api/inbox', methods=['GET'])
def inbox_list():
    if not session.get('user_id'):
        return jsonify({"error": "Unauthorized"}), 401

    status = request.args.get('status', 'pending')
    query = db_session.query(InboundTranscript)
    if status != 'all':
        query = query.filter_by(status=status)
    items = query.order_by(InboundTranscript.received_at.desc()).all()

    pending_count = db_session.query(func.count(InboundTranscript.id)).filter_by(status='pending').scalar() or 0
    return jsonify({
        "items": [_inbox_item_json(i) for i in items],
        "pending_count": pending_count,
    })


@app.route('/api/inbox/<int:item_id>', methods=['GET'])
def inbox_detail(item_id):
    if not session.get('user_id'):
        return jsonify({"error": "Unauthorized"}), 401
    item = db_session.query(InboundTranscript).get(item_id)
    if not item:
        return jsonify({"error": "Not found"}), 404
    return jsonify(_inbox_item_json(item, include_raw=True))


@app.route('/api/inbox/<int:item_id>/assign', methods=['POST'])
def inbox_assign(item_id):
    role = session.get('role')
    if role not in ('Account Manager', 'Admin'):
        return jsonify({"error": "Account Manager or Admin role required."}), 403

    item = db_session.query(InboundTranscript).get(item_id)
    if not item:
        return jsonify({"error": "Not found"}), 404
    if item.status != 'pending':
        return jsonify({"error": "Only pending items can be assigned"}), 400

    data = request.get_json(silent=True) or {}
    user_id = data.get('user_id')  # null unassigns
    if user_id is not None:
        if not db_session.query(User).get(user_id):
            return jsonify({"error": "User not found"}), 404

    item.assigned_to = user_id
    db_session.commit()
    return jsonify(_inbox_item_json(item))


@app.route('/api/inbox/<int:item_id>/attach', methods=['POST'])
def inbox_attach(item_id):
    """Attach a pending inbound transcript to an engagement — either an existing one
    (engagement_id) or a fresh one for a client (client_id). Which agent runs (brief
    generation/refinement vs proposal) follows from the engagement's status, exactly
    like a manual upload."""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    item = db_session.query(InboundTranscript).get(item_id)
    if not item:
        return jsonify({"error": "Not found"}), 404
    if item.status != 'pending':
        return jsonify({"error": "This transcript has already been handled"}), 400

    data = request.get_json(silent=True) or {}
    eng_id = data.get('engagement_id')
    client_id = data.get('client_id')

    if eng_id is not None:
        eng = db_session.query(Engagement).get(eng_id)
        if not eng:
            return jsonify({"error": "Engagement not found"}), 404
    elif client_id is not None:
        if not db_session.get(Client, client_id):
            return jsonify({"error": "Client not found"}), 404
        eng = Engagement(client_id=client_id, status='awaiting_transcript')
        db_session.add(eng)
        db_session.commit()
    else:
        return jsonify({"error": "engagement_id or client_id is required"}), 400

    if eng.is_processing:
        return jsonify({"error": "This engagement is already being processed"}), 409

    if not _attach_inbound(item, eng, user_id=user_id, auto=False):
        return jsonify({"error": "Invalid engagement state for a new transcript"}), 400

    return jsonify({"processing": True, "engagement_id": eng.id}), 202


@app.route('/api/inbox/<int:item_id>/dismiss', methods=['POST'])
def inbox_dismiss(item_id):
    if not session.get('user_id'):
        return jsonify({"error": "Unauthorized"}), 401
    item = db_session.query(InboundTranscript).get(item_id)
    if not item:
        return jsonify({"error": "Not found"}), 404
    if item.status == 'processed':
        return jsonify({"error": "Already attached to an engagement"}), 400
    item.status = 'dismissed'
    db_session.commit()
    return jsonify({"message": "Dismissed"})


@app.route('/api/users', methods=['GET'])
def users_list():
    # For the inbox assignment dropdown — any logged-in role can see the roster.
    if not session.get('user_id'):
        return jsonify({"error": "Unauthorized"}), 401
    users = db_session.query(User).order_by(User.username.asc()).all()
    return jsonify([{"id": u.id, "username": u.username, "role": u.role} for u in users])


@app.route('/api/engagements/<int:eng_id>/proposals/review', methods=['POST'])
def review_proposal(eng_id):
    user_id = session.get('user_id')
    role = session.get('role')
    if not user_id or role != 'Account Manager':
        return jsonify({"error": "Unauthorized. Account Manager role required."}), 403
    
    data = request.json
    action = data.get('action') # 'approve' or 'send_back'
    notes = data.get('notes', '')

    eng = db_session.query(Engagement).get(eng_id)
    if not eng:
        return jsonify({"error": "Engagement not found"}), 404

    proposal = db_session.query(Proposal).filter_by(engagement_id=eng_id).order_by(Proposal.id.desc()).first()
    if not proposal:
        return jsonify({"error": "No proposal found"}), 404

    if action == 'approve':
        proposal.status = 'approved'
        eng.status = 'approved'
        ev = AgentEvent(
            engagement_id=eng_id,
            agent='Account Manager (Human)',
            trigger='proposal_review',
            reasoning_summary='Reviewed and approved the proposal.',
            action='Approved Proposal',
            tokens_used=0
        )
        db_session.add(ev)
        db_session.commit()
        return jsonify({"message": "Proposal approved"})
        
    elif action == 'send_back':
        if not notes.strip():
            return jsonify({"error": "Notes describing the requested changes are required"}), 400

        if eng.is_processing:
            return jsonify({"error": "This engagement is already being processed"}), 409

        eng.is_processing = True
        eng.processing_error = None
        db_session.commit()

        _executor.submit(_process_proposal_revision, eng_id, proposal.id, notes)

        return jsonify({"processing": True}), 202

    return jsonify({"error": "Invalid action"}), 400

# ---------------------------------------------------------------------------
# Part 2: client acceptance → production staffing
# ---------------------------------------------------------------------------
# Once the AM records that the client accepted the (already approved) proposal,
# the Resource Planner assembles a production plan from the seeded Talent pool:
# crew per team_shape role, tools/equipment implied by the deliverables, and a
# kickoff checklist. Matching is deterministic keyword/skill scoring (staffing.py)
# — no LLM call — so acceptance responds instantly. Only engagement.status moves
# to 'accepted'; proposal.status stays 'approved' because analytics revenue and
# the PDF-download gate both key off it.

@app.route('/api/engagements/<int:eng_id>/accept', methods=['POST'])
def accept_engagement(eng_id):
    from staffing import build_staffing_plan
    role = session.get('role')
    if role not in ('Account Manager', 'Admin'):
        return jsonify({"error": "Account Manager or Admin role required."}), 403

    eng = db_session.query(Engagement).get(eng_id)
    if not eng:
        return jsonify({"error": "Engagement not found"}), 404

    existing = db_session.query(StaffingPlan).filter_by(engagement_id=eng_id).order_by(StaffingPlan.id.desc()).first()
    if eng.status == 'accepted' and existing:
        return jsonify({"plan": existing.plan, "already_accepted": True})

    if eng.status != 'approved':
        return jsonify({"error": "The proposal must be approved before it can be marked client-accepted."}), 400

    proposal = db_session.query(Proposal).filter_by(engagement_id=eng_id).order_by(Proposal.id.desc()).first()
    if not proposal:
        return jsonify({"error": "No proposal found"}), 404

    talents = db_session.query(Talent).filter_by(is_active=True).order_by(Talent.id).all()
    if not talents:
        return jsonify({"error": "Talent pool is empty — run seed_talents.py first."}), 409

    plan = build_staffing_plan(proposal, talents, eng.client.name)

    eng.status = 'accepted'
    db_session.add(StaffingPlan(engagement_id=eng_id, proposal_id=proposal.id, plan=plan))
    db_session.add(AgentEvent(
        engagement_id=eng_id,
        agent='Account Manager (Human)',
        trigger='client_acceptance',
        reasoning_summary='Recorded that the client accepted the proposal.',
        action='Marked Proposal Client-Accepted',
        tokens_used=0
    ))
    db_session.add(AgentEvent(
        engagement_id=eng_id,
        agent='Resource Planner',
        trigger='client_acceptance',
        reasoning_summary=(
            f"Matched the proposal's team shape against the talent pool: assembled a "
            f"{len(plan['team'])}-person crew"
            + (f" with {len(plan['unfilled'])} role(s) still to source externally" if plan['unfilled'] else "")
            + f", flagged {len(plan['tools'])} tool/equipment categories, and drafted the kickoff checklist."
        ),
        action='Assembled Production Team',
        tokens_used=0
    ))
    db_session.commit()

    return jsonify({"plan": plan}), 201


@app.route('/api/engagements/<int:eng_id>/staffing', methods=['GET'])
def get_staffing(eng_id):
    if not session.get('user_id'):
        return jsonify({"error": "Unauthorized"}), 401
    sp = db_session.query(StaffingPlan).filter_by(engagement_id=eng_id).order_by(StaffingPlan.id.desc()).first()
    if not sp:
        return jsonify({"available": False})
    return jsonify({"available": True, "plan": sp.plan, "created_at": sp.created_at.isoformat() if sp.created_at else None})


@app.route('/api/talents', methods=['GET'])
def talents_list():
    if not session.get('user_id'):
        return jsonify({"error": "Unauthorized"}), 401
    talents = db_session.query(Talent).filter_by(is_active=True).order_by(Talent.name.asc()).all()
    return jsonify([
        {
            "id": t.id, "name": t.name, "title": t.title, "skills": t.skills or [],
            "day_rate_kes": t.day_rate_kes, "availability": t.availability,
            "available_from": t.available_from, "location": t.location,
            "years_experience": t.years_experience, "highlight": t.highlight,
        } for t in talents
    ])


@app.route('/api/rate-card', methods=['GET'])
def get_rate_card():
    items = db_session.query(RateCardItem).all()
    return jsonify([{
        "category": item.category,
        "description": item.description,
        "unit": item.unit,
        "rate_kes": item.rate_kes
    } for item in items])

# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

PIPELINE_STAGES = ['awaiting_transcript', 'brief_ready', 'awaiting_review_transcript', 'proposal_ready', 'in_review', 'approved', 'accepted']


def _line_item_total(items):
    return sum((item.get('qty', 1) or 1) * (item.get('rate_kes', 0) or 0) for item in (items or []))


def _avg_hours(deltas_seconds):
    if not deltas_seconds:
        return None
    return round(sum(deltas_seconds) / len(deltas_seconds) / 3600, 2)


def _format_kes(n):
    n = n or 0
    if abs(n) >= 1_000_000:
        return f"KES {n / 1_000_000:.2f}M"
    if abs(n) >= 1_000:
        return f"KES {n / 1_000:.1f}K"
    return f"KES {n:,}"


def _snippet(text, length=90):
    text = (text or '').strip().replace('\n', ' ')
    return text if len(text) <= length else text[:length].rstrip() + '…'


@app.route('/api/analytics', methods=['GET'])
def get_analytics():
    # Dashboard.jsx already consumes a slice of this (turnaround, recent_activity) for
    # every role — only the dedicated Analytics page (funnel/revenue breakdown) is
    # gated to Admin, and that's enforced at the frontend route/nav level, not here.
    engagements = db_session.query(Engagement).all()
    clients = db_session.query(Client).all()
    briefs = db_session.query(Brief).all()
    proposals = db_session.query(Proposal).all()
    events = db_session.query(AgentEvent).order_by(AgentEvent.created_at.desc()).all()

    # Funnel: engagement count per pipeline stage
    status_counts = {}
    for eng in engagements:
        status_counts[eng.status] = status_counts.get(eng.status, 0) + 1
    funnel = [{"status": s, "count": status_counts.get(s, 0)} for s in PIPELINE_STAGES]

    # Pipeline value (open) vs approved revenue, using each engagement's latest proposal
    latest_proposal_by_eng = {}
    for p in proposals:
        current = latest_proposal_by_eng.get(p.engagement_id)
        if current is None or p.version > current.version:
            latest_proposal_by_eng[p.engagement_id] = p

    pipeline_value_kes = 0
    approved_revenue_kes = 0
    for p in latest_proposal_by_eng.values():
        total = _line_item_total(p.pricing_line_items)
        if p.status == 'approved':
            approved_revenue_kes += total
        else:
            pipeline_value_kes += total

    # Work-type mix, from generated briefs
    work_type_counts = {}
    for b in briefs:
        wt = (b.work_type or 'unspecified').replace('-', ' ').replace('_', ' ')
        work_type_counts[wt] = work_type_counts.get(wt, 0) + 1
    work_type_breakdown = sorted(
        [{"work_type": k, "count": v} for k, v in work_type_counts.items()],
        key=lambda x: -x['count']
    )

    # Turnaround time per pipeline hop
    transcript_to_brief = []
    for b in briefs:
        t = db_session.query(Transcript).get(b.transcript_id)
        if t and t.uploaded_at and b.created_at:
            transcript_to_brief.append((b.created_at - t.uploaded_at).total_seconds())

    brief_to_proposal = []
    for p in proposals:
        b = db_session.query(Brief).get(p.brief_id)
        if b and b.created_at and p.created_at:
            brief_to_proposal.append((p.created_at - b.created_at).total_seconds())

    approval_time_by_eng = {e.engagement_id: e.created_at for e in events if e.action == 'Approved Proposal'}
    proposal_to_approval = []
    for eng_id, approved_at in approval_time_by_eng.items():
        p = latest_proposal_by_eng.get(eng_id)
        if p and p.created_at:
            proposal_to_approval.append((approved_at - p.created_at).total_seconds())

    turnaround = {
        "transcript_to_brief_hours": _avg_hours(transcript_to_brief),
        "brief_to_proposal_hours": _avg_hours(brief_to_proposal),
        "proposal_to_approval_hours": _avg_hours(proposal_to_approval),
    }

    # Send-back / friction rate: share of proposed engagements that needed at least one revision
    engs_with_sendback = {e.engagement_id for e in events if e.action == 'Regenerated Proposal'}
    engs_reached_proposal = set(latest_proposal_by_eng.keys())
    send_back_rate = round(100 * len(engs_with_sendback) / len(engs_reached_proposal), 1) if engs_reached_proposal else 0

    # Client proposals list — one row per engagement's latest proposal, most recent first
    proposals_list = []
    for eng_id, p in latest_proposal_by_eng.items():
        eng = db_session.query(Engagement).get(eng_id)
        proposals_list.append({
            "engagement_id": eng_id,
            "client_name": eng.client.name if eng else "Unknown",
            "status": p.status,
            "version": p.version,
            "total_kes": _line_item_total(p.pricing_line_items),
            "created_at": p.created_at.isoformat() if p.created_at else None
        })
    proposals_list.sort(key=lambda x: x['created_at'] or '', reverse=True)

    # Agency-wide recent activity feed
    recent_activity = []
    for e in events[:12]:
        eng = db_session.query(Engagement).get(e.engagement_id)
        recent_activity.append({
            "engagement_id": e.engagement_id,
            "client_name": eng.client.name if eng else "Unknown",
            "agent": e.agent,
            "action": e.action,
            "reasoning_summary": e.reasoning_summary,
            "created_at": e.created_at.isoformat()
        })

    return jsonify({
        "totals": {
            "clients": len(clients),
            "engagements": len(engagements),
            # 'accepted' engagements passed through approval — they still count as won
            "approved": status_counts.get('approved', 0) + status_counts.get('accepted', 0)
        },
        "funnel": funnel,
        "pipeline_value_kes": pipeline_value_kes,
        "approved_revenue_kes": approved_revenue_kes,
        "work_type_breakdown": work_type_breakdown,
        "turnaround": turnaround,
        "send_back_rate": send_back_rate,
        "proposals": proposals_list,
        "recent_activity": recent_activity
    })


@app.route('/api/search', methods=['GET'])
def search():
    q = (request.args.get('q') or '').strip()
    if len(q) < 2:
        return jsonify([])
    like = f"%{q}%"
    results = {}

    for eng in db_session.query(Engagement).join(Client).filter(Client.name.ilike(like)).all():
        results[eng.id] = {"id": eng.id, "client_id": eng.client_id, "client_name": eng.client.name, "status": eng.status, "match": "Client name", "preview": None}

    for b in db_session.query(Brief).filter(Brief.rendered_markdown.ilike(like)).all():
        if b.engagement_id not in results:
            eng = db_session.query(Engagement).get(b.engagement_id)
            if eng:
                data = b.structured_json or {}
                work_type = (data.get('work_type') or '').replace('-', ' ').replace('_', ' ')
                objective = (data.get('objectives') or [None])[0]
                preview = ' · '.join(p for p in [work_type.title() if work_type else None, _snippet(objective, 70) if objective else None] if p)
                results[eng.id] = {"id": eng.id, "client_id": eng.client_id, "client_name": eng.client.name, "status": eng.status, "match": "Production brief", "preview": preview or None}

    # Match on rendered markdown OR the pricing line items directly (pricing predates the
    # markdown including a pricing table, and JSON columns don't reliably ilike() on their own).
    proposal_matches = db_session.query(Proposal).filter(
        Proposal.rendered_markdown.ilike(like) | cast(Proposal.pricing_line_items, String).ilike(like)
    ).all()
    for p in proposal_matches:
        if p.engagement_id not in results:
            eng = db_session.query(Engagement).get(p.engagement_id)
            if eng:
                # The match may be on an older revision's text — always summarize the
                # engagement's *current* proposal, not whichever version matched.
                latest = db_session.query(Proposal).filter_by(engagement_id=p.engagement_id) \
                    .order_by(Proposal.version.desc()).first()
                total = _format_kes(_line_item_total(latest.pricing_line_items))
                approach = _snippet((latest.structured_json or {}).get('approach'), 70)
                preview = ' · '.join(x for x in [total, approach] if x)
                results[eng.id] = {"id": eng.id, "client_id": eng.client_id, "client_name": eng.client.name, "status": latest.status, "match": "Client proposal", "preview": preview or None}

    return jsonify(list(results.values())[:10])


# ---------------------------------------------------------------------------
# PDF Generation Helpers
# ---------------------------------------------------------------------------
# These build the PDF straight from each document's structured_json, mirroring
# the on-screen report layout, rather than round-tripping through markdown.

def _esc(value):
    return html.escape(str(value)) if value is not None else ''


def _bullets(items, empty_text='None noted'):
    items = [i for i in (items or []) if i]
    if not items:
        return f'<p class="muted">{_esc(empty_text)}</p>'
    lis = ''.join(f'<li>{_esc(i)}</li>' for i in items)
    return f'<ul>{lis}</ul>'


def _tags(items, empty_text):
    items = [i for i in (items or []) if i]
    if not items:
        return f'<p class="muted">{_esc(empty_text)}</p>'
    return ''.join(f'<span class="tag">{_esc(i)}</span>' for i in items)


PDF_STYLE = '''
  @page {
    size: A4;
    margin: 0;
    @bottom-center {
      content: counter(page) " / " counter(pages);
      font-size: 8.5pt;
      color: #9ca3af;
      font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
    }
  }
  * { box-sizing: border-box; }
  body {
    font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
    font-size: 10.5pt;
    line-height: 1.6;
    color: #374151;
    margin: 0;
  }
  .banner { background: linear-gradient(135deg, ACCENT_FROM, ACCENT_TO); color: #ffffff; padding: 16mm 16mm 12mm 16mm; }
  .banner .eyebrow { font-size: 8.5pt; letter-spacing: 0.15em; text-transform: uppercase; opacity: 0.85; margin: 0 0 8px 0; }
  .banner h1 { font-size: 24pt; margin: 0; color: #ffffff; font-weight: 700; }
  .banner .badge { display: inline-block; background: rgba(255,255,255,0.18); padding: 4px 13px; border-radius: 999px; font-size: 9pt; margin-top: 12px; }
  .body { padding: 14mm 16mm 4mm 16mm; }
  .section { margin-bottom: 20px; }
  .section-label { font-size: 8.5pt; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase; color: ACCENT_FROM; margin: 0 0 8px 0; }
  .muted { color: #9ca3af; font-style: italic; margin: 0; }
  .info-grid { display: flex; gap: 12px; margin-bottom: 22px; }
  .info-box { flex: 1; background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px; padding: 11px 14px; }
  .info-box .label { font-size: 8pt; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: #9ca3af; margin-bottom: 3px; }
  .info-box .value { font-size: 10pt; color: #111827; }
  .tag { display: inline-block; font-size: 9pt; padding: 4px 11px; border-radius: 999px; margin: 0 6px 6px 0; background: ACCENT_TINT; color: ACCENT_FROM; border: 1px solid ACCENT_TINT_BORDER; }
  .callout { border-radius: 8px; padding: 13px 16px; margin-bottom: 20px; background: #fffbeb; border: 1px solid #fde68a; color: #92400e; }
  .callout .section-label { color: #92400e; }
  ul { margin: 0; padding-left: 20px; }
  li { margin-bottom: 6px; }
  p { margin: 0; }
  table.pricing { width: 100%; border-collapse: collapse; font-size: 9.5pt; margin-top: 6px; }
  table.pricing th { background: #f3f4f6; color: #6b7280; font-weight: 600; text-align: left; padding: 9px 12px; border: 1px solid #e5e7eb; }
  table.pricing td { padding: 9px 12px; border: 1px solid #e5e7eb; }
  table.pricing tfoot td { font-weight: 700; color: #111827; border-top: 2px solid #111827; background: #f9fafb; }
  .footer { padding: 14px 16mm 24px 16mm; border-top: 1px solid #e5e7eb; font-size: 8.5pt; color: #9ca3af; text-align: center; margin-top: 10px; }
'''


def _pdf_shell(accent_from, accent_to, accent_tint, accent_tint_border, eyebrow, heading, badge, body_html):
    style = (PDF_STYLE
             .replace('ACCENT_TINT_BORDER', accent_tint_border)
             .replace('ACCENT_TINT', accent_tint)
             .replace('ACCENT_FROM', accent_from)
             .replace('ACCENT_TO', accent_to))
    badge_html = f'<span class="badge">{_esc(badge)}</span>' if badge else ''
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<style>{style}</style>
</head>
<body>
<div class="banner">
  <p class="eyebrow">FactoryOS &middot; {_esc(eyebrow)}</p>
  <h1>{_esc(heading)}</h1>
  {badge_html}
</div>
<div class="body">
{body_html}
</div>
<div class="footer">Generated by FactoryOS on {datetime.now().strftime('%B %d, %Y')}</div>
</body>
</html>'''


def build_brief_pdf_html(brief, client_name):
    data = brief.structured_json or {}
    work_type = (data.get('work_type') or '').replace('-', ' ').title()

    body = f'''
      <div class="section">
        <p class="section-label">Objectives</p>
        {_bullets(data.get('objectives'))}
      </div>
      <div class="section">
        <p class="section-label">Audience</p>
        <p>{_esc(data.get('audience') or 'Not specified')}</p>
      </div>
      <div class="section">
        <p class="section-label">Deliverables</p>
        {_bullets(data.get('deliverables'))}
      </div>
      <div class="info-grid">
        <div class="info-box">
          <div class="label">Timeline</div>
          <div class="value">{_esc(data.get('timeline_signals') or 'TBD')}</div>
        </div>
        <div class="info-box">
          <div class="label">Budget</div>
          <div class="value">{_esc(data.get('budget_signals') or 'TBD')}</div>
        </div>
      </div>
      <div class="section">
        <p class="section-label">Key Stakeholders</p>
        {_tags(data.get('key_stakeholders'), 'None noted')}
      </div>
      {f'<div class="callout"><p class="section-label">Risks</p>{_bullets(data.get("risks"))}</div>' if data.get('risks') else ''}
      {f'<div class="section"><p class="section-label">Open Questions</p>{_bullets(data.get("open_questions"))}</div>' if data.get('open_questions') else ''}
    '''

    return _pdf_shell(
        accent_from='#4f46e5', accent_to='#4338ca',
        accent_tint='#eef2ff', accent_tint_border='#e0e7ff',
        eyebrow='Production Brief',
        heading=client_name,
        badge=work_type or None,
        body_html=body
    )


def build_proposal_pdf_html(proposal, client_name):
    data = proposal.structured_json or {}
    pricing_items = proposal.pricing_line_items or []

    rows = ''
    grand_total = 0
    for item in pricing_items:
        qty = item.get('qty', 1) or 1
        rate = item.get('rate_kes', 0) or 0
        line_total = qty * rate
        grand_total += line_total
        rows += f'''
          <tr>
            <td>{_esc(item.get('category', ''))}</td>
            <td>{_esc(item.get('description', ''))}</td>
            <td style="text-align:center;">{qty}</td>
            <td style="text-align:right;">KES {rate:,}</td>
            <td style="text-align:right;">KES {line_total:,}</td>
          </tr>'''

    pricing_html = ''
    if pricing_items:
        pricing_html = f'''
          <div class="section">
            <p class="section-label">Pricing Structure</p>
            <table class="pricing">
              <thead>
                <tr>
                  <th>Category</th><th>Description</th><th style="text-align:center;">Qty</th>
                  <th style="text-align:right;">Rate (KES)</th><th style="text-align:right;">Total (KES)</th>
                </tr>
              </thead>
              <tbody>{rows}</tbody>
              <tfoot>
                <tr>
                  <td colspan="4" style="text-align:right;">Total Investment</td>
                  <td style="text-align:right;">KES {grand_total:,}</td>
                </tr>
              </tfoot>
            </table>
          </div>'''

    body = f'''
      <div class="section">
        <p class="section-label">Approach</p>
        <p>{_esc(data.get('approach') or 'Not specified')}</p>
      </div>
      <div class="section">
        <p class="section-label">Scoped Deliverables</p>
        {_bullets(data.get('scoped_deliverables'))}
      </div>
      <div class="section">
        <p class="section-label">Phased Timeline</p>
        {_bullets(data.get('phased_timeline'))}
      </div>
      <div class="section">
        <p class="section-label">Team Shape</p>
        {_tags(data.get('team_shape'), 'Not specified')}
      </div>
      {pricing_html}
    '''

    return _pdf_shell(
        accent_from='#059669', accent_to='#047857',
        accent_tint='#ecfdf5', accent_tint_border='#d1fae5',
        eyebrow='Client Proposal',
        heading=client_name,
        badge='Approved' if proposal.status == 'approved' else None,
        body_html=body
    )


@app.route('/api/engagements/<int:eng_id>/brief/pdf', methods=['GET'])
def download_brief_pdf(eng_id):
    eng = db_session.query(Engagement).get(eng_id)
    if not eng:
        return jsonify({"error": "Engagement not found"}), 404

    brief = db_session.query(Brief).filter_by(engagement_id=eng_id).order_by(Brief.id.desc()).first()
    if not brief:
        return jsonify({"error": "No brief found for this engagement"}), 404

    try:
        html_content = build_brief_pdf_html(brief, eng.client.name)
        pdf_buffer = io.BytesIO()
        HTML(string=html_content).write_pdf(pdf_buffer)
        pdf_buffer.seek(0)

        filename = f"{eng.client.name.replace(' ', '_')}_Production_Brief.pdf"
        return send_file(
            pdf_buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        return jsonify({"error": f"PDF generation failed: {str(e)}"}), 500


@app.route('/api/engagements/<int:eng_id>/proposal/pdf', methods=['GET'])
def download_proposal_pdf(eng_id):
    eng = db_session.query(Engagement).get(eng_id)
    if not eng:
        return jsonify({"error": "Engagement not found"}), 404

    proposal = db_session.query(Proposal).filter_by(engagement_id=eng_id).order_by(Proposal.id.desc()).first()
    if not proposal:
        return jsonify({"error": "No proposal found for this engagement"}), 404

    try:
        html_content = build_proposal_pdf_html(proposal, eng.client.name)
        pdf_buffer = io.BytesIO()
        HTML(string=html_content).write_pdf(pdf_buffer)
        pdf_buffer.seek(0)

        filename = f"{eng.client.name.replace(' ', '_')}_Client_Proposal.pdf"
        return send_file(
            pdf_buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        return jsonify({"error": f"PDF generation failed: {str(e)}"}), 500


if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5000)
