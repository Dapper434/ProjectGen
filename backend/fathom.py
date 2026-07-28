"""Fathom integration: webhook signature verification, payload parsing, and a small
CLI to register the webhook against api.fathom.ai.

Flow: Zoom meeting ends -> Fathom finishes the recording -> Fathom POSTs the
"new meeting content ready" payload (with transcript + summary) to
/api/webhooks/fathom (see app.py), which drops it into the Transcript Inbox and,
when the meeting title matches exactly one client, attaches + processes it
immediately.

Env vars (backend/.env):
    FATHOM_API_KEY         — from Fathom Settings -> API Access; only needed to
                             register/delete webhooks via this CLI.
    FATHOM_WEBHOOK_SECRET  — the `secret` returned when the webhook is created
                             (starts with "whsec_"). When set, incoming webhook
                             requests are HMAC-verified; when unset, the endpoint
                             accepts unsigned requests (dev/demo only).

Register the webhook (prints the secret to put in .env):
    python3 fathom.py register https://your-public-host/api/webhooks/fathom
"""
import base64
import hashlib
import hmac
import sys
import time
from datetime import datetime

FATHOM_API_BASE = 'https://api.fathom.ai/external/v1'


# ---------------------------------------------------------------------------
# Signature verification (Fathom uses the Svix webhook signature scheme)
# ---------------------------------------------------------------------------

def verify_signature(headers, body_bytes, secret=None, tolerance_seconds=300):
    """True if the request is authentically from Fathom (or if no secret is
    configured — dev mode). Scheme: HMAC-SHA256 over "{id}.{timestamp}.{body}"
    keyed with the base64-decoded part of the secret after "whsec_", compared
    against each "v1,<base64sig>" entry in the webhook-signature header."""
    if secret is None:
        from config import Config  # deferred: must resolve after load_dotenv(), not at module import
        secret = Config.FATHOM_WEBHOOK_SECRET
    if not secret:
        return True

    msg_id = headers.get('webhook-id')
    timestamp = headers.get('webhook-timestamp')
    signatures = headers.get('webhook-signature')
    if not (msg_id and timestamp and signatures):
        return False

    try:
        if abs(time.time() - int(timestamp)) > tolerance_seconds:  # replay protection
            return False
        key = base64.b64decode(secret.split('whsec_')[-1])
    except (ValueError, TypeError):
        return False

    signed_content = f"{msg_id}.{timestamp}".encode() + b'.' + body_bytes
    expected = base64.b64encode(hmac.new(key, signed_content, hashlib.sha256).digest()).decode()

    for candidate in signatures.split():
        # entries look like "v1,<base64>"; ignore the version prefix
        candidate_sig = candidate.split(',', 1)[-1]
        if hmac.compare_digest(expected, candidate_sig):
            return True
    return False


# ---------------------------------------------------------------------------
# Payload parsing
# ---------------------------------------------------------------------------

def _parse_iso(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None


def parse_meeting_payload(data):
    """Normalize Fathom's "new meeting content ready" payload into the fields
    InboundTranscript stores. Defensive .get() everywhere — Fathom marks most
    fields nullable, and include_* webhook options change what's present."""
    transcript_entries = data.get('transcript') or []
    lines = []
    for entry in transcript_entries:
        speaker = (entry.get('speaker') or {}).get('display_name') or 'Unknown speaker'
        text = (entry.get('text') or '').strip()
        if text:
            lines.append(f"{speaker}: {text}")
    raw_text = '\n'.join(lines)

    started = _parse_iso(data.get('recording_start_time'))
    ended = _parse_iso(data.get('recording_end_time'))
    duration_minutes = None
    if started and ended and ended > started:
        duration_minutes = round((ended - started).total_seconds() / 60)

    attendees = []
    for invitee in (data.get('calendar_invitees') or []):
        label = invitee.get('name') or invitee.get('email')
        if label:
            attendees.append(label)

    recorded_by = (data.get('recorded_by') or {})
    recorded_by_label = recorded_by.get('name') or recorded_by.get('email')

    summary = ((data.get('default_summary') or {}).get('markdown_formatted') or '').strip() or None

    external_id = data.get('recording_id') or data.get('id')

    return {
        'external_id': str(external_id) if external_id is not None else None,
        'title': data.get('meeting_title') or data.get('title'),
        'share_url': data.get('share_url') or data.get('url'),
        'recorded_by': recorded_by_label,
        'meeting_date': started.strftime('%Y-%m-%d') if started else None,
        'duration_minutes': duration_minutes,
        'attendees': attendees,
        'is_external_meeting': data.get('calendar_invitees_domains_type') != 'only_internal',
        'raw_text': raw_text,
        'summary': summary,
    }


# ---------------------------------------------------------------------------
# Webhook registration CLI
# ---------------------------------------------------------------------------

def _api_key():
    from config import Config  # deferred: must resolve after load_dotenv(), not at module import
    key = Config.FATHOM_API_KEY
    if not key:
        raise SystemExit("FATHOM_API_KEY is not set — add it to backend/.env (Fathom Settings -> API Access).")
    return key


def register_webhook(destination_url):
    import requests
    resp = requests.post(
        f"{FATHOM_API_BASE}/webhooks",
        headers={'X-Api-Key': _api_key(), 'Content-Type': 'application/json'},
        json={
            'destination_url': destination_url,
            # Fire for the recorder's own meetings and ones teammates share to the team,
            # so any producer's client call reaches the inbox.
            'triggered_for': ['my_recordings', 'shared_team_recordings'],
            'include_transcript': True,
            'include_summary': True,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def main():
    from dotenv import load_dotenv
    load_dotenv()

    if len(sys.argv) >= 3 and sys.argv[1] == 'register':
        result = register_webhook(sys.argv[2])
        print("Webhook created:")
        print(f"  id:     {result.get('id')}")
        print(f"  url:    {result.get('url')}")
        print(f"  secret: {result.get('secret')}")
        print("\nAdd this line to backend/.env so incoming webhooks are verified:")
        print(f"  FATHOM_WEBHOOK_SECRET={result.get('secret')}")
    else:
        print(__doc__)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
