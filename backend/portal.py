"""Talent-facing portal — WP-11.

**The isolation invariant, stated once:** every query in this module is filtered
by `session['talent_id']` at the query level. **No route here accepts a
`talent_id` parameter.** Talents are external users on the public internet; an
id in a request body is an id an attacker controls.

What a talent must never see: `Talent.notes`, anyone else's ledger or score,
rate cards, proposals, briefs, engagement financials, or their own rank relative
to named others. Show *their* components; never the leaderboard. A visible
ranking turns a fair-rotation queue into a competitive one and invites gaming.
"""
import datetime
import hashlib
import secrets
from functools import wraps

from flask import jsonify, session
from werkzeug.security import check_password_hash, generate_password_hash

from database import db_session
from models import (Assignment, AvailabilityBlock, Certification, CertificationEnrollment,
                    Event, EventAttendance, PortfolioItem, Skill, Talent, TalentSkill)
import tokens as tokens_mod

MIN_PASSWORD_LENGTH = 10
INVITE_TTL_HOURS = 72

# In-process, single-worker deployment: good enough for invite tokens and login
# throttling without adding Redis. Both are short-lived by design.
_invites = {}
_login_attempts = {}


def require_talent(fn):
    @wraps(fn)
    def inner(*args, **kwargs):
        if session.get('role') != 'Talent' or not session.get('talent_id'):
            return jsonify({"error": "Talent login required."}), 401
        return fn(*args, **kwargs)
    return inner


def current_talent():
    """The only way this module resolves a talent. Never from request input."""
    return db_session.query(Talent).get(session.get('talent_id'))


# --- invite / auth -----------------------------------------------------------

def create_invite(talent_id):
    token = secrets.token_urlsafe(32)
    _invites[hashlib.sha256(token.encode()).hexdigest()] = {
        "talent_id": talent_id,
        "expires_at": datetime.datetime.utcnow() + datetime.timedelta(hours=INVITE_TTL_HOURS),
    }
    talent = db_session.query(Talent).get(talent_id)
    if talent:
        talent.portal_invited_at = datetime.datetime.utcnow()
        db_session.commit()
    return token


def redeem_invite(token, password):
    digest = hashlib.sha256((token or '').encode()).hexdigest()
    entry = _invites.get(digest)
    if not entry or entry['expires_at'] < datetime.datetime.utcnow():
        return None, "That invite link has expired or is not valid. Ask your producer for a new one."
    if len(password or '') < MIN_PASSWORD_LENGTH:
        return None, f"Choose a password of at least {MIN_PASSWORD_LENGTH} characters."

    talent = db_session.query(Talent).get(entry['talent_id'])
    if not talent:
        return None, "That account no longer exists."
    talent.portal_password_hash = generate_password_hash(password)
    db_session.commit()
    _invites.pop(digest, None)      # single use
    return talent, None


def throttled(ip):
    """10 attempts per hour per IP, then a lockout."""
    now = datetime.datetime.utcnow()
    attempts = [t for t in _login_attempts.get(ip, []) if (now - t).total_seconds() < 3600]
    _login_attempts[ip] = attempts
    return len(attempts) >= 10


def record_attempt(ip):
    _login_attempts.setdefault(ip, []).append(datetime.datetime.utcnow())


def authenticate(email, password):
    talent = db_session.query(Talent).filter(Talent.email == (email or '').strip().lower()).first()
    if not talent or not talent.portal_password_hash:
        return None
    if (talent.status or 'active') != 'active' or not talent.is_active:
        return None
    if not check_password_hash(talent.portal_password_hash, password or ''):
        return None
    return talent


# --- portal payloads ---------------------------------------------------------

