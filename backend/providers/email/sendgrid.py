"""SendGrid email driver — direct REST call, no vendor SDK dependency."""
import base64
import time

import requests

from config import Config
from providers.base import DriverInfo, EmailDriver
from providers.registry import register

API_URL = 'https://api.sendgrid.com/v3/mail/send'


@register
class SendGridEmail(EmailDriver):
    info = DriverInfo(
        key='sendgrid', capability='email', label='SendGrid',
        blurb='Cloud delivery via SendGrid. Needs SENDGRID_API_KEY and a verified sender.',
        is_local=False, requires_env=('SENDGRID_API_KEY',),
        cost_hint='Free tier ~100 emails/day',
    )

    def send(self, to, subject, body_html, body_text=None, attachments=None):
        content = [{"type": "text/plain", "value": body_text or ''}] if body_text else []
        content.append({"type": "text/html", "value": body_html})
        payload = {
            "personalizations": [{"to": [{"email": to}]}],
            "from": {"email": Config.EMAIL_FROM},
            "subject": subject,
            "content": content,
        }
        if attachments:
            payload["attachments"] = [{
                "content": base64.b64encode(a['content']).decode(),
                "filename": a.get('filename', 'attachment.pdf'),
                "type": a.get('mime_type', 'application/pdf'),
                "disposition": "attachment",
            } for a in attachments]

        resp = requests.post(
            API_URL,
            headers={"Authorization": f"Bearer {Config.SENDGRID_API_KEY}", "Content-Type": "application/json"},
            json=payload, timeout=30,
        )
        if resp.status_code >= 400:
            return {"ok": False, "detail": f"SendGrid returned {resp.status_code}: {resp.text[:200]}",
                    "provider_id": None}
        return {"ok": True, "detail": "Accepted by SendGrid.",
                "provider_id": resp.headers.get('X-Message-Id')}

    def health(self):
        if not self.available():
            return {"ok": False, "detail": "SENDGRID_API_KEY not set", "latency_ms": None}
        started = time.monotonic()
        try:
            resp = requests.get('https://api.sendgrid.com/v3/scopes',
                                headers={"Authorization": f"Bearer {Config.SENDGRID_API_KEY}"}, timeout=5)
            latency = int((time.monotonic() - started) * 1000)
            ok = resp.status_code < 400
            return {"ok": ok, "detail": "Key accepted." if ok else f"HTTP {resp.status_code}",
                    "latency_ms": latency}
        except Exception as e:
            return {"ok": False, "detail": str(e)[:120],
                    "latency_ms": int((time.monotonic() - started) * 1000)}
