"""Spelling hints for the speech engines — WP-4 §4.3.

Both Groq and Whisper accept a `prompt` field (~224 tokens) that biases spelling.
Feeding it the names actually involved in this engagement is the cheapest
accuracy win available anywhere in the system: Kenyan client and talent names
are exactly the vocabulary a generic Whisper model mangles, and no amount of
model upgrading fixes a name it has never seen.
"""
from database import db_session
from models import Client, Engagement, StaffingPlan, Talent, Transcript

# The field is ~224 tokens. Well under that, because a long prompt starts biasing
# the transcription itself rather than just its spelling.
MAX_HINT_CHARS = 900


def build_hints(engagement_id=None, extra_names=()):
    """A comma-separated name list for the engine's prompt field.

    Ordered by how much the engine needs the help: the client's own name first
    (it appears constantly and is the most costly to get wrong), then people,
    then general agency vocabulary.
    """
    names = []

    def add(value):
        value = (value or '').strip()
        if value and value not in names:
            names.append(value)

    if engagement_id:
        eng = db_session.query(Engagement).get(engagement_id)
        if eng:
            if eng.client:
                add(eng.client.name)
                add(eng.client.industry)

            # Stakeholders and attendees the pipeline has already seen — these are
            # the names most likely to recur in the next meeting.
            latest = (db_session.query(Transcript)
                      .filter_by(engagement_id=engagement_id)
                      .order_by(Transcript.id.desc()).first())
            if latest:
                for attendee in (latest.attendees or [])[:8]:
                    add(attendee)

            from models import Brief
            brief = (db_session.query(Brief)
                     .filter_by(engagement_id=engagement_id)
                     .order_by(Brief.id.desc()).first())
            if brief:
                for person in ((brief.structured_json or {}).get('key_stakeholders') or [])[:8]:
                    add(person)

            plan = (db_session.query(StaffingPlan)
                    .filter_by(engagement_id=engagement_id)
                    .order_by(StaffingPlan.id.desc()).first())
            if plan:
                for member in ((plan.plan or {}).get('team') or [])[:8]:
                    add((member.get('talent') or {}).get('name'))

    for name in extra_names:
        add(name)

    hint = ', '.join(names)
    return hint[:MAX_HINT_CHARS]


def agency_vocabulary(limit=25):
    """Client and active-talent names across the whole agency — for dictation
    that is not attached to any one engagement."""
    names = []
    for client in db_session.query(Client).order_by(Client.id).limit(limit).all():
        if client.name:
            names.append(client.name)
    for talent in db_session.query(Talent).filter_by(is_active=True).order_by(Talent.id).limit(limit).all():
        if talent.name:
            names.append(talent.name)
    return ', '.join(names)[:MAX_HINT_CHARS]