def me_json(talent):
    balance = tokens_mod.balance(talent)
    return {
        "id": talent.id, "name": talent.name, "email": talent.email,
        "phone": talent.phone, "title": talent.title, "seniority": talent.seniority,
        "engagement_type": talent.engagement_type, "day_rate_kes": talent.day_rate_kes,
        "location": talent.location, "highlight": talent.highlight,
        "avatar_url": talent.avatar_url, "avg_rating": talent.avg_rating,
        "skills": [s for s in (talent.skills or [])],
        "tokens": balance,
        # Deliberately absent: notes, other talents, scores, rates cards.
    }


def offers_json(talent):
    from casting import policy as casting_policy
    pol, _ = casting_policy()
    hours = pol.get('offer_expiry_hours', 48)

    rows = (db_session.query(Assignment)
            .filter(Assignment.talent_id == talent.id,
                    Assignment.status.in_(('offered', 'accepted', 'completed')))
            .order_by(Assignment.id.desc()).all())
    out = []
    for a in rows:
        expires_at = (a.offered_at + datetime.timedelta(hours=hours)) if a.offered_at else None
        out.append({
            "id": a.id, "role": a.role, "status": a.status, "rate_kes": a.rate_kes,
            "start_at": a.start_at.isoformat() if a.start_at else None,
            "end_at": a.end_at.isoformat() if a.end_at else None,
            "offered_at": a.offered_at.isoformat() if a.offered_at else None,
            "expires_at": expires_at.isoformat() if expires_at else None,
            # No client name, no engagement financials, no score.
        })
    return out


def certifications_json(talent):
    catalog = db_session.query(Certification).all()
    enrolled = {e.certification_id: e for e in
                db_session.query(CertificationEnrollment).filter_by(talent_id=talent.id).all()}
    now = datetime.datetime.utcnow()
    out = []
    for cert in catalog:
        e = enrolled.get(cert.id)
        expired = bool(e and e.expires_at and e.expires_at < now)
        out.append({
            "key": cert.key, "name": cert.name, "provider": cert.provider,
            "category": cert.category, "token_award": cert.token_award,
            "validity_months": cert.validity_months, "is_mock": cert.is_mock,
            "enrollment": None if not e else {
                "id": e.id,
                "status": 'expired' if expired else e.status,
                "score": e.score, "attempts": e.attempts,
                "completed_at": e.completed_at.isoformat() if e.completed_at else None,
                "expires_at": e.expires_at.isoformat() if e.expires_at else None,
            },
        })
    return out


def catalog_questions(cert_key):
    """Quiz questions live in the certification_catalog authoritative document,
    so they are editable without a deploy."""
    from authoritative import resolve as auth_resolve
    body, _prov = auth_resolve('certification_catalog')
    for entry in ((body or {}).get('certifications') or []):
        if entry.get('key') == cert_key:
            return entry
    return None


def grade(cert_entry, answers):
    questions = cert_entry.get('questions') or []
    if not questions:
        return 0.0, 0, 0
    correct = sum(1 for i, q in enumerate(questions)
                  if i < len(answers) and answers[i] == q.get('answer'))
    return correct / len(questions), correct, len(questions)


def next_best_action(talent):
    """The highest-leverage thing this talent could do next. Concrete, not vague —
    'complete On-Set Safety L1: +15 tokens' beats 'engage more'."""
    done = {e.certification_id for e in db_session.query(CertificationEnrollment)
            .filter_by(talent_id=talent.id, status='completed').all()}
    best = None
    for cert in db_session.query(Certification).all():
        if cert.id in done:
            continue
        if best is None or (cert.token_award or 0) > (best.token_award or 0):
            best = cert
    if best:
        return {"kind": "certification", "key": best.key,
                "text": f"Complete {best.name}: +{best.token_award} tokens."}

    upcoming = (db_session.query(Event)
                .filter(Event.starts_at >= datetime.datetime.utcnow())
                .order_by(Event.starts_at).first())
    if upcoming:
        return {"kind": "event", "key": str(upcoming.id),
                "text": f"Attend {upcoming.name}: +{upcoming.token_award} tokens."}
    return None
