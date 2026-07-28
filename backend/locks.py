"""Scoped agent locking — WP-3.

Replaces `Engagement.is_processing` as the *mechanism* for "don't run this
twice", while keeping that column in sync as a derived value so existing
polling/spinner code keeps working.

Two properties matter here and both come from the database, not from Python:

1. **Uniqueness is a constraint** (`uq_agent_lock` on scope/ref_type/ref_id).
   A check-then-insert in application code would let two executor threads both
   observe "not locked" and both proceed. The INSERT is the acquire; an
   IntegrityError is the "someone else has it" signal.
2. **Locks expire.** A worker killed mid-call used to wedge an engagement until
   someone edited the database by hand. The next acquire reaps anything past
   `expires_at` and logs an AgentEvent so the reap is visible, not silent.

Usage — always as a context manager, so the release runs on the exception path
too:

    with agent_lock('brief', 'engagement', eng_id, engagement_id=eng_id):
        ...
"""
import datetime
from contextlib import contextmanager

from sqlalchemy.exc import IntegrityError

from database import db_session
from models import AgentEvent, AgentLock, Engagement

DEFAULT_TTL_MINUTES = 15


class AlreadyProcessing(RuntimeError):
    """Raised when the lock is already held. Routes translate this to HTTP 409."""

    def __init__(self, scope):
        super().__init__(f"Another '{scope}' job is already running for this item.")
        self.scope = scope


def _reap_stale(scope, ref_type, ref_id):
    """Delete an expired lock so a dead worker doesn't wedge the row forever.
    Logs an AgentEvent when it fires — a reap means something crashed, and that
    should be visible in the activity log rather than silently swallowed."""
    now = datetime.datetime.utcnow()
    stale = db_session.query(AgentLock).filter(
        AgentLock.scope == scope,
        AgentLock.ref_type == ref_type,
        AgentLock.ref_id == ref_id,
        AgentLock.expires_at.isnot(None),
        AgentLock.expires_at < now,
    ).all()

    for lock in stale:
        held_for = (now - lock.locked_at).total_seconds() / 60 if lock.locked_at else None
        db_session.add(AgentEvent(
            engagement_id=lock.engagement_id,
            agent='System',
            trigger='stale_lock_reaped',
            reasoning_summary=(
                f"A '{lock.scope}' lock outlived its {DEFAULT_TTL_MINUTES}-minute TTL"
                + (f" (held {held_for:.0f} min)" if held_for is not None else "")
                + " and was released. The worker holding it most likely died mid-run."
            ),
            action='Released a stale agent lock',
            tokens_used=0,
        ))
        db_session.delete(lock)

    if stale:
        db_session.commit()
    return len(stale)


def is_locked(engagement_id, scope=None):
    """True when any (or one named) agent job is in flight for this engagement.
    This is the source of truth behind the derived `is_processing` value."""
    q = db_session.query(AgentLock).filter(AgentLock.engagement_id == engagement_id)
    if scope:
        q = q.filter(AgentLock.scope == scope)
    return db_session.query(q.exists()).scalar()


def _sync_is_processing(engagement_id):
    """Keep the legacy boolean consistent with the lock table. `EngagementDetail.jsx`
    polls it and every existing route checks it, so it stays accurate rather than
    being ripped out — but the lock rows are what actually enforce exclusion."""
    if engagement_id is None:
        return
    eng = db_session.query(Engagement).get(engagement_id)
    if eng:
        eng.is_processing = is_locked(engagement_id)


@contextmanager
def agent_lock(scope, ref_type, ref_id, engagement_id=None, locked_by=None, ttl_minutes=DEFAULT_TTL_MINUTES):
    """Acquire an exclusive lock, or raise AlreadyProcessing.

    The INSERT *is* the acquire — an IntegrityError from the unique constraint
    is how a contended lock reports itself, which is what makes this safe
    against two executor threads racing.
    """
    _reap_stale(scope, ref_type, ref_id)

    lock = AgentLock(
        scope=scope, ref_type=ref_type, ref_id=ref_id, engagement_id=engagement_id,
        locked_by=locked_by,
        locked_at=datetime.datetime.utcnow(),
        expires_at=datetime.datetime.utcnow() + datetime.timedelta(minutes=ttl_minutes),
    )
    db_session.add(lock)
    try:
        db_session.commit()
    except IntegrityError:
        db_session.rollback()
        raise AlreadyProcessing(scope)

    lock_id = lock.id
    try:
        _sync_is_processing(engagement_id)
        db_session.commit()
        yield lock
    finally:
        # Release must survive both the happy path and any exception raised
        # inside the with-block — otherwise a single agent failure wedges the
        # engagement until the TTL expires. rollback() first because the caller
        # may be unwinding from a failed flush, which would poison this delete.
        db_session.rollback()
        db_session.query(AgentLock).filter_by(id=lock_id).delete()
        db_session.commit()
        _sync_is_processing(engagement_id)
        db_session.commit()
