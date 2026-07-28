"""Speech-to-text driver interface — WP-4 §4.3.

One piece of audio in, `Segment`s out. Pieces are produced by `audio.split()`
for the batch path, or by the browser's MediaRecorder for the live path; the
driver does not care which.
"""
import threading
import time
from abc import abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from providers.base import Driver


@dataclass
class Segment:
    text: str
    start_ms: Optional[int] = None
    end_ms: Optional[int] = None
    confidence: Optional[float] = None
    speaker: Optional[str] = None
    provider: str = ""
    raw: Optional[dict] = field(default=None, repr=False)

    def to_json(self):
        return {"text": self.text, "start_ms": self.start_ms, "end_ms": self.end_ms,
                "confidence": self.confidence, "speaker": self.speaker, "provider": self.provider}


class STTError(RuntimeError):
    """Base for speech errors that callers are expected to handle."""


class STTRateLimited(STTError):
    """429 from the provider. Carries the server's own retry hint so the caller
    backs off by the amount asked for rather than a guess."""

    def __init__(self, retry_after=5.0, detail=''):
        super().__init__(detail or f"Rate limited; retry in {retry_after}s")
        self.retry_after = retry_after


class STTUnavailable(STTError):
    """The engine could not be reached at all — triggers failover to the next driver."""


# --- free-tier budget tracking ---------------------------------------------
# Groq returns x-ratelimit-* headers on every response. Reading them is how the
# UI can show a remaining-budget meter instead of failing mysteriously at
# request 2,001. In-memory only: this is a hint for humans, not an accounting
# record, and one gunicorn worker means one process to keep it in.
_rate_lock = threading.Lock()
_rate_state = {}


def record_rate_headers(driver_key, headers):
    if not headers:
        return
    interesting = {k.lower(): v for k, v in headers.items() if k.lower().startswith('x-ratelimit')}
    if not interesting:
        return
    with _rate_lock:
        _rate_state[driver_key] = {**interesting, 'observed_at': time.time()}


def rate_status(driver_key=None):
    with _rate_lock:
        if driver_key:
            return dict(_rate_state.get(driver_key) or {})
        return {k: dict(v) for k, v in _rate_state.items()}


class STTDriver(Driver):
    supports_timestamps = False
    supports_live = False
    # Both Groq and the OpenAI-compatible Whisper servers cap a request at 25 MB.
    max_bytes = 25 * 1024 * 1024

    @abstractmethod
    def transcribe(self, audio, mime, hints="", language="en"):
        """One piece of audio in, list[Segment] out.

        `hints` biases spelling and is the cheapest accuracy win in the system —
        feed it client, producer and talent names (see stt_hints.py). Both Groq
        and Whisper accept roughly 224 tokens here.
        """

    def transcribe_text(self, audio, mime, hints="", language="en"):
        return " ".join(s.text for s in self.transcribe(audio, mime, hints=hints, language=language)).strip()
