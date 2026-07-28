"""Assignment lifecycle — WP-10 §10.3.

Every token movement writes a `TokenLedger` row with `ref_type='assignment'`, so
a talent's ledger reads as a narrative of their year rather than a mystery
number.
"""
import datetime

from database import db_session
from models import Assignment, Talent
import tokens as tokens_mod

VALID_TRANSITIONS = {
    'shortlisted': ('offered', 'cancelled'),
    'offered': ('accepted', 'declined', 'expired', 'cancelled'),
    'accepted': ('completed', 'cancelled', 'no_show'),
    'declined': (),
    'expired': (),
    'cancelled': (),
    'completed': (),
    'no_show': (),
}


class LifecycleError(ValueError):
    """An illegal state transition."""


def offer(assignment, pol=None):
    from casting import policy as casting_policy
    pol = pol or casting_policy()[0]
    assignment.status = 'offered'
    assignment.offered_at = datetime.datetime.utcnow()
    db_session.commit()
    return assignment


def accept(assignment):
    """Accepting costs tokens, creates the busy block, and resets idle accrual —
    all three together, or the fair-share queue stops being fair."""
    from availability import block_for_assignment

    talent = db_session.query(Talent).get(assignment.talent_id)
    pol, _ = tokens_mod.policy()

    assignment.status = 'accepted'
    assignment.responded_at = datetime.datetime.utcnow()
    talent.last_assigned_at = datetime.datetime.utcnow()   # zeroes idle accrual
    block_for_assignment(assignment)
    db_session.commit()

    tokens_mod.award(
        talent.id, (pol.get('spend') or {}).get('assignment_accepted', -40),
        reason='assignment_accepted', ref_type='assignment', ref_id=assignment.id,
        note=f"Accepted: {assignment.role or 'engagement'}",
    )
    return assignment


def decline(assignment, reason=None):
    """Costs nothing by design — see tokens.py. Tracked, not priced."""
    assignment.status = 'declined'
    assignment.responded_at = datetime.datetime.utcnow()
    if reason:
        assignment.concerns = (assignment.concerns or '') + f"\nDeclined: {reason}"
    db_session.commit()
    return assignment


def complete(assignment, rating=None, on_time=True):
    from models import AvailabilityBlock

    pol, _ = tokens_mod.policy()
    assignment.status = 'completed'
    assignment.completed_at = datetime.datetime.utcnow()
    if rating is not None:
        assignment.rating = rating
    db_session.commit()

    if on_time:
        tokens_mod.award(
            assignment.talent_id, (pol.get('earn') or {}).get('assignment_completed_on_time', 15),
            reason='assignment_completed_on_time', ref_type='assignment', ref_id=assignment.id,
            note=f"Completed: {assignment.role or 'engagement'}",
        )
    if rating == 5:
        tokens_mod.award(
            assignment.talent_id, (pol.get('earn') or {}).get('client_rating_5', 10),
            reason='client_rating_5', ref_type='assignment', ref_id=assignment.id,
        )

    if rating is not None:
        rated = db_session.query(Assignment).filter(
            Assignment.talent_id == assignment.talent_id,
            Assignment.rating.isnot(None)).all()
        if rated:
            talent = db_session.query(Talent).get(assignment.talent_id)
            talent.avg_rating = round(sum(a.rating for a in rated) / len(rated), 2)
            db_session.commit()
    return assignment


def cancel(assignment, late=False):
    from models import AvailabilityBlock

    pol, _ = tokens_mod.policy()
    was_accepted = assignment.status == 'accepted'
    assignment.status = 'cancelled'
    db_session.query(AvailabilityBlock).filter_by(
        source='assignment', ref_id=assignment.id).delete()
    db_session.commit()

    if was_accepted and late:
        tokens_mod.award(
            assignment.talent_id, (pol.get('spend') or {}).get('late_cancellation', -25),
            reason='late_cancellation', ref_type='assignment', ref_id=assignment.id,
        )
    return assignment


def mark_no_show(assignment):
    pol, _ = tokens_mod.policy()
    assignment.status = 'no_show'
    db_session.commit()
    tokens_mod.award(
        assignment.talent_id, (pol.get('spend') or {}).get('no_show', -50),
        reason='no_show', ref_type='assignment', ref_id=assignment.id,
    )
    return assignment


def expire_stale_offers():
    """Lazy expiry — called on read, so there is no cron. An expired offer frees
    the next shortlist candidate without re-running the casting agent."""
    from casting import policy as casting_policy
    pol, _ = casting_policy()
    hours = pol.get('offer_expiry_hours', 48)
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=hours)
    stale = db_session.query(Assignment).filter(
        Assignment.status == 'offered',
        Assignment.offered_at.isnot(None),
        Assignment.offered_at < cutoff,
    ).all()
    for a in stale:
        a.status = 'expired'
    if stale:
        db_session.commit()
    return len(stale)


def transition(assignment, to_status, **kwargs):
    allowed = VALID_TRANSITIONS.get(assignment.status, ())
    if to_status not in allowed:
        raise LifecycleError(
            f"An assignment that is '{assignment.status}' cannot become '{to_status}'."
        )
    if to_status == 'offered':
        return offer(assignment)
    if to_status == 'accepted':
        return accept(assignment)
    if to_status == 'declined':
        return decline(assignment, kwargs.get('reason'))
    if to_status == 'completed':
        return complete(assignment, kwargs.get('rating'), kwargs.get('on_time', True))
    if to_status == 'cancelled':
        return cancel(assignment, kwargs.get('late', False))
    if to_status == 'no_show':
        return mark_no_show(assignment)
    if to_status == 'expired':
        assignment.status = 'expired'
        db_session.commit()
        return assignment
    raise LifecycleError(f"Unhandled transition to {to_status}")


def assignment_json(a, include_talent=True):
    out = {
        "id": a.id, "engagement_id": a.engagement_id, "talent_id": a.talent_id,
        "role": a.role, "status": a.status, "rate_kes": a.rate_kes,
        "start_at": a.start_at.isoformat() if a.start_at else None,
        "end_at": a.end_at.isoformat() if a.end_at else None,
        "score": a.score, "score_breakdown": a.score_breakdown,
        "rationale": a.rationale, "concerns": a.concerns, "rating": a.rating,
        "offered_at": a.offered_at.isoformat() if a.offered_at else None,
        "responded_at": a.responded_at.isoformat() if a.responded_at else None,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }
    if include_talent:
        t = db_session.query(Talent).get(a.talent_id)
        if t:
            out["talent"] = {"id": t.id, "name": t.name, "title": t.title,
                             "engagement_type": t.engagement_type,
                             "day_rate_kes": t.day_rate_kes, "avg_rating": t.avg_rating}
    return out
