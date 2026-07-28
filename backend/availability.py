"""Talent availability — WP-9 §9.3.

Absence of data means available. A conflict is any overlap with a `busy` or
`leave` block, or with an active assignment window.
"""
import datetime
import re

from database import db_session
from models import Assignment, AvailabilityBlock

BLOCKING_KINDS = ('busy', 'leave')


def is_available(talent_id, start, end):
    """(available, reason). `reason` is human-readable so the UI can say why."""
    if not start or not end:
        return True, None

    clash = db_session.query(AvailabilityBlock).filter(
        AvailabilityBlock.talent_id == talent_id,
        AvailabilityBlock.kind.in_(BLOCKING_KINDS),
        AvailabilityBlock.start_at < end,
        AvailabilityBlock.end_at > start,
    ).first()
    if clash:
        return False, f"{clash.kind} {clash.start_at:%d %b}–{clash.end_at:%d %b}"

    assigned = db_session.query(Assignment).filter(
        Assignment.talent_id == talent_id,
        Assignment.status.in_(('accepted', 'offered')),
        Assignment.start_at.isnot(None), Assignment.end_at.isnot(None),
        Assignment.start_at < end, Assignment.end_at > start,
    ).first()
    if assigned:
        return False, f"already on an engagement {assigned.start_at:%d %b}–{assigned.end_at:%d %b}"

    return True, None


def block_for_assignment(assignment):
    """Accepting work auto-creates a busy block, so the calendar stays true
    without anyone maintaining it."""
    if not (assignment.start_at and assignment.end_at):
        return None
    existing = db_session.query(AvailabilityBlock).filter_by(
        talent_id=assignment.talent_id, source='assignment', ref_id=assignment.id).first()
    if existing:
        return existing
    block = AvailabilityBlock(
        talent_id=assignment.talent_id, start_at=assignment.start_at, end_at=assignment.end_at,
        kind='busy', source='assignment', ref_id=assignment.id,
        note=f"Assigned: {assignment.role or 'engagement'}",
    )
    db_session.add(block)
    return block


# --- .ics import -------------------------------------------------------------
# Deliberately a paste-or-URL parse rather than Google OAuth: the parse path is
# the real work, so swapping in a live connector later touches one function.

_ICS_DT = re.compile(r'^(?:DTSTART|DTEND)(?:;[^:]*)?:(\d{8}T?\d{0,6}Z?)', re.MULTILINE)


def _parse_ics_datetime(value):
    value = value.strip().rstrip('Z')
    for fmt in ('%Y%m%dT%H%M%S', '%Y%m%d'):
        try:
            return datetime.datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def parse_ics(text):
    """Minimal VEVENT extraction. Uses the stdlib rather than adding a calendar
    dependency for what is, this cycle, a mocked import path."""
    events = []
    for block in re.split(r'BEGIN:VEVENT', text or '')[1:]:
        body = block.split('END:VEVENT')[0]
        starts = re.search(r'^DTSTART(?:;[^:]*)?:([0-9TZ]+)', body, re.MULTILINE)
        ends = re.search(r'^DTEND(?:;[^:]*)?:([0-9TZ]+)', body, re.MULTILINE)
        summary = re.search(r'^SUMMARY:(.*)$', body, re.MULTILINE)
        if not starts:
            continue
        start = _parse_ics_datetime(starts.group(1))
        end = _parse_ics_datetime(ends.group(1)) if ends else None
        if not start:
            continue
        events.append({
            "start_at": start,
            "end_at": end or (start + datetime.timedelta(hours=1)),
            "note": (summary.group(1).strip()[:200] if summary else None),
        })
    return events


def import_ics(talent_id, text):
    created = 0
    for event in parse_ics(text):
        db_session.add(AvailabilityBlock(
            talent_id=talent_id, start_at=event['start_at'], end_at=event['end_at'],
            kind='busy', source='ics', note=event['note'],
        ))
        created += 1
    db_session.commit()
    return created
