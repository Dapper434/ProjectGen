from dotenv import load_dotenv

# Load backend/.env (if present) before anything reads os.environ — this must happen
# before config.py and agents.py are imported, since agents.py reads NIM_API_KEY at
# module-import time.
load_dotenv()

from functools import wraps
from flask import Flask, request, jsonify, session, send_file, has_request_context
from flask_cors import CORS
from config import Config
from database import db_session, init_db
from models import User, Client, Engagement, Transcript, Brief, Proposal, RateCardItem, PastProject, AgentEvent, RequirementDocument, ReferenceDocument, InboundTranscript, Talent, StaffingPlan, AuthoritativeDoc, ComparisonRun, RecordingJob, RecordingSegment, BoardroomSession, TranscriptSegment, CoverageCheck, AvailabilityBlock, PortfolioItem, Assignment, CastingRun, Certification, CertificationEnrollment, Event, EventAttendance, TalentSkill
from authoritative import REGISTRY as AUTH_REGISTRY, GROUPS as AUTH_GROUPS, resolve as auth_resolve, create_version as auth_create_version, activate_version as auth_activate_version, list_versions as auth_list_versions, build_refs, AuthoritativeError
from locks import agent_lock, is_locked, AlreadyProcessing
import assignments as assignments_mod
import audio
import availability
import boardroom
import casting
import lab
import mailer
import polish as polish_mod
import portal
import provider_settings
import recordings
import stt_hints
import tokens as tokens_mod
import transcribe
from providers import registry as provider_registry

provider_registry.load_drivers()
from werkzeug.security import check_password_hash
from sqlalchemy import cast, String, func
from weasyprint import HTML
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from werkzeug.utils import secure_filename
import io
import html
import re
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = Config.SECRET_KEY
CORS(app, supports_credentials=True)

# Production runs behind HTTPS everywhere (Vercel rewrite -> Cloudflare Tunnel),
# and the Vercel proxy makes all browser traffic same-origin — so Lax + Secure
# is enough; no cross-site cookie contortions needed. Off in dev (plain http).
if Config.PRODUCTION:
    app.config.update(SESSION_COOKIE_SECURE=True, SESSION_COOKIE_SAMESITE='Lax')


def feature(name):
    """Gate a route behind a Config.FLAGS entry. Disabled -> 404, not 403 — a
    dark-shipped feature must be indistinguishable from one that doesn't exist."""
    def deco(fn):
        @wraps(fn)
        def inner(*args, **kwargs):
            if not Config.FLAGS.get(name):
                return jsonify({"error": "Feature not enabled."}), 404
            return fn(*args, **kwargs)
        return inner
    return deco


def require_role(*roles):
    """Gate a route to specific internal User roles (401 if not logged in, 403
    if logged in as the wrong role) — decorators, not inline `if` checks, per
    AGENTS.md §5. Any role not in `roles` is rejected, which today also covers
    a hypothetical Talent-portal session (WP-11): there is no session path yet
    that sets session['role'] to anything but an internal role, so this is
    already "everyone except an internal role gets 403" by construction."""
    def deco(fn):
        @wraps(fn)
        def inner(*args, **kwargs):
            if not session.get('user_id'):
                return jsonify({"error": "Unauthorized"}), 401
            if roles and session.get('role') not in roles:
                return jsonify({"error": f"{' or '.join(roles)} role required."}), 403
            return fn(*args, **kwargs)
        return inner
    return deco


@app.route('/healthz')
@app.route('/api/healthz')
def healthz():
    return jsonify({"status": "ok"})


@app.route('/api/config')
def get_config():
    return jsonify({"flags": Config.FLAGS, "product": "The Exodus"})


# ---------------------------------------------------------------------------
# Authoritative Data Layer (WP-1) — versioned, scoped system knowledge
# ---------------------------------------------------------------------------
# Read: any authenticated internal role. Write (create a new version, or roll
# back to an old one): Account Manager or Admin only — this data drives every
# agent in the system, including pricing.

INTERNAL_ROLES = ('Producer', 'Account Manager', 'Admin')


def _auth_doc_json(d, include_body=False):
    out = {
        "id": d.id, "key": d.key, "scope_type": d.scope_type, "scope_id": d.scope_id,
        "title": d.title, "fmt": d.fmt, "version": d.version, "is_active": d.is_active,
        "label": d.label, "note": d.note, "updated_by": d.updated_by,
        "updated_at": d.updated_at.isoformat() if d.updated_at else None,
    }
    if include_body:
        out["body"] = d.body
    return out


def _auth_entry_json(key, entry):
    return {
        "key": key,
        "title": entry.get('title', key),
        "description": entry.get('description', ''),
        "group": entry.get('group', 'policies'),
        "fmt": entry['fmt'],
        "scopes": list(entry['scopes']),
        "consumers": entry.get('consumers', []),
        "variants": bool(entry.get('variants')),
    }


def _auth_registry_json():
    return {key: _auth_entry_json(key, entry) for key, entry in AUTH_REGISTRY.items()}


@app.route('/api/authoritative', methods=['GET', 'POST'])
@feature('auth_data')
@require_role(*INTERNAL_ROLES)
def authoritative_list():
    if request.method == 'POST':
        if session.get('role') not in ('Account Manager', 'Admin'):
            return jsonify({"error": "Account Manager or Admin role required."}), 403

        data = request.get_json(silent=True) or {}
        key = data.get('key')
        if key not in AUTH_REGISTRY:
            return jsonify({"error": "Unknown authoritative key."}), 400
        scope_type = data.get('scope_type', 'global')
        scope_id = data.get('scope_id')
        title = (data.get('title') or AUTH_REGISTRY[key].get('title') or key).strip()
        fmt = data.get('fmt', AUTH_REGISTRY[key]['fmt'])
        body = data.get('body')
        label = data.get('label')
        note = data.get('note')
        if not body:
            return jsonify({"error": "body is required"}), 400

        try:
            doc = auth_create_version(key, scope_type, scope_id, title, fmt, body,
                                       updated_by=session.get('user_id'), label=label, note=note)
            db_session.commit()
        except AuthoritativeError as e:
            db_session.rollback()
            return jsonify({"error": str(e)}), 400
        return jsonify(_auth_doc_json(doc, include_body=True)), 201

    scope_type = request.args.get('scope_type', 'global')
    scope_id = request.args.get('scope_id', type=int)
    if scope_type != 'global' and scope_id is None:
        return jsonify({"error": "scope_id is required for scope_type != global"}), 400

    docs = db_session.query(AuthoritativeDoc).filter_by(
        scope_type=scope_type, scope_id=scope_id, is_active=True
    ).all()
    docs_by_key = {}
    for d in docs:
        docs_by_key.setdefault(d.key, []).append(_auth_doc_json(d))

    return jsonify([
        {**_auth_entry_json(key, entry), "active_docs": docs_by_key.get(key, [])}
        for key, entry in AUTH_REGISTRY.items()
    ])


@app.route('/api/authoritative/groups', methods=['GET'])
@feature('auth_data')
@require_role(*INTERNAL_ROLES)
def authoritative_groups():
    """Section headings for the Playbook, in display order. Owned by the registry
    so the UI never keeps its own copy of the taxonomy."""
    return jsonify([{"id": gid, **meta} for gid, meta in AUTH_GROUPS.items()])


@app.route('/api/authoritative/registry', methods=['GET'])
@feature('auth_data')
@require_role(*INTERNAL_ROLES)
def authoritative_registry():
    return jsonify(_auth_registry_json())


@app.route('/api/authoritative/resolve/<key>', methods=['GET'])
@feature('auth_data')
@require_role(*INTERNAL_ROLES)
def authoritative_resolve_route(key):
    if key not in AUTH_REGISTRY:
        return jsonify({"error": "Unknown authoritative key."}), 404
    eng_id = request.args.get('engagement_id', type=int)
    client_id = request.args.get('client_id', type=int)
    label = request.args.get('label')
    engagement = db_session.query(Engagement).get(eng_id) if eng_id else None
    client = db_session.query(Client).get(client_id) if client_id else None
    body, provenance = auth_resolve(key, engagement=engagement, client=client, label=label)
    return jsonify({"body": body, "provenance": provenance})


@app.route('/api/authoritative/<key>/versions', methods=['GET'])
@feature('auth_data')
@require_role(*INTERNAL_ROLES)
def authoritative_versions(key):
    if key not in AUTH_REGISTRY:
        return jsonify({"error": "Unknown authoritative key."}), 404
    scope_type = request.args.get('scope_type', 'global')
    scope_id = request.args.get('scope_id', type=int)
    versions = auth_list_versions(key, scope_type, scope_id)
    return jsonify([_auth_doc_json(d, include_body=True) for d in versions])


# ---------------------------------------------------------------------------
# Provider registry, runtime settings & the Lab (WP-2)
# ---------------------------------------------------------------------------


def driver_override(capability):
    """Per-request driver override from `X-Driver-Override: agent_llm=ollama;polish=off`.

    Deliberately narrow: this is a debugging tool for the Lab, not a production
    API surface. Ignored entirely unless FEATURE_LAB is on *and* the caller is an
    Account Manager or Admin — otherwise any client could redirect an agent to a
    different vendor by setting a header.
    """
    if not Config.FLAGS.get('lab'):
        return None
    # Callable from background tasks and scripts, where there is no request to
    # read a header from — those paths simply get no override.
    if not has_request_context():
        return None
    if session.get('role') not in ('Account Manager', 'Admin'):
        return None
    header = request.headers.get('X-Driver-Override')
    if not header:
        return None
    for part in header.split(';'):
        name, _, value = part.partition('=')
        if name.strip() == capability and value.strip():
            return value.strip()
    return None


@app.route('/api/providers', methods=['GET'])
@feature('lab')
@require_role(*INTERNAL_ROLES)
def providers_list():
    return jsonify(provider_settings.list_capabilities())


@app.route('/api/providers/health', methods=['GET'])
@feature('lab')
@require_role(*INTERNAL_ROLES)
def providers_health():
    return jsonify(provider_settings.health_all(force=request.args.get('refresh') == '1'))


@app.route('/api/providers/history', methods=['GET'])
@feature('lab')
@require_role(*INTERNAL_ROLES)
def providers_history():
    return jsonify(provider_settings.history())


