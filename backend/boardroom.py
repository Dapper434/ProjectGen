"""Boardroom: live transcription + the Coverage Agent — WP-7.

The checklist is the product, not the transcript. A producer glancing at the
agenda mid-meeting should be able to steer the conversation before the client
hangs up — which is worth far more than a tidy record afterwards.

Two rules the parser enforces rather than trusts:

* **Evidence is mandatory for `covered`.** No transcript span → downgraded to
  `partial`. It is the only defence against a model agreeing with itself, and it
  makes the UI clickable.
* **A coverage check never crashes a live meeting.** Malformed model output gets
  one repair retry, then becomes `unknown` — never a false `covered`, never a 500.
"""
import datetime
import json
import re

from database import db_session
from models import AgentEvent, BoardroomSession, CoverageCheck, TranscriptSegment

DEFAULT_PROTOCOL = {
    "name": "GDF Client Intake Boardroom Protocol",
    "meeting_kind": "intake",
    "items": [
        {"key": "budget_range", "label": "Confirmed budget range", "required": True,
         "why": "Proposal pricing cannot be scoped without it; the Rate Card needs a band to fit.",
         "accept_when": "A figure or range with a currency, or an explicit statement that budget is not yet set.",
         "ask": "What budget range are we working within for this?"},
        {"key": "decision_maker", "label": "Decision-maker & sign-off path", "required": True,
         "why": "Proposals sent to the wrong person stall for weeks.",
         "accept_when": "A named person or role who signs off, and how approval reaches them.",
         "ask": "Who signs off on this, and what does that approval path look like?"},
        {"key": "deliverables", "label": "Deliverable list & formats", "required": True,
         "why": "Scope disputes start here.",
         "accept_when": "Each deliverable named with a format or spec.",
         "ask": "What exactly are we delivering, and in what formats?"},
        {"key": "timeline", "label": "Key dates and hard deadlines", "required": True,
         "why": "Drives casting availability and production scheduling.",
         "accept_when": "At least one dated milestone or a hard deadline.",
         "ask": "What are the hard dates we're working back from?"},
        {"key": "usage_rights", "label": "Usage rights, territory & duration", "required": True,
         "why": "The single most common source of post-delivery disputes.",
         "accept_when": "Media, territory and licence duration are all stated.",
         "ask": "Where will this run, in which markets, and for how long?"},
        {"key": "talent_needs", "label": "Talent / casting requirements", "required": False,
         "why": "Feeds the Casting Agent directly.",
         "accept_when": "Roles, count, or a described profile.",
         "ask": "Who do we need on camera or on the crew?"},
        {"key": "brand_assets", "label": "Brand guidelines & asset availability", "required": False,
         "why": "Avoids a week lost waiting for logos and fonts.",
         "accept_when": "Confirmation that guidelines and assets exist and who supplies them.",
         "ask": "Do you have brand guidelines and assets ready, and who sends them over?"},
        {"key": "success_metric", "label": "How the client will judge success", "required": False,
         "why": "Sharpens the proposal's framing.",
         "accept_when": "A stated outcome or measure.",
         "ask": "How will you know this worked?"},
    ],
    "interim_check_seconds": 90,
    "interim_check_min_new_words": 1200,
    "closing_script": ("Before we close — a few things we haven't covered yet: {missing}. "
                       "Can we take those now, or should I follow up by email today?"),
}

DEFAULT_COVERAGE_PROMPT = """You are a meeting Coverage Agent for a creative agency. You are given a live meeting transcript and a list of agenda items that must be covered before the meeting ends. Decide, for each item, whether the transcript actually covers it.

<rules>
1. Judge ONLY on what the transcript says. Never assume something was covered because it usually is.
2. "covered" REQUIRES a verbatim quote from the transcript that satisfies the item's accept_when. If you cannot quote it, the status is NOT "covered".
3. "partial" means the topic was raised but the accept_when condition is not fully met.
4. "missing" means the topic has not been meaningfully raised.
5. Never invent, infer, or paraphrase evidence. The "evidence" field must be an exact substring of the transcript.
</rules>

<output_format>
Respond ONLY with a JSON array. One object per agenda item, with exactly these keys:
- "key": the item's key, copied exactly.
- "status": one of "covered", "partial", "missing".
- "evidence": an exact quote from the transcript that satisfies the item, or null when the status is not "covered".
- "confidence": a number between 0 and 1.
No prose, no markdown fence, no commentary.
</output_format>"""

VALID_STATUSES = ('covered', 'partial', 'missing', 'unknown')


def resolve_protocol(session=None, engagement=None, meeting_kind='intake'):
    """The protocol document for a session, and its provenance.

    When a session already exists its FROZEN version is used, so editing the
    agenda mid-meeting cannot move the goalposts under a live session.
    """
    from authoritative import resolve as auth_resolve

    if session and session.protocol_version:
        body, prov = auth_resolve('boardroom_protocol', engagement=engagement,
                                  version=session.protocol_version)
        if body:
            return body, prov

    body, prov = auth_resolve('boardroom_protocol', engagement=engagement)
    if body is None:
        return DEFAULT_PROTOCOL, {"key": "boardroom_protocol", "scope": "legacy_constant", "version": 0}
    return body, prov


