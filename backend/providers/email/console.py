"""Console email driver — prints instead of sending.

This is what makes WP-11's invite flow and WP-12's proposal delivery fully
testable locally with no vendor account, and it is the fallback for the whole
`email` capability: if a real provider is misconfigured, mail lands in the log
rather than silently vanishing or 500ing a request.
"""
from config import Config
from providers.base import DriverInfo, EmailDriver
from providers.registry import register


@register
class ConsoleEmail(EmailDriver):
    info = DriverInfo(
        key='console', capability='email', label='Console (no delivery)',
        blurb='Prints the email to the server log instead of sending it. Use locally and in demos.',
        is_local=True, cost_hint='Free — nothing is sent',
    )

    def send(self, to, subject, body_html, body_text=None, attachments=None):
        names = [a.get('filename', 'attachment') for a in (attachments or [])]
        print(
            "\n=== EMAIL (console driver — not actually sent) ===\n"
            f"From:    {Config.EMAIL_FROM}\n"
            f"To:      {to}\n"
            f"Subject: {subject}\n"
            f"Attachments: {', '.join(names) if names else 'none'}\n"
            f"---\n{body_text or body_html}\n"
            "=== END EMAIL ===\n",
            # flush: stdout is block-buffered when it is not a TTY (gunicorn, a
            # redirected dev server), and an email that only appears minutes
            # later defeats the entire point of this driver.
            flush=True,
        )
        return {"ok": True, "detail": "Printed to the server log (nothing was sent).", "provider_id": None}

    def health(self):
        return {"ok": True, "detail": "Always available — prints to the log.", "latency_ms": 0}