@app.route('/api/providers/<capability>', methods=['POST'])
@feature('lab')
@require_role('Admin')
def providers_set(capability):
    data = request.get_json(silent=True) or {}
    driver_key = data.get('driver_key')
    if not driver_key:
        return jsonify({"error": "driver_key is required"}), 400
    try:
        result = provider_settings.set_driver(
            capability, driver_key, options=data.get('options'),
            changed_by=session.get('user_id'), reason=data.get('reason'),
        )
    except provider_settings.SettingsError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(result)


@app.route('/api/providers/<capability>/test', methods=['POST'])
@feature('lab')
@require_role(*INTERNAL_ROLES)
def providers_test(capability):
    data = request.get_json(silent=True) or {}
    driver_key = data.get('driver_key')
    cls = provider_registry.get_driver_class(capability, driver_key)
    if cls is None:
        return jsonify({"error": f"{driver_key} is not a registered driver for {capability}."}), 404
    try:
        health = cls(data.get('options')).health()
    except Exception as e:
        health = {"ok": False, "detail": f"health() raised: {str(e)[:150]}", "latency_ms": None}
    return jsonify({"capability": capability, "driver_key": driver_key, **health})


@app.route('/api/lab/generate', methods=['POST'])
@feature('lab')
@require_role('Account Manager', 'Admin')
def lab_generate():
    """Bake-off for brief generation across model drivers and/or prompt variants,
    on a transcript already in the system. Returns 202; the frontend polls the run."""
    data = request.get_json(silent=True) or {}
    driver_keys = data.get('drivers') or []
    if not driver_keys:
        return jsonify({"error": "Pick at least one driver to compare."}), 400

    transcript_id = data.get('transcript_id')
    text = (data.get('text') or '').strip()
    if transcript_id:
        transcript = db_session.query(Transcript).get(transcript_id)
        if not transcript:
            return jsonify({"error": "Transcript not found"}), 404
        text = transcript.raw_text or ''
    if not text:
        return jsonify({"error": "Provide a transcript_id or some text to run against."}), 400

    prompt_key = data.get('prompt_key', 'brief_generation_prompt')
    prompt_labels = data.get('prompt_labels') or [None]

    # Resolve each prompt variant up front, on the request thread, so the worker
    # gets primitives only — never an ORM object or a live session.
    system_prompt_by_label = {}
    for label in prompt_labels:
        body, _ = auth_resolve(prompt_key, label=label)
        if body is None and label is None:
            from agents import DEFAULT_BRIEF_GENERATION_PROMPT
            body = DEFAULT_BRIEF_GENERATION_PROMPT
        system_prompt_by_label[label] = body or ''

    run = lab.create_run(
        capability='agent_llm', input_kind='transcript',
        input_ref=transcript_id or 'inline', driver_keys=driver_keys,
        created_by=session.get('user_id'),
        input_meta={"word_count": len(text.split()), "prompt_key": prompt_key},
        prompt_labels=prompt_labels,
    )
    user_prompt = f"<meeting_summary>\n{text}\n</meeting_summary>"
    _executor.submit(lab.run_generation_comparison, run.id, system_prompt_by_label, user_prompt)
    return jsonify({"run_id": run.id}), 202


# ---------------------------------------------------------------------------
# Talent portal (WP-11) — the first genuinely public surface in this system
# ---------------------------------------------------------------------------
# Every query below is filtered by session['talent_id'] at the query level.
# No route here accepts a talent_id parameter, by design.


@app.route('/api/talent/login', methods=['POST'])
@feature('talent_portal')
def talent_login():
    ip = request.headers.get('X-Forwarded-For', request.remote_addr or 'unknown').split(',')[0].strip()
    if portal.throttled(ip):
        return jsonify({"error": "Too many attempts. Try again in an hour."}), 429

    data = request.get_json(silent=True) or {}
    talent = portal.authenticate(data.get('email'), data.get('password'))
    if not talent:
        portal.record_attempt(ip)
        return jsonify({"error": "Those details did not match an active account."}), 401

    session.clear()
    session['role'] = 'Talent'
    session['talent_id'] = talent.id
    return jsonify({"name": talent.name, "email": talent.email})


@app.route('/api/talent/signup', methods=['POST'])
@feature('talent_portal')
def talent_signup():
    """Open sign-up — a talent joins the bench themselves, no invite required.

    Rate-limited on the same per-IP counter as login, since this endpoint also
    reveals whether an email is known to the system. A new account is live
    immediately (`signup_source='self'`) so the person can build a profile and
    take certifications the moment they land; the bench UI marks them
    self-registered so a producer can tell them from vetted crew.
    """
    ip = request.headers.get('X-Forwarded-For', request.remote_addr or 'unknown').split(',')[0].strip()
    if portal.throttled(ip):
        return jsonify({"error": "Too many attempts. Try again in an hour."}), 429

    data = request.get_json(silent=True) or {}
    talent, error, claim_token = portal.register(
        name=data.get('name'), email=data.get('email'), password=data.get('password'),
        title=data.get('title'), location=data.get('location'), phone=data.get('phone'),
    )
    if error:
        portal.record_attempt(ip)
        return jsonify({"error": error}), 400

    if claim_token:
        # Already on the bench but never set a password: confirm ownership of the
        # address before handing over the profile. 202, not 201 — nothing is live yet.
        email = (data.get('email') or '').strip().lower()
        link = f"{Config.APP_BASE_URL.rstrip('/')}/talent/set-password?token={claim_token}"
        result = mailer.send(
            email, "Claim your Exodus talent profile",
            f"Someone (hopefully you) tried to create an account with this address.\n\n"
            f"You are already on the GDF talent bench, so set your password here instead:\n\n{link}\n\n"
            f"This link works once and expires in {portal.INVITE_TTL_HOURS} hours. "
            f"If this wasn't you, ignore this email — nothing has changed.",
        )
        return jsonify({
            "claim_sent": True,
            "message": "You're already on the GDF bench. We've emailed you a link to set your password.",
            "link": link if result['driver'] == 'console' else None,
        }), 202

    session.clear()
    session['role'] = 'Talent'
    session['talent_id'] = talent.id
    return jsonify({"name": talent.name, "email": talent.email}), 201


@app.route('/api/talent/logout', methods=['POST'])
@feature('talent_portal')
def talent_logout():
    session.clear()
    return jsonify({"message": "Signed out"})


@app.route('/api/talent/set-password', methods=['POST'])
@feature('talent_portal')
def talent_set_password():
    data = request.get_json(silent=True) or {}
    talent, error = portal.redeem_invite(data.get('token'), data.get('password'))
    if error:
        return jsonify({"error": error}), 400
    session.clear()
    session['role'] = 'Talent'
    session['talent_id'] = talent.id
    return jsonify({"name": talent.name, "email": talent.email})


@app.route('/api/talent/me', methods=['GET', 'PATCH'])
@feature('talent_portal')
@portal.require_talent
def talent_me():
    talent = portal.current_talent()
    if not talent:
        return jsonify({"error": "Account not found"}), 404
    if request.method == 'PATCH':
        data = request.get_json(silent=True) or {}
        # A talent may edit their own presentation, never their commercial or
        # status fields — those belong to the agency.
        for field in ('name', 'phone', 'highlight', 'avatar_url', 'day_rate_kes'):
            if field in data:
                setattr(talent, field, data[field])
        if 'skills' in data and isinstance(data['skills'], list):
            talent.skills = data['skills']
        db_session.commit()
    return jsonify({**portal.me_json(talent), "next_best_action": portal.next_best_action(talent)})


@app.route('/api/talent/tokens', methods=['GET'])
@feature('talent_portal')
@portal.require_talent
def talent_portal_tokens():
    talent = portal.current_talent()
    return jsonify({"balance": tokens_mod.balance(talent),
                    "ledger": tokens_mod.ledger_json(talent.id)})


@app.route('/api/talent/policies', methods=['GET'])
@feature('talent_portal')
@portal.require_talent
def talent_policies():
    """Whitelisted authoritative read — the "How I get picked" page renders the
    real policy documents rather than a hand-written copy, which would drift from
    the actual weights within one edit."""
    token_policy, token_prov = tokens_mod.policy()
    cast_policy, cast_prov = casting.policy()
    talent = portal.current_talent()
    return jsonify({
        "talent_token_policy": token_policy,
        "casting_policy": cast_policy,
        "provenance": {"tokens": token_prov, "casting": cast_prov},
        "my_balance": tokens_mod.balance(talent),
        "next_best_action": portal.next_best_action(talent),
    })


@app.route('/api/talent/portfolio', methods=['GET', 'POST'])
@feature('talent_portal')
@portal.require_talent
def talent_portfolio():
    talent_id = session['talent_id']
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        item = PortfolioItem(
            talent_id=talent_id, title=data.get('title'), role=data.get('role'),
            client_name=data.get('client_name'), year=data.get('year'),
            media_url=data.get('media_url'), link=data.get('link'),
            description=data.get('description'),
            is_public=data.get('is_public', True),
            order_index=data.get('order_index', 0),
        )
        db_session.add(item)
        db_session.commit()
        return jsonify({"id": item.id}), 201

    rows = (db_session.query(PortfolioItem).filter_by(talent_id=talent_id)
            .order_by(PortfolioItem.order_index, PortfolioItem.id).all())
    return jsonify([{
        "id": p.id, "title": p.title, "role": p.role, "client_name": p.client_name,
        "year": p.year, "media_url": p.media_url, "link": p.link,
        "description": p.description, "is_public": p.is_public, "order_index": p.order_index,
    } for p in rows])


@app.route('/api/talent/portfolio/<int:item_id>', methods=['PATCH', 'DELETE'])
@feature('talent_portal')
@portal.require_talent
def talent_portfolio_item(item_id):
    # Filtered by the session's talent, so another talent's item simply 404s.
    item = db_session.query(PortfolioItem).filter_by(
        id=item_id, talent_id=session['talent_id']).first()
    if not item:
        return jsonify({"error": "Not found"}), 404

    if request.method == 'DELETE':
        db_session.delete(item)
        db_session.commit()
        return jsonify({"deleted": item_id})

    data = request.get_json(silent=True) or {}
    for field in ('title', 'role', 'client_name', 'year', 'media_url', 'link',
                  'description', 'is_public', 'order_index'):
        if field in data:
            setattr(item, field, data[field])
    db_session.commit()
    return jsonify({"id": item.id})


