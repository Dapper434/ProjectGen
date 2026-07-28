"""Wispr Flow drivers — implemented for Lab evaluation, deliberately not a default.

Wispr Flow cleans filler, fixes names from supplied context and auto-formats,
which puts it closer to "a producer's assistant typing what they said" than raw
transcription. It is also paid, cloud-only and usage-billed with no built-in
rate cap — so it ships as an option to evaluate against Groq and local, not as
something the system drifts onto by accident (WP-4 §4.9).

Auth is **API-key mode, server-brokered**. Client meeting audio carries names,
budgets and internal decisions; this codebase's rule is that secrets stay
server-side, and a client-held token would break it.

The REST endpoint shape below is written against the vendor docs as of July 2026
and has NOT been verified against a live account — there is no key in this
environment. Treat the response parsing as provisional and check it against a
real response before relying on this driver.
"""
import time

import requests

from config import Config
from providers.base import DriverInfo
from providers.registry import register
from providers.stt.base import STTDriver, STTRateLimited, STTUnavailable, Segment

API_BASE = 'https://api.wisprflow.ai/v1'


class _WisprBase(STTDriver):
    supports_timestamps = False

    def transcribe(self, audio, mime, hints="", language="en"):
        data = {"language": language}
        if hints:
            data["context"] = hints[:900]
        try:
            resp = requests.post(
                f"{API_BASE}/transcribe",
                headers={"Authorization": f"Bearer {Config.WISPRFLOW_API_KEY}"},
                files={"file": ("piece.mp3", audio, mime or "audio/mpeg")},
                data=data, timeout=self._timeout(),
            )
        except requests.RequestException as e:
            raise STTUnavailable(f"Wispr Flow unreachable: {e.__class__.__name__}") from e

        if resp.status_code == 429:
            raise STTRateLimited(retry_after=float(resp.headers.get('retry-after', 5) or 5),
                                 detail="Wispr Flow rate limit reached")
        if resp.status_code >= 500:
            raise STTUnavailable(f"Wispr Flow returned HTTP {resp.status_code}")
        resp.raise_for_status()

        payload = resp.json()
        text = (payload.get('text') or payload.get('transcript') or '').strip()
        return [Segment(text=text, provider=self.info.key, raw=payload)] if text else []

    def _timeout(self):
        return 180

    def health(self):
        if not self.available():
            return {"ok": False, "detail": "WISPRFLOW_API_KEY not set", "latency_ms": None}
        started = time.monotonic()
        try:
            resp = requests.get(f"{API_BASE}/health",
                                headers={"Authorization": f"Bearer {Config.WISPRFLOW_API_KEY}"}, timeout=5)
            latency = int((time.monotonic() - started) * 1000)
            ok = resp.status_code < 400
            return {"ok": ok,
                    "detail": "Key accepted." if ok else f"HTTP {resp.status_code} — endpoint shape unverified",
                    "latency_ms": latency}
        except Exception as e:
            return {"ok": False, "detail": str(e)[:120],
                    "latency_ms": int((time.monotonic() - started) * 1000)}


@register
class WisprBatchSTT(_WisprBase):
    info = DriverInfo(
        key='wispr_batch', capability='stt_batch', label='Wispr Flow (cloud, cleaned)',
        blurb='Returns already-cleaned, formatted text rather than raw transcription. Paid and usage-billed — evaluate in the Lab before adopting.',
        is_local=False, requires_env=('WISPRFLOW_API_KEY',),
        cost_hint='Paid per use, no built-in cap — set a budget before enabling',
    )


@register
class WisprStreamSTT(_WisprBase):
    supports_live = True
    max_bytes = 8 * 1024 * 1024
    info = DriverInfo(
        key='wispr_stream', capability='stt_live', label='Wispr Flow (live)',
        blurb='Live capture via Wispr Flow. Uses the REST path here; the vendor also offers a WebSocket that this driver does not yet implement.',
        is_local=False, requires_env=('WISPRFLOW_API_KEY',),
        cost_hint='Paid per use, no built-in cap — set a budget before enabling',
    )

    def _timeout(self):
        return 60
