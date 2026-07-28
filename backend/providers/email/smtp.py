"""Generic SMTP email driver — the escape hatch for any provider or a self-hosted
relay. Uses the stdlib, so it adds no dependency.

Credentials come from options (stored in the RuntimeSetting row) rather than
env, because SMTP is the driver most likely to be pointed at something
ad hoc. Note the consequence: those options are readable by anyone who can read
the settings API, so prefer an API-key driver for production.
"""
import smtplib
import time
from email.message import EmailMessage

from config import Config
from providers.base import DriverInfo, EmailDriver
from providers.registry import register


@register
class SmtpEmail(EmailDriver):
    info = DriverInfo(
        key='smtp', capability='email', label='SMTP (any host)',
        blurb='Send through any SMTP server, including a self-hosted relay. Configure host and port below.',
        is_local=False,
        cost_hint='Depends on your SMTP provider',
        options_schema={
            'host': {'type': 'string', 'default': 'localhost', 'label': 'SMTP host'},
            'port': {'type': 'number', 'default': 587, 'label': 'Port'},
            'username': {'type': 'string', 'default': '', 'label': 'Username'},
            'password': {'type': 'string', 'default': '', 'label': 'Password', 'secret': True},
            'use_tls': {'type': 'boolean', 'default': True, 'label': 'Use STARTTLS'},
        },
    )

    def _connect(self, timeout=20):
        server = smtplib.SMTP(self.options.get('host') or 'localhost',
                              int(self.options.get('port') or 587), timeout=timeout)
        if self.options.get('use_tls'):
            server.starttls()
        if self.options.get('username'):
            server.login(self.options['username'], self.options.get('password') or '')
        return server

    def send(self, to, subject, body_html, body_text=None, attachments=None):
        msg = EmailMessage()
        msg['From'] = Config.EMAIL_FROM
        msg['To'] = to
        msg['Subject'] = subject
        msg.set_content(body_text or 'This message requires an HTML-capable client.')
        msg.add_alternative(body_html, subtype='html')
        for a in (attachments or []):
            maintype, _, subtype = (a.get('mime_type') or 'application/pdf').partition('/')
            msg.add_attachment(a['content'], maintype=maintype, subtype=subtype or 'octet-stream',
                               filename=a.get('filename', 'attachment.pdf'))
        try:
            with self._connect() as server:
                server.send_message(msg)
        except Exception as e:
            return {"ok": False, "detail": f"SMTP send failed: {str(e)[:200]}", "provider_id": None}
        return {"ok": True, "detail": f"Handed to {self.options.get('host')}.", "provider_id": None}

    def health(self):
        started = time.monotonic()
        try:
            with self._connect(timeout=5) as server:
                server.noop()
            return {"ok": True, "detail": f"Connected to {self.options.get('host')}.",
                    "latency_ms": int((time.monotonic() - started) * 1000)}
        except Exception as e:
            return {"ok": False, "detail": str(e)[:120],
                    "latency_ms": int((time.monotonic() - started) * 1000)}