@app.route('/api/talent/availability', methods=['GET', 'POST'])
@feature('talent_portal')
@portal.require_talent
def talent_portal_availability():
    talent_id = session['talent_id']
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        if data.get('ics'):
            return jsonify({"imported": availability.import_ics(talent_id, data['ics'])}), 201
        from datetime import datetime as _dt
        try:
            block = AvailabilityBlock(
                talent_id=talent_id,
                start_at=_dt.fromisoformat(data['start_at']),
                end_at=_dt.fromisoformat(data['end_at']),
                kind=data.get('kind', 'busy'), source='manual',
                note=(data.get('note') or None),
            )
        except (KeyError, ValueError):
            return jsonify({"error": "start_at and end_at must be ISO datetimes."}), 400
        db_session.add(block)
        db_session.commit()
        return jsonify({"id": block.id}), 201

    rows = (db_session.query(AvailabilityBlock).filter_by(talent_id=talent_id)
            .order_by(AvailabilityBlock.start_at).all())
    return jsonify([{
        "id": b.id, "start_at": b.start_at.isoformat(), "end_at": b.end_at.isoformat(),
        "kind": b.kind, "source": b.source, "note": b.note,
    } for b in rows])


@app.route('/api/talent/availability/<int:block_id>', methods=['DELETE'])
@feature('talent_portal')
@portal.require_talent
def talent_delete_availability(block_id):
    block = db_session.query(AvailabilityBlock).filter_by(
        id=block_id, talent_id=session['talent_id']).first()
    if not block:
        return jsonify({"error": "Not found"}), 404
    if block.source == 'assignment':
        return jsonify({"error": "This block comes from an accepted assignment and cannot be removed here."}), 409
    db_session.delete(block)
    db_session.commit()
    return jsonify({"deleted": block_id})


@app.route('/api/talent/offers', methods=['GET'])
@feature('talent_portal')
@portal.require_talent
def talent_offers():
    assignments_mod.expire_stale_offers()
    return jsonify(portal.offers_json(portal.current_talent()))


@app.route('/api/talent/offers/<int:assignment_id>/respond', methods=['POST'])
@feature('talent_portal')
@portal.require_talent
def talent_respond_offer(assignment_id):
    """Drives the same state machine as the internal route — one lifecycle, two
    doors into it."""
    a = db_session.query(Assignment).filter_by(
        id=assignment_id, talent_id=session['talent_id']).first()
    if not a:
        return jsonify({"error": "Not found"}), 404

    data = request.get_json(silent=True) or {}
    action = data.get('action')
    if action not in ('accept', 'decline'):
        return jsonify({"error": "action must be 'accept' or 'decline'."}), 400
    try:
        assignments_mod.transition(a, 'accepted' if action == 'accept' else 'declined',
                                   reason=data.get('reason'))
    except assignments_mod.LifecycleError as e:
        return jsonify({"error": str(e)}), 409
    return jsonify({"status": a.status, "tokens": tokens_mod.balance(portal.current_talent())})


@app.route('/api/talent/certifications', methods=['GET'])
@feature('talent_portal')
@portal.require_talent
def talent_certifications():
    return jsonify(portal.certifications_json(portal.current_talent()))


@app.route('/api/talent/certifications/<cert_key>/enroll', methods=['POST'])
@feature('talent_portal')
@portal.require_talent
def talent_enroll(cert_key):
    cert = db_session.query(Certification).filter_by(key=cert_key).first()
    if not cert:
        return jsonify({"error": "That certification does not exist."}), 404

    existing = db_session.query(CertificationEnrollment).filter_by(
        talent_id=session['talent_id'], certification_id=cert.id).first()
    if existing and existing.status == 'completed':
        return jsonify({"error": "You have already completed this one."}), 409

    enrollment = existing or CertificationEnrollment(
        talent_id=session['talent_id'], certification_id=cert.id, status='in_progress')
    enrollment.status = 'in_progress'
    db_session.add(enrollment)
    db_session.commit()

    entry = portal.catalog_questions(cert_key) or {}
    # Answers are stripped: the quiz is graded server-side.
    questions = [{"q": q.get('q'), "options": q.get('options')} for q in (entry.get('questions') or [])]
    return jsonify({"enrollment_id": enrollment.id, "questions": questions,
                    "pass_mark": entry.get('pass_mark', 0.8)})


@app.route('/api/talent/certifications/<int:enrollment_id>/submit', methods=['POST'])
@feature('talent_portal')
@portal.require_talent
def talent_submit_quiz(enrollment_id):
    enrollment = db_session.query(CertificationEnrollment).filter_by(
        id=enrollment_id, talent_id=session['talent_id']).first()
    if not enrollment:
        return jsonify({"error": "Not found"}), 404
    if enrollment.status == 'completed':
        return jsonify({"error": "You have already passed this one."}), 409

    cert = db_session.query(Certification).get(enrollment.certification_id)
    entry = portal.catalog_questions(cert.key) or {}
    answers = (request.get_json(silent=True) or {}).get('answers') or []
    ratio, correct, total = portal.grade(entry, answers)
    pass_mark = entry.get('pass_mark', 0.8)

    enrollment.attempts = (enrollment.attempts or 0) + 1
    enrollment.score = round(ratio, 3)

    if ratio < pass_mark:
        # Failing awards nothing; a retake is allowed after the cooldown.
        enrollment.status = 'failed'
        db_session.commit()
        return jsonify({"passed": False, "score": enrollment.score,
                        "correct": correct, "total": total,
                        "cooldown_hours": entry.get('cooldown_hours', 24)})

    enrollment.status = 'completed'
    enrollment.completed_at = datetime.utcnow()
    if cert.validity_months:
        enrollment.expires_at = datetime.utcnow() + timedelta(days=30 * cert.validity_months)
    db_session.commit()

    tokens_mod.award(
        enrollment.talent_id, tokens_mod.certification_award(cert.category),
        reason='certification_completed', ref_type='enrollment', ref_id=enrollment.id,
        note=f"Passed {cert.name}",
    )

    # A certified skill outranks a claimed one in the casting hard filter.
    if cert.grants_skill_id:
        link = db_session.query(TalentSkill).filter_by(
            talent_id=enrollment.talent_id, skill_id=cert.grants_skill_id).first()
        if not link:
            link = TalentSkill(talent_id=enrollment.talent_id, skill_id=cert.grants_skill_id, level=4)
            db_session.add(link)
        link.verified_by_enrollment_id = enrollment.id
        db_session.commit()

    return jsonify({"passed": True, "score": enrollment.score, "correct": correct, "total": total,
                    "tokens": tokens_mod.balance(portal.current_talent())})


@app.route('/api/talent/events', methods=['GET'])
@feature('talent_portal')
@portal.require_talent
def talent_events():
    rows = db_session.query(Event).order_by(Event.starts_at.desc()).limit(50).all()
    attended = {a.event_id for a in db_session.query(EventAttendance)
                .filter_by(talent_id=session['talent_id']).all()}
    return jsonify([{
        "id": e.id, "name": e.name, "kind": e.kind, "location": e.location,
        "token_award": e.token_award,
        "starts_at": e.starts_at.isoformat() if e.starts_at else None,
        "ends_at": e.ends_at.isoformat() if e.ends_at else None,
        "attended": e.id in attended,
    } for e in rows])


@app.route('/api/talent/events/checkin', methods=['POST'])
@feature('talent_portal')
@portal.require_talent
def talent_event_checkin():
    code = ((request.get_json(silent=True) or {}).get('code') or '').strip()
    if not code:
        return jsonify({"error": "Enter the check-in code from the event."}), 400

    event = db_session.query(Event).filter(Event.checkin_code == code).first()
    if not event:
        return jsonify({"error": "That code did not match any event."}), 404

    talent_id = session['talent_id']
    existing = db_session.query(EventAttendance).filter_by(
        event_id=event.id, talent_id=talent_id).first()
    if existing:
        # A second attempt is a friendly no-op, not an error and not a double credit.
        return jsonify({"already": True, "event": event.name,
                        "tokens": tokens_mod.balance(portal.current_talent())})

    db_session.add(EventAttendance(event_id=event.id, talent_id=talent_id, method='code'))
    db_session.commit()
    tokens_mod.award(talent_id, event.token_award or 10, reason='event_attendance',
                     ref_type='event', ref_id=event.id, note=f"Attended {event.name}")
    return jsonify({"already": False, "event": event.name,
                    "tokens": tokens_mod.balance(portal.current_talent())})


@app.route('/api/talent/<int:talent_id>/invite', methods=['POST'])
@feature('talent')
@require_role('Account Manager', 'Admin')
def talent_invite(talent_id):
    """Nudge someone GDF added to the bench into setting a portal password.

    Talents can also register themselves (`POST /api/talent/signup`); this route
    exists for the other direction — a producer added the profile first and wants
    the person to take it over. With EMAIL_DRIVER=console the link prints to
    stdout, so the whole flow is testable with no vendor account."""
    t = db_session.query(Talent).get(talent_id)
    if not t:
        return jsonify({"error": "Talent not found"}), 404
    if not t.email:
        return jsonify({"error": "Add an email address for this talent first."}), 400

    token = portal.create_invite(talent_id)
    link = f"{Config.APP_BASE_URL.rstrip('/')}/talent/set-password?token={token}"
    result = mailer.send(
        t.email, "Your Exodus talent portal invitation",
        f"Hi {t.name},\n\nYou've been added to the GDF talent bench. "
        f"Set your password to see your token balance, availability and offers:\n\n{link}\n\n"
        f"This link works once and expires in {portal.INVITE_TTL_HOURS} hours.",
    )
    return jsonify({"sent": result['ok'], "driver": result['driver'], "detail": result['detail'],
                    # Surfaced only for the console driver so a local flow is testable.
                    "link": link if result['driver'] == 'console' else None})


# ---------------------------------------------------------------------------
# Talent domain, casting & assignments (WP-9 / WP-10)
# ---------------------------------------------------------------------------


