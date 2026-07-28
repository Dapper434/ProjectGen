"""Groq and local-Whisper drivers.

Both speak the same OpenAI-compatible `POST /audio/transcriptions` shape, so the
local driver really is the cloud driver with a different base URL and no auth
header — which is the whole reason the "run it on our own hardware" requirement
is cheap to meet here (WP-4 §4.1).

Live and batch variants are registered as separate drivers rather than one
dual-purpose class: the Lab lists them independently, and their defaults
genuinely differ (chunk ceiling, model choice).
"""
import time

import requests

from config import Config
from providers.base import DriverInfo
from providers.registry import register
from providers.stt.base import STTDriver, STTRateLimited, STTUnavailable, Segment, record_rate_headers


def _looks_like_echoed_hints(text, hints):
    """True when Whisper has parroted the spelling-hint prompt back as if it were
    speech.

    This is a real, reproducible Whisper behaviour: given silence or non-speech
    audio and a `prompt`, it frequently returns the prompt itself as the
    transcription. Verified against Groq — a 6-second pure tone with
    hints "Aisha, Twiga Foods, Nairobi" transcribed as exactly that string.

    Left unguarded it would write names nobody said into a client transcript,
    which breaks the invariant that transcription never invents content. A
    silent chunk must produce nothing, not a plausible-looking sentence.
    """
    if not hints or not text:
        return False
    norm = lambda s: ' '.join(''.join(c.lower() if c.isalnum() or c.isspace() else ' ' for c in s).split())
    text_n, hints_n = norm(text), norm(hints[:900])
    if not text_n:
        return False
    if text_n == hints_n or text_n in hints_n:
        return True
    # Also catch a partial echo: short output whose words are entirely drawn
    # from the hint list is far more likely parroting than speech.
    hint_words = set(hints_n.split())
    text_words = text_n.split()
    return len(text_words) <= 12 and bool(hint_words) and all(w in hint_words for w in text_words)


def _is_contentless(text):
    """Whisper emits a bare '.' (or similar punctuation) for silence. Harmless in
    a batch transcript, but a dictation UI appending one per silent chunk looks
    broken — verified live: 6s of tone returned exactly '.'."""
    return not any(ch.isalnum() for ch in text)


def _parse_segments(payload, provider_key, hints=''):
    """verbose_json → Segments. Falls back to the flat `text` field when a server
    ignores the timestamp request, so a minimal Whisper build still works."""
    segments = payload.get('segments') or []
    out = []
    for s in segments:
        text = (s.get('text') or '').strip()
        if not text or _is_contentless(text) or _looks_like_echoed_hints(text, hints):
            continue
        start, end = s.get('start'), s.get('end')
        out.append(Segment(
            text=text,
            start_ms=int(start * 1000) if start is not None else None,
            end_ms=int(end * 1000) if end is not None else None,
            provider=provider_key, raw=s,
        ))
    if not out:
        text = (payload.get('text') or '').strip()
        if text and not _is_contentless(text) and not _looks_like_echoed_hints(text, hints):
            out.append(Segment(text=text, provider=provider_key))
    return out


class _WhisperCompatible(STTDriver):
    supports_timestamps = True

    def _endpoint(self):
        raise NotImplementedError

    def _headers(self):
        return {}

    def _model(self):
        raise NotImplementedError

    def _timeout(self):
        return 180

    def transcribe(self, audio, mime, hints="", language="en"):
        data = {
            "model": self._model(),
            "response_format": "verbose_json",
            "timestamp_granularities[]": "segment",
            "temperature": str(self.options.get('temperature', 0.0)),
        }
        if language:
            data["language"] = language
        if hints:
            # ~224 tokens is the documented ceiling for the prompt field.
            data["prompt"] = hints[:900]

        try:
            resp = requests.post(
                self._endpoint(), headers=self._headers(),
                files={"file": ("piece.mp3", audio, mime or "audio/mpeg")},
                data=data, timeout=self._timeout(),
            )
        except requests.RequestException as e:
            raise STTUnavailable(f"{self.info.label} unreachable: {e.__class__.__name__}") from e

        record_rate_headers(self.info.key, resp.headers)

        if resp.status_code == 429:
            raise STTRateLimited(retry_after=float(resp.headers.get('retry-after', 5) or 5),
                                 detail=f"{self.info.label} rate limit reached")
        if resp.status_code >= 500:
            raise STTUnavailable(f"{self.info.label} returned HTTP {resp.status_code}")
        resp.raise_for_status()
        return _parse_segments(resp.json(), self.info.key, hints=hints)


# --- Groq --------------------------------------------------------------------

_GROQ_BASE = 'https://api.groq.com/openai/v1'
_GROQ_MODELS = ["whisper-large-v3-turbo", "whisper-large-v3"]