def assemble(session_id, since_seq=None):
    q = db_session.query(TranscriptSegment).filter_by(session_id=session_id)
    if since_seq is not None:
        q = q.filter(TranscriptSegment.seq > since_seq)
    segments = q.order_by(TranscriptSegment.seq).all()
    return '\n'.join(f"[{s.seq}] {s.speaker_label + ': ' if s.speaker_label else ''}{s.text}"
                     for s in segments)


def next_seq(session_id):
    from sqlalchemy import func
    current = db_session.query(func.max(TranscriptSegment.seq)).filter_by(session_id=session_id).scalar()
    return (current or 0) + 1


def latest_checks(session_id):
    """The most recent check per item — finals always win over interims."""
    rows = (db_session.query(CoverageCheck)
            .filter_by(session_id=session_id)
            .order_by(CoverageCheck.is_final, CoverageCheck.id).all())
    latest = {}
    for row in rows:
        latest[row.item_key] = row
    return latest


def _extract_json_array(raw):
    text = (raw or '').strip()
    if text.startswith('```'):
        text = re.sub(r'^```(?:json)?', '', text).rsplit('```', 1)[0]
    start, end = text.find('['), text.rfind(']')
    if start == -1 or end == -1:
        raise ValueError("no JSON array in the response")
    return json.loads(text[start:end + 1])


def parse_coverage(raw, items, transcript=''):
    """Strict parse of the model's coverage verdict.

    Downgrades `covered` to `partial` when the evidence is missing or is not
    actually present in the transcript — a model that fabricates a quote does not
    get to mark an item done.
    """
    parsed = _extract_json_array(raw)
    if not isinstance(parsed, list):
        raise ValueError("expected a JSON array")

    by_key = {item['key']: item for item in items}
    haystack = ' '.join(transcript.split()).lower()
    out = []

    for entry in parsed:
        if not isinstance(entry, dict):
            continue
        key = entry.get('key')
        if key not in by_key:
            continue
        status = entry.get('status')
        if status not in VALID_STATUSES:
            status = 'unknown'
        evidence = (entry.get('evidence') or '').strip() or None

        if status == 'covered':
            if not evidence:
                status = 'partial'
            elif ' '.join(evidence.split()).lower() not in haystack:
                # Quote is not in the transcript — treat as unverified, not covered.
                status = 'partial'

        confidence = entry.get('confidence')
        try:
            confidence = float(confidence) if confidence is not None else None
        except (TypeError, ValueError):
            confidence = None

        out.append({
            "key": key, "status": status, "evidence": evidence,
            "confidence": confidence,
            "suggested_prompt": by_key[key].get('ask'),
        })

    seen = {c['key'] for c in out}
    for key, item in by_key.items():
        if key not in seen:
            out.append({"key": key, "status": "unknown", "evidence": None,
                        "confidence": None, "suggested_prompt": item.get('ask')})
    return out


def _evidence_seq(evidence, session_id):
    """Which segment the quote came from, so the UI can jump to that moment."""
    if not evidence:
        return None
    needle = ' '.join(evidence.split()).lower()[:80]
    for segment in (db_session.query(TranscriptSegment)
                    .filter_by(session_id=session_id).order_by(TranscriptSegment.seq).all()):
        if needle and needle in ' '.join(segment.text.split()).lower():
            return segment.seq
    return None


def persist_checks(session_id, checks, is_final, driver_key):
    for check in checks:
        db_session.add(CoverageCheck(
            session_id=session_id, item_key=check['key'], status=check['status'],
            evidence=check['evidence'], evidence_seq=_evidence_seq(check['evidence'], session_id),
            confidence=check['confidence'], suggested_prompt=check['suggested_prompt'],
            is_final=is_final, driver_key=driver_key,
            checked_at=datetime.datetime.utcnow(),
        ))
    db_session.commit()


def debounce_ok(session, protocol):
    """Server-side rate limiting. Never trust a browser tab to limit model spend."""
    every = protocol.get('interim_check_seconds', 90)
    last = (db_session.query(CoverageCheck)
            .filter_by(session_id=session.id, is_final=False)
            .order_by(CoverageCheck.id.desc()).first())
    if not last or not last.checked_at:
        return True
    return (datetime.datetime.utcnow() - last.checked_at).total_seconds() >= every