def _talent_json(t, detail=False):
    out = {
        "id": t.id, "name": t.name, "title": t.title, "skills": t.skills or [],
        "day_rate_kes": t.day_rate_kes, "location": t.location,
        "years_experience": t.years_experience, "highlight": t.highlight,
        "engagement_type": t.engagement_type, "status": t.status or 'active',
        "seniority": t.seniority, "avg_rating": t.avg_rating,
        "email": t.email, "avatar_url": t.avatar_url,
        "last_assigned_at": t.last_assigned_at.isoformat() if t.last_assigned_at else None,
        "tokens": tokens_mod.balance(t),
        # Curation signals for the bench UI. Rows predating open sign-up have no
        # source recorded and read as agency-added.
        "signup_source": t.signup_source or 'agency',
        "has_portal_login": bool(t.portal_password_hash),
    }
    if detail:
        blocks = db_session.query(AvailabilityBlock).filter_by(talent_id=t.id).order_by(
            AvailabilityBlock.start_at).all()
        out["availability_blocks"] = [{
            "id": b.id, "start_at": b.start_at.isoformat(), "end_at": b.end_at.isoformat(),
            "kind": b.kind, "source": b.source, "note": b.note,
        } for b in blocks]
        out["portfolio"] = [{
            "id": p.id, "title": p.title, "role": p.role, "client_name": p.client_name,
            "year": p.year, "link": p.link, "description": p.description,
        } for p in db_session.query(PortfolioItem).filter_by(talent_id=t.id, is_public=True).all()]
        out["skills_detail"] = casting.talent_skill_names(t)
        out["decline_count_90d"] = tokens_mod.decline_count(t.id)
        # `notes` is deliberately absent — internal only, never exposed here.
    return out


@app.route('/api/talent', methods=['GET'])
@feature('talent')
@require_role(*INTERNAL_ROLES)
def talent_directory():
    q = db_session.query(Talent).filter(Talent.is_active == True)  # noqa: E712
    if request.args.get('discipline'):
        q = q.filter(Talent.title.ilike(f"%{request.args['discipline']}%"))
    if request.args.get('engagement_type'):
        q = q.filter(Talent.engagement_type == request.args['engagement_type'])
    if request.args.get('status'):
        q = q.filter(Talent.status == request.args['status'])
    rows = q.order_by(Talent.name).all()

    start = request.args.get('available_from')
    end = request.args.get('available_to')
    if start and end:
        from datetime import datetime as _dt
        try:
            s, e = _dt.fromisoformat(start), _dt.fromisoformat(end)
            rows = [t for t in rows if availability.is_available(t.id, s, e)[0]]
        except ValueError:
            return jsonify({"error": "available_from/available_to must be ISO datetimes."}), 400

    return jsonify([_talent_json(t) for t in rows])


@app.route('/api/talent/<int:talent_id>', methods=['GET', 'PATCH'])
@feature('talent')
@require_role(*INTERNAL_ROLES)
def talent_detail(talent_id):
    t = db_session.query(Talent).get(talent_id)
    if not t:
        return jsonify({"error": "Talent not found"}), 404
    if request.method == 'PATCH':
        if session.get('role') not in ('Account Manager', 'Admin'):
            return jsonify({"error": "Account Manager or Admin role required."}), 403
        data = request.get_json(silent=True) or {}
        for field in ('name', 'title', 'email', 'phone', 'engagement_type', 'status',
                      'seniority', 'day_rate_kes', 'location', 'highlight', 'notes', 'avatar_url'):
            if field in data:
                setattr(t, field, data[field])
        db_session.commit()
    return jsonify(_talent_json(t, detail=True))


@app.route('/api/talent/<int:talent_id>/tokens', methods=['GET', 'POST'])
@feature('talent')
@require_role(*INTERNAL_ROLES)
def talent_tokens(talent_id):
    t = db_session.query(Talent).get(talent_id)
    if not t:
        return jsonify({"error": "Talent not found"}), 404

    if request.method == 'POST':
        if session.get('role') != 'Admin':
            return jsonify({"error": "Admin role required."}), 403
        data = request.get_json(silent=True) or {}
        delta = data.get('delta')
        note = (data.get('note') or '').strip()
        if not isinstance(delta, int) or delta == 0:
            return jsonify({"error": "delta must be a non-zero integer."}), 400
        if not note:
            return jsonify({"error": "A note is required for a manual adjustment."}), 400
        tokens_mod.award(talent_id, delta, reason='manual', ref_type='manual',
                         ref_id=int(datetime.utcnow().timestamp()), note=note,
                         created_by=session.get('user_id'))

    return jsonify({"balance": tokens_mod.balance(t), "ledger": tokens_mod.ledger_json(talent_id)})


@app.route('/api/talent/<int:talent_id>/availability', methods=['GET', 'POST'])
@feature('talent')
@require_role(*INTERNAL_ROLES)
def talent_availability(talent_id):
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        if data.get('ics'):
            created = availability.import_ics(talent_id, data['ics'])
            return jsonify({"imported": created}), 201
        from datetime import datetime as _dt
        try:
            block = AvailabilityBlock(
                talent_id=talent_id,
                start_at=_dt.fromisoformat(data['start_at']),
                end_at=_dt.fromisoformat(data['end_at']),
                kind=data.get('kind', 'busy'), source='manual',
                note=(data.get('note') or None),
            )
        except (KeyError, ValueError):
            return jsonify({"error": "start_at and end_at must be ISO datetimes."}), 400
        db_session.add(block)
        db_session.commit()
        return jsonify({"id": block.id}), 201

    blocks = db_session.query(AvailabilityBlock).filter_by(talent_id=talent_id).order_by(
        AvailabilityBlock.start_at).all()
    return jsonify([{
        "id": b.id, "start_at": b.start_at.isoformat(), "end_at": b.end_at.isoformat(),
        "kind": b.kind, "source": b.source, "note": b.note,
    } for b in blocks])


@app.route('/api/engagements/<int:eng_id>/casting', methods=['GET', 'POST'])
@feature('talent')
@require_role(*INTERNAL_ROLES)
def engagement_casting(eng_id):
    eng = db_session.query(Engagement).get(eng_id)
    if not eng:
        return jsonify({"error": "Engagement not found"}), 404

    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        _executor.submit(casting.run_casting, eng_id, data.get('roles'), session.get('user_id'))
        return jsonify({"running": True}), 202

    run = (db_session.query(CastingRun).filter_by(engagement_id=eng_id)
           .order_by(CastingRun.id.desc()).first())
    if not run:
        return jsonify({"run": None})
    return jsonify({"run": {
        "id": run.id, "status": run.status, "roles": run.roles, "result": run.result,
        "tokens_used": run.tokens_used,
        "created_at": run.created_at.isoformat() if run.created_at else None,
    }})


@app.route('/api/engagements/<int:eng_id>/assignments', methods=['GET'])
@feature('talent')
@require_role(*INTERNAL_ROLES)
def engagement_assignments(eng_id):
    assignments_mod.expire_stale_offers()
    rows = db_session.query(Assignment).filter_by(engagement_id=eng_id).order_by(Assignment.id).all()
    return jsonify([assignments_mod.assignment_json(a) for a in rows])


@app.route('/api/assignments', methods=['POST'])
@feature('talent')
@require_role('Account Manager', 'Admin')
def create_assignment():
    """No assignment reaches a talent without this explicit approval step —
    the casting agent only ever produces a shortlist."""
    data = request.get_json(silent=True) or {}
    if not data.get('engagement_id') or not data.get('talent_id'):
        return jsonify({"error": "engagement_id and talent_id are required."}), 400

    from datetime import datetime as _dt
    def _dt_or_none(v):
        try:
            return _dt.fromisoformat(v) if v else None
        except ValueError:
            return None

    a = Assignment(
        engagement_id=data['engagement_id'], talent_id=data['talent_id'],
        role=data.get('role'), status='shortlisted',
        rate_kes=data.get('rate_kes'),
        start_at=_dt_or_none(data.get('start_at')), end_at=_dt_or_none(data.get('end_at')),
        score=data.get('score'), score_breakdown=data.get('score_breakdown'),
        rationale=data.get('rationale'), created_by=session.get('user_id'),
    )
    db_session.add(a)
    db_session.commit()
    return jsonify(assignments_mod.assignment_json(a)), 201


@app.route('/api/assignments/<int:assignment_id>', methods=['PATCH'])
@feature('talent')
@require_role(*INTERNAL_ROLES)
def patch_assignment(assignment_id):
    a = db_session.query(Assignment).get(assignment_id)
    if not a:
        return jsonify({"error": "Assignment not found"}), 404
    data = request.get_json(silent=True) or {}
    to_status = data.get('status')
    if not to_status:
        return jsonify({"error": "status is required."}), 400
    try:
        assignments_mod.transition(a, to_status, **{k: v for k, v in data.items() if k != 'status'})
    except assignments_mod.LifecycleError as e:
        return jsonify({"error": str(e)}), 409
    return jsonify(assignments_mod.assignment_json(a))


# ---------------------------------------------------------------------------
# Boardroom (WP-7)
# ---------------------------------------------------------------------------
# Transport is polling, not SSE or WebSockets: it matches the pattern the rest
# of the app already uses and does not hold a gunicorn thread open per attendee.
# With one worker and eight threads, a handful of SSE sessions would eat the pool.


