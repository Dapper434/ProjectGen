"""Resend email driver — direct REST call, no vendor SDK dependency."""
import base64
import time

import requests

from config import Config
from providers.base import DriverInfo, EmailDriver
from providers.registry import register

API_URL = 'https://api.resend.com/emails'


@register
class ResendEmail(EmailDriver):
    info = DriverInfo(
        key='resend', capability='email', label='Resend',
        blurb='Cloud delivery via Resend. Simple API, generous free tier.',
        is_local=False, requires_env=('RESEND_API_KEY',),
        cost_hint='Free tier ~3k emails/month',
    )

    def send(self, to, subject, body_html, body_text=None, attachments=None):
        payload = {"from": Config.EMAIL_FROM, "to": [to], "subject": subject, "html": body_html}
        if body_text:
            payload["text"] = body_text
        if attachments:
            payload["attachments"] = [{
                "filename": a.get('filename', 'attachment.pdf'),
                "content": base64.b64encode(a['content']).decode(),
            } for a in attachments]

        resp = requests.post(
            API_URL,
            headers={"Authorization": f"Bearer {Config.RESEND_API_KEY}", "Content-Type": "application/json"},
            json=payload, timeout=30,
        )
        data = resp.json() if resp.content else {}
        if resp.status_code >= 400:
            return {"ok": False,
                    "detail": f"Resend: {(data.get('error') or {}).get('message') or resp.text[:200]}",
                    "provider_id": None}
        return {"ok": True, "detail": "Accepted by Resend.", "provider_id": data.get('id')}

    def health(self):
        if not self.available():
            return {"ok": False, "detail": "RESEND_API_KEY not set", "latency_ms": None}
        started = time.monotonic()
        try:
            resp = requests.get('https://api.resend.com/domains',
                                headers={"Authorization": f"Bearer {Config.RESEND_API_KEY}"}, timeout=5)
            latency = int((time.monotonic() - started) * 1000)
            ok = resp.status_code < 400
            return {"ok": ok, "detail": "Key accepted." if ok else f"HTTP {resp.status_code}",
                    "latency_ms": latency}
        except Exception as e:
            return {"ok": False, "detail": str(e)[:120],
                    "latency_ms": int((time.monotonic() - started) * 1000)}
