"""Outbound email — WP-12.

A capability, not a hardcoded vendor: the driver comes from the provider
registry, so switching SendGrid → Postmark → SMTP is a settings change, and
`console` makes every flow here testable with no vendor account at all.
"""
import html as html_mod

from providers import registry

DEFAULT_COVER_NOTE = """Hi {contact},

Please find attached our proposal for {client}.

{summary}

Happy to walk through any of it — just reply to this email and we'll set up a time.

Best,
{sender}
{agency}"""


def render_email(template, **fields):
    text = template
    for key, value in fields.items():
        text = text.replace('{' + key + '}', str(value or ''))
    return text


def to_html(text):
    """Plain text → simple HTML. Escaped first: a client name with an ampersand
    must not be able to inject markup into an outbound email."""
    paragraphs = [p.strip() for p in (text or '').split('\n\n') if p.strip()]
    body = '\n'.join(
        f'<p style="margin:0 0 14px;line-height:1.55;">'
        f'{html_mod.escape(p).replace(chr(10), "<br>")}</p>'
        for p in paragraphs
    )
    return (
        '<div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;'
        'font-size:15px;color:#1a1a1a;max-width:620px;">' + body + '</div>'
    )


def send(to, subject, body_text, attachments=None, driver_override=None):
    """Returns the driver's own {'ok', 'detail', 'provider_id'} plus which driver ran."""
    driver = registry.get('email', override=driver_override)
    try:
        result = driver.send(to, subject, to_html(body_text), body_text=body_text,
                             attachments=attachments)
    except Exception as e:
        result = {"ok": False, "detail": f"{driver.info.label} failed: {str(e)[:200]}",
                  "provider_id": None}
    result['driver'] = driver.info.key
    result['driver_label'] = driver.info.label
    return result


def proposal_email(engagement, proposal, contact_name, sender_name, cover_note=None):
    from config import Config

    client_name = engagement.client.name if engagement.client else 'your team'
    structured = proposal.structured_json or {}
    approach = (structured.get('approach') or '').strip()
    total = sum((li.get('qty', 1) or 1) * (li.get('rate_kes', 0) or 0)
                for li in (proposal.pricing_line_items or []))

    summary_lines = []
    if approach:
        summary_lines.append(approach)
    if total:
        summary_lines.append(f"Total investment: KES {total:,}.")

    template = cover_note or DEFAULT_COVER_NOTE
    body = render_email(
        template,
        contact=contact_name or 'there',
        client=client_name,
        summary='\n\n'.join(summary_lines),
        sender=sender_name or 'The team',
        agency='GDF',
    )
    subject = f"Proposal — {client_name}"
    return subject, body