@app.route('/api/boardroom/sessions', methods=['GET', 'POST'])
@feature('boardroom')
@require_role(*INTERNAL_ROLES)
def boardroom_sessions():
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        if not data.get('consent_ack'):
            return jsonify({"error": "Consent must be acknowledged before a session can start."}), 400

        eng_id = data.get('engagement_id')
        eng = db_session.query(Engagement).get(eng_id) if eng_id else None
        meeting_kind = data.get('meeting_kind') or 'intake'

        _protocol, prov = boardroom.resolve_protocol(None, eng, meeting_kind)
        stt_selected = provider_registry.current_selection('stt_live')[0]
        coverage_selected = provider_registry.current_selection('coverage_llm')[0]

        session_row = BoardroomSession(
            engagement_id=eng_id,
            client_id=(eng.client_id if eng else data.get('client_id')),
            title=(data.get('title') or 'Client meeting').strip()[:200],
            meeting_kind=meeting_kind,
            # Frozen here: editing the protocol mid-meeting must not move the
            # goalposts under a session that has already started.
            protocol_scope=(prov or {}).get('scope'),
            protocol_version=(prov or {}).get('version'),
            status='live',
            stt_driver=stt_selected, coverage_driver=coverage_selected,
            language=data.get('language') or 'en',
            planned_minutes=data.get('planned_minutes'),
            consent_ack_by=session.get('user_id'),
            consent_ack_at=datetime.utcnow(),
            created_by=session.get('user_id'),
        )
        db_session.add(session_row)
        db_session.flush()

        db_session.add(AgentEvent(
            engagement_id=eng_id, agent='Boardroom', trigger='boardroom_session_start',
            reasoning_summary=(
                f"Live transcription started for '{session_row.title}'. The producer confirmed that "
                f"everyone present has been told the meeting is being transcribed."
            ),
            action='Started Boardroom Session', tokens_used=0,
        ))
        db_session.commit()
        return jsonify(boardroom.session_json(session_row)), 201

    q = db_session.query(BoardroomSession)
    if request.args.get('status'):
        q = q.filter(BoardroomSession.status == request.args['status'])
    if request.args.get('engagement_id', type=int):
        q = q.filter(BoardroomSession.engagement_id == request.args.get('engagement_id', type=int))
    rows = q.order_by(BoardroomSession.id.desc()).limit(50).all()
    return jsonify([boardroom.session_json(s, include_protocol=False) for s in rows])


@app.route('/api/boardroom/sessions/<int:session_id>', methods=['GET'])
@feature('boardroom')
@require_role(*INTERNAL_ROLES)
def boardroom_session_detail(session_id):
    row = db_session.query(BoardroomSession).get(session_id)
    if not row:
        return jsonify({"error": "Session not found"}), 404
    return jsonify(boardroom.session_json(row, since_seq=request.args.get('since_seq', type=int)))


@app.route('/api/boardroom/sessions/<int:session_id>/chunk', methods=['POST'])
@feature('boardroom')
@require_role(*INTERNAL_ROLES)
def boardroom_chunk(session_id):
    row = db_session.query(BoardroomSession).get(session_id)
    if not row:
        return jsonify({"error": "Session not found"}), 404
    if row.status != 'live':
        return jsonify({"error": f"This session is {row.status}."}), 409

    upload = request.files.get('audio')
    if not upload:
        return jsonify({"error": "No audio uploaded."}), 400
    data = upload.read()
    if not data:
        return jsonify({"error": "The uploaded chunk was empty."}), 400

    hints = stt_hints.build_hints(row.engagement_id) if row.engagement_id else stt_hints.agency_vocabulary()
    try:
        result = transcribe.transcribe_piece(
            data, upload.mimetype or 'audio/webm', capability='stt_live',
            hints=hints, language=row.language or 'en',
            override=driver_override('stt_live'),
        )
    except Exception as e:
        return jsonify({"error": str(e)[:300]}), 503

    # One write per chunk (~15s), not per word — SQLite's single writer is a
    # non-issue at that rate for a handful of rooms.
    seq = boardroom.next_seq(session_id)
    created = []
    if result['text']:
        db_session.add(TranscriptSegment(
            session_id=session_id, seq=seq, text=result['text'],
            source='stt', provider=result['driver'],
        ))
        created.append(seq)
        row.audio_seconds = (row.audio_seconds or 0) + int(request.form.get('seconds', 15) or 15)
        db_session.commit()

    return jsonify({
        "segments": created, "text": result['text'],
        "provider": result['driver'], "provider_label": result['driver_label'],
        "is_local": result['is_local'], "degraded": result['degraded'],
    })


@app.route('/api/boardroom/sessions/<int:session_id>/segments', methods=['POST'])
@feature('boardroom')
@require_role(*INTERNAL_ROLES)
def boardroom_add_segment(session_id):
    """Typed notes and browser-side speech text. The coverage agent does not care
    where the text came from, so a session can run with no audio at all."""
    row = db_session.query(BoardroomSession).get(session_id)
    if not row:
        return jsonify({"error": "Session not found"}), 404
    data = request.get_json(silent=True) or {}
    text = (data.get('text') or '').strip()
    if not text:
        return jsonify({"error": "Nothing to add."}), 400

    seq = boardroom.next_seq(session_id)
    db_session.add(TranscriptSegment(
        session_id=session_id, seq=seq, text=text,
        speaker_label=(data.get('speaker_label') or None),
        source=data.get('source') or 'typed',
    ))
    db_session.commit()
    return jsonify({"seq": seq}), 201


@app.route('/api/boardroom/sessions/<int:session_id>/coverage', methods=['POST'])
@feature('boardroom')
@require_role(*INTERNAL_ROLES)
def boardroom_coverage(session_id):
    """Safe to call repeatedly — the server enforces the protocol's debounce."""
    row = db_session.query(BoardroomSession).get(session_id)
    if not row:
        return jsonify({"error": "Session not found"}), 404
    _executor.submit(boardroom.analyze_coverage, session_id, False)
    return jsonify({"queued": True}), 202


@app.route('/api/boardroom/sessions/<int:session_id>/end', methods=['POST'])
@feature('boardroom')
@require_role(*INTERNAL_ROLES)
def boardroom_end(session_id):
    row = db_session.query(BoardroomSession).get(session_id)
    if not row:
        return jsonify({"error": "Session not found"}), 404
    if row.status != 'live':
        return jsonify({"error": f"This session is already {row.status}."}), 409

    raw = boardroom.assemble(session_id)
    row.raw_transcript = raw
    row.status = 'ended'
    row.ended_at = datetime.utcnow()
    db_session.commit()

    def _finalise(sid):
        try:
            boardroom.analyze_coverage(sid, final=True)
            s = db_session.query(BoardroomSession).get(sid)
            if s and s.raw_transcript:
                names = stt_hints.build_hints(s.engagement_id) if s.engagement_id else ''
                polished, _prov = polish_mod.polish(
                    s.raw_transcript, names=[n.strip() for n in names.split(',') if n.strip()])
                s.polished_transcript = polished
                db_session.commit()
        finally:
            db_session.remove()

    _executor.submit(_finalise, session_id)
    return jsonify({"status": "ended"}), 202


@app.route('/api/boardroom/sessions/<int:session_id>/promote', methods=['POST'])
@feature('boardroom')
@require_role(*INTERNAL_ROLES)
def boardroom_promote(session_id):
    """Manual, never automatic — the producer reviews before this feeds the brief
    agent. Goes through the same transcript endpoint as every other inlet."""
    row = db_session.query(BoardroomSession).get(session_id)
    if not row:
        return jsonify({"error": "Session not found"}), 404

    data = request.get_json(silent=True) or {}
    eng_id = data.get('engagement_id') or row.engagement_id
    if not eng_id:
        return jsonify({"error": "Choose an engagement to promote this transcript into."}), 400

    eng = db_session.query(Engagement).get(eng_id)
    if not eng:
        return jsonify({"error": "Engagement not found"}), 404
    if eng.is_processing:
        return jsonify({"error": "This engagement is already being processed"}), 409

    dispatch = _transcript_dispatch_for(eng.status)
    if not dispatch:
        return jsonify({"error": "This engagement is not in a state that accepts a transcript."}), 400
    kind, task = dispatch

    text = (data.get('text') or row.polished_transcript or row.raw_transcript
            or boardroom.assemble(session_id)).strip()
    if not text:
        return jsonify({"error": "This session captured no text to promote."}), 400

    transcript_row = Transcript(engagement_id=eng.id, kind=kind, raw_text=text,
                                uploaded_by=session.get('user_id'))
    db_session.add(transcript_row)
    eng.is_processing = True
    eng.processing_error = None
    db_session.flush()

    row.status = 'promoted'
    row.engagement_id = eng.id
    row.client_id = eng.client_id
    row.promoted_transcript_id = transcript_row.id

    db_session.add(AgentEvent(
        engagement_id=eng.id, agent='Boardroom', trigger='boardroom_promote',
        reasoning_summary=f"Promoted the live transcript from '{row.title}' into this engagement.",
        action='Promoted Boardroom Transcript', tokens_used=0,
    ))
    db_session.commit()

    _executor.submit(task, eng.id, transcript_row.id)
    return jsonify({"processing": True, "transcript_id": transcript_row.id}), 202


@app.route('/api/boardroom/sessions/<int:session_id>/discard', methods=['POST'])
@feature('boardroom')
@require_role(*INTERNAL_ROLES)
def boardroom_discard(session_id):
    row = db_session.query(BoardroomSession).get(session_id)
    if not row:
        return jsonify({"error": "Session not found"}), 404
    row.status = 'discarded'          # soft-delete: the audit row survives
    db_session.commit()
    return jsonify({"status": "discarded"})


@app.route('/api/boardroom/sessions/<int:session_id>/export', methods=['GET'])
@feature('boardroom')
@require_role(*INTERNAL_ROLES)
def boardroom_export(session_id):
    row = db_session.query(BoardroomSession).get(session_id)
    if not row:
        return jsonify({"error": "Session not found"}), 404

    text = row.polished_transcript or row.raw_transcript or boardroom.assemble(session_id)
    checks = boardroom.latest_checks(session_id)
    protocol, _prov = boardroom.resolve_protocol(row, row.engagement if row.engagement_id else None)
    labels = {i['key']: i['label'] for i in protocol.get('items', [])}

    lines = [f"# {row.title}", ""]
    lines.append(f"_{row.meeting_kind} · {row.started_at:%Y-%m-%d %H:%M}_" if row.started_at else "")
    lines += ["", "## Agenda coverage", ""]
    for key, check in checks.items():
        mark = {'covered': 'x', 'partial': '~', 'missing': ' ', 'unknown': '?'}.get(check.status, ' ')
        lines.append(f"- [{mark}] **{labels.get(key, key)}** — {check.status}")
        if check.evidence:
            lines.append(f"  > {check.evidence}")
    lines += ["", "## Transcript", "", text]

    body = '\n'.join(lines)
    return send_file(io.BytesIO(body.encode('utf-8')), mimetype='text/markdown',
                     as_attachment=True,
                     download_name=f"{secure_filename(row.title or 'boardroom')}.md")


# ---------------------------------------------------------------------------
# Recording Studio (WP-6)
# ---------------------------------------------------------------------------

MAX_UPLOAD_MB = 500
ALLOWED_MEDIA_EXT = {'.mp3', '.m4a', '.wav', '.mp4', '.mov', '.webm', '.ogg', '.aac', '.flac', '.mkv'}


