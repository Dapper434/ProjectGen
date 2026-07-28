"""Postmark email driver — direct REST call, no vendor SDK dependency."""
import base64
import time

import requests

from config import Config
from providers.base import DriverInfo, EmailDriver
from providers.registry import register

API_URL = 'https://api.postmarkapp.com/email'


@register
class PostmarkEmail(EmailDriver):
    info = DriverInfo(
        key='postmark', capability='email', label='Postmark',
        blurb='Cloud delivery via Postmark. Strong deliverability for transactional mail.',
        is_local=False, requires_env=('POSTMARK_TOKEN',),
        cost_hint='Paid; free developer tier ~100 emails/month',
    )

    def send(self, to, subject, body_html, body_text=None, attachments=None):
        payload = {
            "From": Config.EMAIL_FROM,
            "To": to,
            "Subject": subject,
            "HtmlBody": body_html,
            "MessageStream": self.options.get('message_stream', 'outbound'),
        }
        if body_text:
            payload["TextBody"] = body_text
        if attachments:
            payload["Attachments"] = [{
                "Name": a.get('filename', 'attachment.pdf'),
                "Content": base64.b64encode(a['content']).decode(),
                "ContentType": a.get('mime_type', 'application/pdf'),
            } for a in attachments]

        resp = requests.post(
            API_URL,
            headers={"X-Postmark-Server-Token": Config.POSTMARK_TOKEN,
                     "Content-Type": "application/json", "Accept": "application/json"},
            json=payload, timeout=30,
        )
        data = resp.json() if resp.content else {}
        if resp.status_code >= 400:
            return {"ok": False, "detail": f"Postmark: {data.get('Message', resp.text[:200])}",
                    "provider_id": None}
        return {"ok": True, "detail": "Accepted by Postmark.", "provider_id": data.get('MessageID')}

    def health(self):
        if not self.available():
            return {"ok": False, "detail": "POSTMARK_SERVER_TOKEN not set", "latency_ms": None}
        started = time.monotonic()
        try:
            resp = requests.get('https://api.postmarkapp.com/server',
                                headers={"X-Postmark-Server-Token": Config.POSTMARK_TOKEN,
                                         "Accept": "application/json"}, timeout=5)
            latency = int((time.monotonic() - started) * 1000)
            ok = resp.status_code < 400
            return {"ok": ok, "detail": "Token accepted." if ok else f"HTTP {resp.status_code}",
                    "latency_ms": latency}
        except Exception as e:
            return {"ok": False, "detail": str(e)[:120],
                    "latency_ms": int((time.monotonic() - started) * 1000)}