class _GroqSTT(_WhisperCompatible):
    def _endpoint(self):
        return f"{_GROQ_BASE}/audio/transcriptions"

    def _headers(self):
        return {"Authorization": f"Bearer {Config.GROQ_API_KEY}"}

    def _model(self):
        return self.options.get('model') or Config.GROQ_STT_MODEL

    def health(self):
        if not self.available():
            return {"ok": False, "detail": "GROQ_API_KEY not set", "latency_ms": None}
        started = time.monotonic()
        try:
            resp = requests.get(f"{_GROQ_BASE}/models",
                                headers={"Authorization": f"Bearer {Config.GROQ_API_KEY}"}, timeout=5)
            latency = int((time.monotonic() - started) * 1000)
            if resp.status_code >= 400:
                return {"ok": False, "detail": f"HTTP {resp.status_code}", "latency_ms": latency}
            return {"ok": True, "detail": f"Reachable · {self._model()}", "latency_ms": latency}
        except Exception as e:
            return {"ok": False, "detail": str(e)[:120],
                    "latency_ms": int((time.monotonic() - started) * 1000)}


@register
class GroqBatchSTT(_GroqSTT):
    info = DriverInfo(
        key='groq_batch', capability='stt_batch', label='Groq Whisper (cloud)',
        blurb='Fast cloud transcription. A one-hour recording in a couple of minutes.',
        is_local=False, requires_env=('GROQ_API_KEY',),
        cost_hint='Free tier: ~2,000 requests/day, 7,200 audio-seconds/hour',
        options_schema={
            'model': {'type': 'string', 'default': 'whisper-large-v3-turbo',
                      'enum': _GROQ_MODELS, 'label': 'Model'},
            'temperature': {'type': 'number', 'default': 0.0, 'label': 'Temperature'},
        },
    )


@register
class GroqChunkedSTT(_GroqSTT):
    supports_live = True
    # Live chunks are seconds of audio, never megabytes. A low ceiling here turns
    # a malformed browser upload into a clear error instead of a slow 25 MB POST.
    max_bytes = 8 * 1024 * 1024
    info = DriverInfo(
        key='groq_chunked', capability='stt_live', label='Groq Whisper (cloud, chunked)',
        blurb='Live dictation and boardroom capture in ~15s chunks. Groq has no streaming socket, so "live" means chunked.',
        is_local=False, requires_env=('GROQ_API_KEY',),
        cost_hint='A 1-hour session ≈ 240 requests — about eight sessions/day on the free tier',
        options_schema={
            'model': {'type': 'string', 'default': 'whisper-large-v3-turbo',
                      'enum': _GROQ_MODELS, 'label': 'Model'},
        },
    )
    def _timeout(self):
        return 60


# --- local Whisper -----------------------------------------------------------

_WHISPER_MODELS = [
    "Systran/faster-whisper-tiny", "Systran/faster-whisper-base",
    "Systran/faster-whisper-small", "Systran/faster-whisper-large-v3",
]


class _LocalWhisperSTT(_WhisperCompatible):
    def _endpoint(self):
        return f"{Config.WHISPER_BASE_URL.rstrip('/')}/audio/transcriptions"

    def _model(self):
        return self.options.get('model') or Config.WHISPER_MODEL

    def _timeout(self):
        # Local transcription of a long piece on CPU is slow, not broken.
        return 1800

    def health(self):
        started = time.monotonic()
        try:
            resp = requests.get(f"{Config.WHISPER_BASE_URL.rstrip('/')}/models", timeout=3)
            latency = int((time.monotonic() - started) * 1000)
            if resp.status_code >= 400:
                return {"ok": False, "detail": f"HTTP {resp.status_code}", "latency_ms": latency}
            return {"ok": True, "detail": f"Reachable · {self._model()}", "latency_ms": latency}
        except Exception as e:
            return {"ok": False,
                    "detail": f"No Whisper server at {Config.WHISPER_BASE_URL} ({e.__class__.__name__})",
                    "latency_ms": int((time.monotonic() - started) * 1000)}

    @classmethod
    def available(cls):
        # Unlike the cloud drivers there is no env var to check — availability is
        # "is the server actually up", which only a probe can answer. Kept cheap
        # (3s timeout) because get() calls this on the resolution path.
        try:
            return requests.get(f"{Config.WHISPER_BASE_URL.rstrip('/')}/models", timeout=3).ok
        except Exception:
            return False

    @classmethod
    def missing_env(cls):
        return [] if cls.available() else [f'a Whisper server at {Config.WHISPER_BASE_URL}']


@register
class LocalWhisperBatchSTT(_LocalWhisperSTT):
    info = DriverInfo(
        key='local_whisper_batch', capability='stt_batch', label='Local Whisper (your hardware)',
        blurb='Free and fully private — audio never leaves the building. Slower: roughly real time per meeting-hour on CPU.',
        is_local=True, cost_hint='No marginal cost',
        options_schema={
            'model': {'type': 'string', 'default': 'Systran/faster-whisper-small',
                      'enum': _WHISPER_MODELS, 'label': 'Model'},
        },
    )


@register
class LocalWhisperChunkedSTT(_LocalWhisperSTT):
    supports_live = True
    max_bytes = 8 * 1024 * 1024
    info = DriverInfo(
        key='local_whisper_chunked', capability='stt_live', label='Local Whisper (chunked)',
        blurb='Live capture on your own hardware. `small` roughly keeps up on CPU; `large-v3` will fall behind a live room.',
        is_local=True, cost_hint='No marginal cost',
        options_schema={
            'model': {'type': 'string', 'default': 'Systran/faster-whisper-small',
                      'enum': _WHISPER_MODELS, 'label': 'Model'},
        },
    )
    def _timeout(self):
        return 120