def _recordings_dir():
    path = Path(Config.UPLOAD_DIR) / 'recordings'
    path.mkdir(parents=True, exist_ok=True)
    return path


def _save_upload(upload, dest_dir):
    """Stream to disk rather than buffering — one worker holding a 400 MB upload
    in RAM is how the box falls over. Enforces the size cap while writing, so an
    oversized file never fully lands."""
    name = secure_filename(upload.filename or 'recording')
    dest = dest_dir / f"{int(datetime.now().timestamp())}_{name}"
    limit = MAX_UPLOAD_MB * 1024 * 1024
    written = 0
    with open(dest, 'wb') as out:
        while True:
            chunk = upload.stream.read(1024 * 1024)
            if not chunk:
                break
            written += len(chunk)
            if written > limit:
                out.close()
                dest.unlink(missing_ok=True)
                raise ValueError(f"That file is over the {MAX_UPLOAD_MB} MB limit.")
            out.write(chunk)
    return dest, name, written


@app.route('/api/recordings', methods=['GET', 'POST'])
@feature('recordings')
@require_role(*INTERNAL_ROLES)
def recordings_list():
    if request.method == 'POST':
        upload = request.files.get('audio')
        if not upload or not upload.filename:
            return jsonify({"error": "Choose an audio or video file to upload."}), 400

        ext = Path(upload.filename).suffix.lower()
        if ext not in ALLOWED_MEDIA_EXT:
            return jsonify({"error": f"{ext or 'That file type'} is not supported. "
                                     f"Use one of: {', '.join(sorted(ALLOWED_MEDIA_EXT))}."}), 400

        driver_key = request.form.get('driver_key') or provider_registry.current_selection('stt_batch')[0]
        if provider_registry.get_driver_class('stt_batch', driver_key) is None:
            return jsonify({"error": f"{driver_key} is not a known transcription engine."}), 400

        try:
            path, name, size = _save_upload(upload, _recordings_dir())
        except ValueError as e:
            return jsonify({"error": str(e)}), 413

        eng_id = request.form.get('engagement_id', type=int)
        eng = db_session.query(Engagement).get(eng_id) if eng_id else None

        job = RecordingJob(
            engagement_id=eng_id,
            client_id=eng.client_id if eng else None,
            title=(request.form.get('title') or name).strip()[:200],
            source_path=str(path), source_name=name, source_bytes=size,
            mime=upload.mimetype, driver_key=driver_key,
            driver_options=request.form.get('options'),
            language=request.form.get('language') or 'en',
            status='queued', created_by=session.get('user_id'),
        )
        db_session.add(job)
        db_session.commit()

        _executor.submit(recordings.run_recording_job, job.id)
        return jsonify(recordings.job_json(job)), 202

    q = db_session.query(RecordingJob)
    if request.args.get('status'):
        q = q.filter(RecordingJob.status == request.args['status'])
    if request.args.get('engagement_id', type=int):
        q = q.filter(RecordingJob.engagement_id == request.args.get('engagement_id', type=int))
    jobs = q.order_by(RecordingJob.id.desc()).limit(100).all()
    return jsonify([recordings.job_json(j) for j in jobs])


@app.route('/api/recordings/compare', methods=['POST'])
@feature('recordings')
@require_role('Account Manager', 'Admin')
def recordings_compare():
    """'Transcribe with both and compare' — the one click that lets you decide
    between cloud and local on your own audio."""
    upload = request.files.get('audio')
    if not upload or not upload.filename:
        return jsonify({"error": "Choose an audio or video file to upload."}), 400
    driver_keys = [k for k in (request.form.get('drivers') or '').split(',') if k]
    if len(driver_keys) < 2:
        return jsonify({"error": "Pick at least two engines to compare."}), 400

    try:
        path, name, size = _save_upload(upload, _recordings_dir())
    except ValueError as e:
        return jsonify({"error": str(e)}), 413

    eng_id = request.form.get('engagement_id', type=int)
    hints = stt_hints.build_hints(eng_id) if eng_id else stt_hints.agency_vocabulary()

    run = lab.create_run(
        capability='stt_batch', input_kind='audio', input_ref=str(path),
        driver_keys=driver_keys, created_by=session.get('user_id'),
        input_meta={"filename": name, "size_bytes": size},
    )
    _executor.submit(lab.run_transcription_comparison, run.id, str(path), hints)
    return jsonify({"run_id": run.id}), 202


@app.route('/api/recordings/<int:job_id>', methods=['GET', 'PATCH', 'DELETE'])
@feature('recordings')
@require_role(*INTERNAL_ROLES)
def recording_detail(job_id):
    job = db_session.query(RecordingJob).get(job_id)
    if not job:
        return jsonify({"error": "Recording not found"}), 404

    if request.method == 'DELETE':
        Path(job.source_path).unlink(missing_ok=True) if job.source_path else None
        db_session.query(RecordingSegment).filter_by(job_id=job.id).delete()
        db_session.delete(job)
        db_session.commit()
        return jsonify({"deleted": job_id})

    if request.method == 'PATCH':
        data = request.get_json(silent=True) or {}
        if 'edited_text' in data:
            job.edited_text = data['edited_text']
        if 'title' in data:
            job.title = (data['title'] or '').strip()[:200]
        if 'engagement_id' in data:
            job.engagement_id = data['engagement_id']
            eng = db_session.query(Engagement).get(data['engagement_id']) if data['engagement_id'] else None
            job.client_id = eng.client_id if eng else None
        db_session.commit()

    return jsonify(recordings.job_json(job, include_segments=True))


@app.route('/api/recordings/<int:job_id>/retry', methods=['POST'])
@feature('recordings')
@require_role(*INTERNAL_ROLES)
def recording_retry(job_id):
    job = db_session.query(RecordingJob).get(job_id)
    if not job:
        return jsonify({"error": "Recording not found"}), 404
    if not job.source_path or not Path(job.source_path).exists():
        return jsonify({"error": "The source audio is no longer on disk, so this job cannot be re-run."}), 409

    data = request.get_json(silent=True) or {}
    if data.get('driver_key'):
        job.driver_key = data['driver_key']
    job.status = 'queued'
    job.error = None
    job.progress_pct = 0
    job.pieces_done = 0
    db_session.commit()
    _executor.submit(recordings.run_recording_job, job.id)
    return jsonify(recordings.job_json(job)), 202


@app.route('/api/recordings/<int:job_id>/cancel', methods=['POST'])
@feature('recordings')
@require_role(*INTERNAL_ROLES)
def recording_cancel(job_id):
    job = db_session.query(RecordingJob).get(job_id)
    if not job:
        return jsonify({"error": "Recording not found"}), 404
    if job.status in recordings.TERMINAL_STATUSES:
        return jsonify({"error": f"This recording is already {job.status}."}), 409
    job.status = 'cancelled'
    db_session.commit()
    return jsonify(recordings.job_json(job))


@app.route('/api/recordings/<int:job_id>/attach', methods=['POST'])
@feature('recordings')
@require_role(*INTERNAL_ROLES)
def recording_attach(job_id):
    """Send the reviewed transcript into the pipeline that already exists, so an
    uploaded-recording brief is the same object as a Fathom one."""
    job = db_session.query(RecordingJob).get(job_id)
    if not job:
        return jsonify({"error": "Recording not found"}), 404
    if job.status not in ('ready', 'attached'):
        return jsonify({"error": f"This recording is {job.status}; wait for it to finish."}), 409

    data = request.get_json(silent=True) or {}
    eng_id = data.get('engagement_id') or job.engagement_id
    if not eng_id:
        return jsonify({"error": "Choose an engagement to attach this transcript to."}), 400

    eng = db_session.query(Engagement).get(eng_id)
    if not eng:
        return jsonify({"error": "Engagement not found"}), 404
    if eng.is_processing:
        return jsonify({"error": "This engagement is already being processed"}), 409

    dispatch = _transcript_dispatch_for(eng.status)
    if not dispatch:
        return jsonify({"error": "This engagement is not in a state that accepts a transcript."}), 400
    kind, task = dispatch

    # Human edits win over the polished text, which wins over the raw text.
    text = (job.edited_text or job.polished_text or job.raw_text or '').strip()
    if not text:
        return jsonify({"error": "This recording produced no text to attach."}), 400

    transcript_row = Transcript(engagement_id=eng.id, kind=kind, raw_text=text,
                                uploaded_by=session.get('user_id'))
    db_session.add(transcript_row)
    eng.is_processing = True
    eng.processing_error = None
    db_session.flush()

    job.status = 'attached'
    job.engagement_id = eng.id
    job.client_id = eng.client_id
    job.attached_transcript_id = transcript_row.id

    db_session.add(AgentEvent(
        engagement_id=eng.id, agent='Recording Studio', trigger='recording_attach',
        reasoning_summary=(
            f"Transcribed '{job.title or job.source_name}' with {job.driver_key} "
            f"and attached it to this engagement."
        ),
        action='Attached Recording Transcript', tokens_used=0,
    ))
    db_session.commit()

    _executor.submit(task, eng.id, transcript_row.id)
    return jsonify({"processing": True, "transcript_id": transcript_row.id}), 202


@app.route('/api/recordings/<int:job_id>/export', methods=['GET'])
@feature('recordings')
@require_role(*INTERNAL_ROLES)
def recording_export(job_id):
    job = db_session.query(RecordingJob).get(job_id)
    if not job:
        return jsonify({"error": "Recording not found"}), 404
    fmt = request.args.get('format', 'txt')
    text = (job.edited_text or job.polished_text or job.raw_text or '')

    if fmt == 'srt':
        segments = (db_session.query(RecordingSegment)
                    .filter_by(job_id=job.id).order_by(RecordingSegment.seq).all())

        def stamp(ms):
            ms = max(0, int(ms or 0))
            h, rem = divmod(ms, 3600000)
            m, rem = divmod(rem, 60000)
            s, ms = divmod(rem, 1000)
            return f"{h:02}:{m:02}:{s:02},{ms:03}"

        body = '\n'.join(
            f"{i + 1}\n{stamp(s.start_ms)} --> {stamp(s.end_ms or (s.start_ms or 0) + 2000)}\n{s.text}\n"
            for i, s in enumerate(segments)
        )
        mimetype, ext = 'application/x-subrip', 'srt'
    elif fmt == 'md':
        body = f"# {job.title or job.source_name}\n\n{text}\n"
        mimetype, ext = 'text/markdown', 'md'
    else:
        body = text
        mimetype, ext = 'text/plain', 'txt'

    filename = f"{secure_filename(job.title or job.source_name or 'transcript')}.{ext}"
    return send_file(io.BytesIO(body.encode('utf-8')), mimetype=mimetype,
                     as_attachment=True, download_name=filename)


