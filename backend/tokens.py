"""Token mechanics — WP-9 §9.2.

Three decisions here will be questioned, so they are stated plainly:

**Idle tokens are computed, never written.** No cron, no scheduler, no drift, no
missed-run backfill. The value is a pure function of `last_assigned_at` and the
policy: deterministic, testable, and instantly correct the moment the policy
changes.

**Accepting an assignment costs tokens.** That is what makes this a fair-share
queue rather than a leaderboard. Without a spend, the same high-token talent wins
every casting run forever and the mechanism collapses into "rank by seniority."
Working draws down priority; idleness rebuilds it.

**Declining costs nothing.** Penalising declines punishes talent for being
honestly unavailable and teaches them to accept work they cannot do. Declines are
tracked for visibility, not priced. *Late cancellation after accepting* is
different, and is penalised, because that one has a real production cost.
"""
import datetime

from sqlalchemy import func, or_

from database import db_session
from models import Assignment, TokenLedger

DEFAULT_TOKEN_POLICY = {
    "earn": {
        "event_attendance": 10,
        "certification_completed": {"default": 25, "by_category": {"safety": 15, "craft": 30, "software": 20}},
        "assignment_completed_on_time": 15,
        "client_rating_5": 10,
        "referral_hired": 20,
    },
    "spend": {"assignment_accepted": -40, "no_show": -50, "late_cancellation": -25},
    "idle_accrual": {"tokens_per_idle_day": 2, "starts_after_days": 3, "cap": 60},
    "expiry_days": 365,
    "floor": 0,
    "decline_penalty": 0,
}


def policy():
    from authoritative import resolve as auth_resolve
    body, prov = auth_resolve('talent_token_policy')
    if body is None:
        return DEFAULT_TOKEN_POLICY, {"key": "talent_token_policy", "scope": "legacy_constant", "version": 0}
    return body, prov


def balance(talent, at=None):
    """The full breakdown, not just a number — the UI and the talent both need
    the *why*."""
    pol, prov = policy()
    now = at or datetime.datetime.utcnow()

    ledger = db_session.query(func.coalesce(func.sum(TokenLedger.delta), 0)).filter(
        TokenLedger.talent_id == talent.id,
        or_(TokenLedger.expires_at.is_(None), TokenLedger.expires_at > now),
    ).scalar() or 0

    accrual = pol.get('idle_accrual', {})
    anchor = talent.last_assigned_at or talent.created_at
    idle_days = (now - anchor).days if anchor else 0
    idle = min(
        max(idle_days - accrual.get('starts_after_days', 3), 0) * accrual.get('tokens_per_idle_day', 2),
        accrual.get('cap', 60),
    )

    return {
        "total": max(pol.get('floor', 0), ledger + idle),
        "ledger": int(ledger),
        "idle": idle,
        "idle_days": idle_days,
        "policy_version": (prov or {}).get('version'),
    }


def award(talent_id, delta, reason, ref_type=None, ref_id=None, note=None, created_by=None, expires_days=None):
    """Append a ledger row, or do nothing if this exact award already exists.

    Idempotency comes from the unique constraint, not from a pre-check — a
    concurrent retry cannot slip between a SELECT and an INSERT.
    """
    from sqlalchemy.exc import IntegrityError

    pol, _prov = policy()
    days = expires_days if expires_days is not None else pol.get('expiry_days')
    expires_at = (datetime.datetime.utcnow() + datetime.timedelta(days=days)) if days and delta > 0 else None

    row = TokenLedger(
        talent_id=talent_id, delta=delta, reason=reason, ref_type=ref_type,
        ref_id=ref_id, note=note, created_by=created_by, expires_at=expires_at,
    )
    db_session.add(row)
    try:
        db_session.commit()
        return row
    except IntegrityError:
        db_session.rollback()
        return None   # already awarded — not an error


def certification_award(category):
    pol, _ = policy()
    spec = (pol.get('earn') or {}).get('certification_completed', 25)
    if isinstance(spec, dict):
        return (spec.get('by_category') or {}).get(category, spec.get('default', 25))
    return spec


def ledger_json(talent_id, limit=200):
    """Full history with a running balance — this is the answer to "why do I have
    74 tokens?", which is the whole reason the ledger is append-only."""
    rows = (db_session.query(TokenLedger)
            .filter_by(talent_id=talent_id)
            .order_by(TokenLedger.created_at, TokenLedger.id)
            .limit(limit).all())
    running = 0
    out = []
    for r in rows:
        running += r.delta
        out.append({
            "id": r.id, "delta": r.delta, "reason": r.reason, "ref_type": r.ref_type,
            "ref_id": r.ref_id, "note": r.note, "running_balance": running,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "expires_at": r.expires_at.isoformat() if r.expires_at else None,
        })
    out.reverse()
    return out


def decline_count(talent_id, days=90):
    since = datetime.datetime.utcnow() - datetime.timedelta(days=days)
    return db_session.query(func.count(Assignment.id)).filter(
        Assignment.talent_id == talent_id,
        Assignment.status == 'declined',
        Assignment.responded_at >= since,
    ).scalar() or 0