def analyze_coverage(session_id, final=False):
    """Interim checks are cheap and incremental; the final check is expensive and
    complete. Interim output is a live hint; final output is the record."""
    from authoritative import build_refs, resolve as auth_resolve
    from locks import AlreadyProcessing, agent_lock
    from providers import registry

    try:
        # Scoped to the session, not the engagement, so two rooms can run at once.
        with agent_lock('boardroom_coverage', 'boardroom_session', session_id, ttl_minutes=10):
            session = db_session.query(BoardroomSession).get(session_id)
            if not session:
                return
            engagement = session.engagement if session.engagement_id else None
            protocol, prov = resolve_protocol(session, engagement)
            prompt, prompt_prov = auth_resolve('coverage_prompt')
            if prompt is None:
                prompt = DEFAULT_COVERAGE_PROMPT

            if final:
                transcript = assemble(session_id)
                items = protocol['items']
                driver = registry.get('agent_llm')
            else:
                if not debounce_ok(session, protocol):
                    return
                transcript = assemble(session_id)
                settled = {k for k, c in latest_checks(session_id).items() if c.status == 'covered'}
                # `covered` is sticky within a session: an item satisfied at
                # minute 5 does not become uncovered at minute 40. The final pass
                # re-derives everything anyway, so this is pure cost saving.
                items = [i for i in protocol['items'] if i['key'] not in settled]
                driver = registry.get('coverage_llm')

            if not items or not transcript.strip():
                return

            user_prompt = (f"<agenda_items>\n{json.dumps(items, indent=2)}\n</agenda_items>\n\n"
                           f"<transcript>\n{transcript}\n</transcript>")

            try:
                raw, usage = driver.complete(prompt, user_prompt, reasoning='off')
                checks = parse_coverage(raw, items, transcript)
            except Exception as first_error:
                try:
                    repair = (user_prompt + "\n\nYour previous response could not be parsed as a JSON "
                              f"array ({str(first_error)[:200]}). Respond with ONLY the JSON array.")
                    raw, usage = driver.complete(prompt, repair, reasoning='off')
                    checks = parse_coverage(raw, items, transcript)
                except Exception as second_error:
                    # Never a 500, never a false 'covered' — mark unknown and log it.
                    checks = [{"key": i['key'], "status": "unknown", "evidence": None,
                               "confidence": None, "suggested_prompt": i.get('ask')} for i in items]
                    usage = {}
                    db_session.add(AgentEvent(
                        engagement_id=session.engagement_id, agent='Coverage Agent',
                        trigger='boardroom_coverage_parse_failed',
                        reasoning_summary=f"Could not parse the model's coverage response: {str(second_error)[:300]}",
                        action='Marked all items unknown', tokens_used=0,
                    ))

            persist_checks(session_id, checks, is_final=final, driver_key=driver.info.key)

            missing = sum(1 for c in checks if c['status'] == 'missing')
            db_session.add(AgentEvent(
                engagement_id=session.engagement_id, agent='Coverage Agent',
                trigger='boardroom_coverage_final' if final else 'boardroom_coverage_interim',
                reasoning_summary='; '.join(f"{c['key']}={c['status']}" for c in checks),
                action=f"{missing} item(s) still uncovered",
                tokens_used=(usage or {}).get('total_tokens', 0),
                authoritative_refs=build_refs(prov, prompt_prov),
            ))
            db_session.commit()
    except AlreadyProcessing:
        return  # a check is already running for this room; the next poll picks it up
    finally:
        db_session.remove()


def session_json(session, since_seq=None, include_protocol=True):
    q = db_session.query(TranscriptSegment).filter_by(session_id=session.id)
    if since_seq is not None:
        q = q.filter(TranscriptSegment.seq > since_seq)
    segments = q.order_by(TranscriptSegment.seq).all()

    checks = latest_checks(session.id)
    engagement = session.engagement if session.engagement_id else None
    protocol, prov = resolve_protocol(session, engagement) if include_protocol else (None, None)

    out = {
        "id": session.id,
        "engagement_id": session.engagement_id,
        "client_id": session.client_id,
        "title": session.title,
        "meeting_kind": session.meeting_kind,
        "status": session.status,
        "language": session.language,
        "planned_minutes": session.planned_minutes,
        "started_at": session.started_at.isoformat() if session.started_at else None,
        "ended_at": session.ended_at.isoformat() if session.ended_at else None,
        "protocol_version": session.protocol_version,
        "protocol_scope": session.protocol_scope,
        "raw_transcript": session.raw_transcript,
        "polished_transcript": session.polished_transcript,
        "promoted_transcript_id": session.promoted_transcript_id,
        "consent_ack_at": session.consent_ack_at.isoformat() if session.consent_ack_at else None,
        "segments": [{
            "seq": s.seq, "text": s.text, "speaker_label": s.speaker_label,
            "source": s.source, "provider": s.provider,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        } for s in segments],
        "coverage": [{
            "key": key, "status": c.status, "evidence": c.evidence,
            "evidence_seq": c.evidence_seq, "confidence": c.confidence,
            "suggested_prompt": c.suggested_prompt, "is_final": c.is_final,
            "driver_key": c.driver_key,
            "checked_at": c.checked_at.isoformat() if c.checked_at else None,
        } for key, c in checks.items()],
    }
    if include_protocol:
        out["protocol"] = protocol
        out["protocol_provenance"] = prov
    return out