# ---------------------------------------------------------------------------
# Speech-to-text (WP-4)
# ---------------------------------------------------------------------------


@app.route('/api/stt/status', methods=['GET'])
@feature('voice')
@require_role(*INTERNAL_ROLES)
def stt_status():
    """What the UI needs to show an honest provider badge and a remaining-budget
    meter, instead of failing mysteriously at request 2,001."""
    from providers.stt.base import rate_status
    out = {}
    for capability in ('stt_live', 'stt_batch'):
        selected, source = provider_registry.current_selection(capability)
        cls = provider_registry.get_driver_class(capability, selected)
        chain = [k for k, _ in transcribe._candidates(capability)]
        out[capability] = {
            "selected": selected,
            "selected_source": source,
            "selected_label": cls.info.label if cls else selected,
            "available": bool(cls and cls.available()),
            "failover_chain": chain,
            "budget": rate_status(selected),
        }
    out['keep_audio'] = Config.STT_KEEP_AUDIO
    out['daily_seconds_per_user'] = Config.STT_DAILY_SECONDS_PER_USER
    out['ffmpeg'] = audio.ffmpeg_available()
    return jsonify(out)


@app.route('/api/stt/chunk', methods=['POST'])
@feature('voice')
@require_role(*INTERNAL_ROLES)
def stt_chunk():
    """Live path: one short chunk of audio in, text out.

    Runs inline rather than on the executor — the caller is a dictation UI that
    needs the text back, and a chunk is seconds of audio, not minutes. It must
    never touch the agent pool.
    """
    upload = request.files.get('audio')
    if not upload:
        return jsonify({"error": "No audio uploaded."}), 400

    data = upload.read()
    if not data:
        return jsonify({"error": "The uploaded chunk was empty."}), 400

    selected = provider_registry.current_selection('stt_live')[0]
    cls = provider_registry.get_driver_class('stt_live', selected)
    max_bytes = getattr(cls, 'max_bytes', 8 * 1024 * 1024) if cls else 8 * 1024 * 1024
    if len(data) > max_bytes:
        return jsonify({"error": f"That chunk is too large ({len(data) // 1024} KB). Record shorter chunks."}), 413

    eng_id = request.form.get('engagement_id', type=int)
    hints = stt_hints.build_hints(eng_id) if eng_id else stt_hints.agency_vocabulary()

    try:
        result = transcribe.transcribe_piece(
            data, upload.mimetype or 'audio/webm', capability='stt_live',
            hints=hints, language=request.form.get('language') or 'en',
            override=driver_override('stt_live'),
        )
    except Exception as e:
        return jsonify({"error": str(e)[:300]}), 503

    return jsonify({
        "text": result['text'],
        "segments": [s.to_json() for s in result['segments']],
        "provider": result['driver'],
        "provider_label": result['driver_label'],
        "is_local": result['is_local'],
        "degraded": result['degraded'],
        "latency_ms": result['latency_ms'],
    })


@app.route('/api/lab/transcribe', methods=['POST'])
@feature('lab')
@require_role('Account Manager', 'Admin')
def lab_transcribe():
    """Audio bake-off: one recording through two to four STT drivers, compared
    side by side. Returns 202; the frontend polls the run like every other job."""
    upload = request.files.get('audio')
    if not upload:
        return jsonify({"error": "Upload an audio file to compare."}), 400
    driver_keys = [k for k in (request.form.get('drivers') or '').split(',') if k]
    if not driver_keys:
        return jsonify({"error": "Pick at least one engine to compare."}), 400

    upload_dir = Path(Config.UPLOAD_DIR) / 'lab'
    upload_dir.mkdir(parents=True, exist_ok=True)
    stored = upload_dir / f"lab_{int(datetime.now().timestamp())}_{secure_filename(upload.filename or 'audio')}"
    upload.save(stored)

    eng_id = request.form.get('engagement_id', type=int)
    hints = stt_hints.build_hints(eng_id) if eng_id else stt_hints.agency_vocabulary()

    run = lab.create_run(
        capability='stt_batch', input_kind='audio', input_ref=str(stored),
        driver_keys=driver_keys, created_by=session.get('user_id'),
        input_meta={"filename": upload.filename, "size_bytes": stored.stat().st_size},
    )
    _executor.submit(lab.run_transcription_comparison, run.id, str(stored), hints)
    return jsonify({"run_id": run.id}), 202


@app.route('/api/lab/runs', methods=['GET'])
@feature('lab')
@require_role(*INTERNAL_ROLES)
def lab_runs():
    runs = db_session.query(ComparisonRun).order_by(ComparisonRun.id.desc()).limit(50).all()
    return jsonify([lab.run_json(r, include_output=False) for r in runs])


@app.route('/api/lab/runs/<int:run_id>', methods=['GET'])
@feature('lab')
@require_role(*INTERNAL_ROLES)
def lab_run_detail(run_id):
    run = db_session.query(ComparisonRun).get(run_id)
    if not run:
        return jsonify({"error": "Run not found"}), 404
    return jsonify(lab.run_json(run))


@app.route('/api/lab/runs/<int:run_id>/adopt', methods=['POST'])
@feature('lab')
@require_role('Admin')
def lab_adopt(run_id):
    """'Use this one' — promote a winning column to the runtime setting."""
    run = db_session.query(ComparisonRun).get(run_id)
    if not run:
        return jsonify({"error": "Run not found"}), 404
    data = request.get_json(silent=True) or {}
    driver_key = data.get('driver_key')
    if not driver_key:
        return jsonify({"error": "driver_key is required"}), 400
    try:
        result = provider_settings.set_driver(
            data.get('capability') or run.capability, driver_key,
            changed_by=session.get('user_id'),
            reason=data.get('reason') or f"Adopted from Lab comparison #{run.id}",
        )
    except provider_settings.SettingsError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(result)


@app.route('/api/authoritative/<int:doc_id>/activate', methods=['POST'])
@feature('auth_data')
@require_role('Account Manager', 'Admin')
def authoritative_activate(doc_id):
    try:
        doc = auth_activate_version(doc_id)
        db_session.commit()
    except AuthoritativeError as e:
        db_session.rollback()
        return jsonify({"error": str(e)}), 400
    return jsonify(_auth_doc_json(doc, include_body=True)), 201

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


def _with_lock(scope, ref_type='engagement'):
    """Wrap an executor task in its scoped AgentLock (WP-3). Two different
    scopes on one engagement now run concurrently; the same scope twice is
    refused by the database's unique constraint rather than by a check-then-set
    on `is_processing`, which two executor threads could both win.

    Owns `db_session.remove()` for the whole task: it must run *after* the lock
    is released, so the release doesn't execute against an already-discarded
    thread-local session."""
    def deco(fn):
        @wraps(fn)
        def inner(eng_id, *args, **kwargs):
            try:
                with agent_lock(scope, ref_type, eng_id, engagement_id=eng_id):
                    return fn(eng_id, *args, **kwargs)
            except AlreadyProcessing as e:
                _fail_processing(eng_id, str(e))
            finally:
                db_session.remove()
        return inner
    return deco


@_with_lock('brief')
def _process_brief_generation(eng_id, transcript_id):
    from agents import generate_brief
    try:
        eng = db_session.query(Engagement).get(eng_id)
        transcript = db_session.query(Transcript).get(transcript_id)
        client_history = _client_relationship_context(eng.client_id, exclude_engagement_id=eng_id)
        reference_material = _reference_material_for(eng_id, transcript.raw_text)
        prompt_body, prompt_ref = auth_resolve('brief_generation_prompt', engagement=eng)

        brief_json = generate_brief(transcript.raw_text, eng.client.name, client_history=client_history, reference_material=reference_material, system_prompt=prompt_body)
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
            tokens_used=tokens,
            authoritative_refs=build_refs(prompt_ref)
        ))
        db_session.commit()
    except Exception as e:
        _fail_processing(eng_id, f"Agent failed: {e}")


@_with_lock('brief')
def _process_brief_refinement(eng_id, transcript_id):
    from agents import refine_brief
    try:
        eng = db_session.query(Engagement).get(eng_id)
        transcript = db_session.query(Transcript).get(transcript_id)
        existing_brief = db_session.query(Brief).filter_by(engagement_id=eng_id).order_by(Brief.id.desc()).first()
        if not existing_brief:
            raise RuntimeError("No existing brief to refine")

        prompt_body, prompt_ref = auth_resolve('brief_refinement_prompt', engagement=eng)
        brief_json = refine_brief(existing_brief, transcript.raw_text, eng.client.name, system_prompt=prompt_body)
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
            tokens_used=tokens,
            authoritative_refs=build_refs(prompt_ref)
        ))
        db_session.commit()
    except Exception as e:
        _fail_processing(eng_id, f"Agent failed: {e}")


@_with_lock('proposal')
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
        proposal_prompt_body, proposal_prompt_ref = auth_resolve('proposal_generation_prompt', engagement=eng)
        signal_prompt_body, signal_prompt_ref = auth_resolve('signal_extraction_prompt', engagement=eng)

        proposal_json = generate_proposal(transcript.raw_text, brief, eng.client.name, past_projects, rate_card, client_history=client_history, reference_material=reference_material, system_prompt=proposal_prompt_body, signal_system_prompt=signal_prompt_body)
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
            tokens_used=proposal_tokens,
            authoritative_refs=build_refs(proposal_prompt_ref)
        ))
        db_session.add(AgentEvent(
            engagement_id=eng_id,
            agent='Signal Extractor',
            trigger='review_meeting_transcript_upload',
            reasoning_summary=extracted_signals_markdown,
            action='Extracted Meeting Signals',
            tokens_used=signal_tokens,
            authoritative_refs=build_refs(signal_prompt_ref)
        ))
        db_session.commit()
    except Exception as e:
        _fail_processing(eng_id, f"Agent failed: {e}")


@_with_lock('proposal')
def _process_proposal_revision(eng_id, proposal_id, notes):
    from agents import revise_proposal
    try:
        eng = db_session.query(Engagement).get(eng_id)
        proposal = db_session.query(Proposal).get(proposal_id)
        rate_card = db_session.query(RateCardItem).all()
        prompt_body, prompt_ref = auth_resolve('proposal_revision_prompt', engagement=eng)

        proposal_json = revise_proposal(proposal, notes, eng.client.name, rate_card, system_prompt=prompt_body)
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
            tokens_used=tokens,
            authoritative_refs=build_refs(prompt_ref)
        ))
        db_session.commit()
    except Exception as e:
        _fail_processing(eng_id, f"Agent failed on revision: {e}")


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
    """Identifies the corpus a cached completeness result was computed against.
    `last_edit` is what makes an in-place edit (Playbook) invalidate that cache —
    count and max_id both stay put when someone only rewords a document."""
    q = db_session.query(
        func.count(RequirementDocument.id),
        func.max(RequirementDocument.id),
        func.max(RequirementDocument.updated_at),
    ).filter(
        RequirementDocument.is_active == True,  # noqa: E712
        RequirementDocument.doc_type.in_([doc_type, 'general'])
    )
    count, max_id, last_edit = q.one()
    return {"count": count or 0, "max_id": max_id or 0,
            "last_edit": last_edit.isoformat() if last_edit else None}


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
    return jsonify([_requirement_json(d) for d in docs])


def _requirement_json(d, include_text=False):
    def username(user_id):
        user = db_session.query(User).get(user_id) if user_id else None
        return user.username if user else None

    out = {
        "id": d.id,
        "title": d.title,
        "doc_type": d.doc_type,
        "uploaded_at": d.uploaded_at.isoformat() if d.uploaded_at else None,
        "uploaded_by": username(d.uploaded_by),
        "updated_at": d.updated_at.isoformat() if d.updated_at else None,
        "updated_by": username(d.updated_by),
        "length": len(d.raw_text or ''),
    }
    if include_text:
        out["raw_text"] = d.raw_text or ''
    return out


@app.route('/api/requirements/<int:doc_id>', methods=['GET', 'PATCH'])
def requirement_detail(doc_id):
    """Read one requirement document in full, or edit it.

    Edits are in place rather than versioned: unlike an AuthoritativeDoc, this is
    a free-text corpus the completeness checker retrieves against, not a pinned
    instruction an AgentEvent has to be able to replay. Bumping `updated_at`
    moves `_requirement_fingerprint`, so every cached brief/proposal completeness
    result computed against the old wording is flagged stale rather than quietly
    surviving the edit.
    """
    doc = db_session.query(RequirementDocument).get(doc_id)
    if not doc or not doc.is_active:
        return jsonify({"error": "Not found"}), 404

    if request.method == 'PATCH':
        if session.get('role') not in ('Account Manager', 'Admin'):
            return jsonify({"error": "Account Manager or Admin role required."}), 403

        data = request.get_json(silent=True) or {}
        if 'doc_type' in data:
            if data['doc_type'] not in ('brief', 'proposal', 'general'):
                return jsonify({"error": "doc_type must be one of: brief, proposal, general"}), 400
            doc.doc_type = data['doc_type']
        if 'title' in data:
            title = (data.get('title') or '').strip()
            if not title:
                return jsonify({"error": "Title is required"}), 400
            doc.title = title
        if 'raw_text' in data:
            raw_text = (data.get('raw_text') or '').strip()
            if not raw_text:
                return jsonify({"error": "Document text is required"}), 400
            doc.raw_text = raw_text
        doc.updated_at = datetime.now()
        doc.updated_by = session.get('user_id')
        db_session.commit()

    return jsonify(_requirement_json(doc, include_text=True))


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


@app.route('/api/clients/<int:client_id>', methods=['PATCH'])
@require_role('Account Manager', 'Admin')
def patch_client(client_id):
    """Contact details — needed before a proposal can be emailed (WP-12)."""
    client = db_session.query(Client).get(client_id)
    if not client:
        return jsonify({"error": "Client not found"}), 404
    data = request.get_json(silent=True) or {}
    for field in ('name', 'industry', 'notes', 'contact_email', 'contact_name'):
        if field in data:
            setattr(client, field, (data[field] or None))
    db_session.commit()
    return jsonify({"id": client.id, "contact_email": client.contact_email,
                    "contact_name": client.contact_name})


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
        "contact_email": client.contact_email,
        "contact_name": client.contact_name,
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
        "client_contact_email": eng.client.contact_email,
        "client_contact_name": eng.client.contact_name,
        "status": eng.status,
        "is_processing": bool(eng.is_processing),
        "processing_error": eng.processing_error,
        # Paste into a calendar invite title and the Fathom transcript attaches
        # itself to this exact engagement — see _match_engagement_by_tag().
        "eng_tag": f"[ENG-{eng.id:04d}]",
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
    #
    # `is_processing` is set here rather than left to the worker's AgentLock so
    # the flag is already true when the frontend's first poll lands, which can
    # beat the executor thread to the database. The lock is what actually
    # enforces exclusion; this is the spinner.
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


ENG_TAG = re.compile(r"\[ENG-(\d+)\]", re.IGNORECASE)

# Defaults used when no `fathom_matching` authoritative doc has been seeded.
# Kept in code as the guaranteed floor — auto-attaching to the wrong client is
# the one failure mode worse than a human clicking Attach, so this path must
# never depend on a database row existing.
LEGACY_FATHOM_MATCHING = {"fuzzy_threshold": 0.75, "min_client_name_length": 3}


def _match_engagement_by_tag(title):
    """Engagement named by an explicit [ENG-0042] tag in the meeting title.

    Checked before any name matching: it resolves to a *specific engagement*
    rather than a client, so it also disambiguates a client with several open
    engagements — which name matching cannot do, since _open_engagement_for()
    just takes the most recent."""
    if not title:
        return None
    m = ENG_TAG.search(title)
    if not m:
        return None
    eng = db_session.query(Engagement).get(int(m.group(1)))
    if eng and eng.status in DISPATCHABLE_STATUSES and not is_locked(eng.id):
        return eng
    return None


def _auto_match_client(title, mode=None):
    """The single client this meeting title unambiguously names, or None.

    Thin wrapper over the `client_match` capability — the matching itself lives
    in providers/client_match/matchers.py so it is switchable at runtime and
    exists in exactly one place. Zero or several candidates always return None
    so the item stays pending in the Inbox for a human; fuzziness widens what
    counts as a confident match but must never turn an ambiguous case into a
    confident auto-attach.
    """
    if not title:
        return None

    cfg, _ = auth_resolve('fathom_matching')
    if cfg is None:
        cfg = LEGACY_FATHOM_MATCHING

    driver = provider_registry.get('client_match', override=mode or driver_override('client_match'))
    clients = db_session.query(Client).all()
    return driver.match(title, clients, cfg)


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

    # Auto-attach on either an explicit [ENG-0042] tag (deterministic, wins
    # outright) or a single confident client-name match. Zero or ambiguous
    # matches wait in the inbox for a human — see _auto_match_client().
    auto_processed = False
    tagged_eng = _match_engagement_by_tag(parsed['title'])
    if tagged_eng:
        auto_processed = _attach_inbound(inbound, tagged_eng, user_id=None, auto=True)
    elif parsed['is_external_meeting']:
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
  <p class="eyebrow">The Exodus &middot; {_esc(eyebrow)}</p>
  <h1>{_esc(heading)}</h1>
  {badge_html}
</div>
<div class="body">
{body_html}
</div>
<div class="footer">Generated by The Exodus on {datetime.now().strftime('%B %d, %Y')}</div>
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


@app.route('/api/engagements/<int:eng_id>/proposal/send-email', methods=['POST'])
@feature('email')
@require_role('Account Manager', 'Admin')
def send_proposal_email(eng_id):
    """Reuses the *existing* approval gate and the existing PDF builder —
    deliberately not a new rule and not a second renderer."""
    eng = db_session.query(Engagement).get(eng_id)
    if not eng:
        return jsonify({"error": "Engagement not found"}), 404

    proposal = (db_session.query(Proposal).filter_by(engagement_id=eng_id)
                .order_by(Proposal.id.desc()).first())
    if not proposal or proposal.status != 'approved':
        return jsonify({"error": "This proposal has not been approved yet."}), 409

    data = request.get_json(silent=True) or {}
    to = (data.get('to') or eng.client.contact_email or '').strip()
    if not to:
        return jsonify({"error": "No contact email on file for this client. Add one first."}), 400

    cover_note, _prov = auth_resolve('email_cover_note', engagement=eng)
    contact_name = data.get('contact_name') or eng.client.contact_name
    sender = db_session.query(User).get(session.get('user_id'))
    subject, body = mailer.proposal_email(
        eng, proposal, contact_name, sender.username if sender else 'The team', cover_note)
    if data.get('body'):
        body = data['body']
    if data.get('subject'):
        subject = data['subject']

    attachments = []
    try:
        pdf = io.BytesIO()
        HTML(string=build_proposal_pdf_html(proposal, eng.client.name)).write_pdf(pdf)
        attachments.append({
            "filename": f"{eng.client.name.replace(' ', '_')}_Proposal.pdf",
            "content": pdf.getvalue(), "mime_type": "application/pdf",
        })
    except Exception as e:
        return jsonify({"error": f"Could not build the proposal PDF: {str(e)[:200]}"}), 500

    result = mailer.send(to, subject, body, attachments=attachments)

    db_session.add(AgentEvent(
        engagement_id=eng_id, agent='Email', trigger='proposal_send_email',
        reasoning_summary=(f"Sent the approved proposal to {to} via {result['driver_label']}."
                           if result['ok'] else f"Failed to send to {to}: {result['detail']}"),
        action='Emailed Proposal' if result['ok'] else 'Proposal Email Failed', tokens_used=0,
    ))
    db_session.commit()

    if not result['ok']:
        return jsonify({"error": result['detail'], "driver": result['driver']}), 502
    return jsonify({"sent": True, "to": to, "driver": result['driver'],
                    "driver_label": result['driver_label'], "detail": result['detail']})


if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5000)
