"""No-op drivers: the honest "this capability is switched off" state.

`off` is the registry fallback for stt_live, stt_batch and polish, so it must
always be available and must never raise. Returning an empty result with an
explicit reason is deliberate — silently returning fabricated text would violate
the invariant that nothing is ever invented into a transcript.
"""
from providers.base import Driver, DriverInfo, STTDriver
from providers.registry import register


class _OffMixin:
    def health(self):
        return {"ok": True, "detail": "Switched off — no transcription will run.", "latency_ms": 0}


@register
class OffLive(_OffMixin, STTDriver):
    info = DriverInfo(
        key='off', capability='stt_live', label='Off',
        blurb='No live transcription. The boardroom still records notes typed by hand.',
        is_local=True, cost_hint='Free',
    )

    def transcribe(self, audio_path, language=None, timeout=300):
        return {"text": "", "segments": None, "duration_s": None,
                "note": "Live speech-to-text is switched off."}


@register
class OffBatch(_OffMixin, STTDriver):
    info = DriverInfo(
        key='off', capability='stt_batch', label='Off',
        blurb='No recording transcription. Uploaded audio is stored but not transcribed.',
        is_local=True, cost_hint='Free',
    )

    def transcribe(self, audio_path, language=None, timeout=300):
        return {"text": "", "segments": None, "duration_s": None,
                "note": "Recording transcription is switched off."}


@register
class OffPolish(_OffMixin, Driver):
    info = DriverInfo(
        key='off', capability='polish', label='Off (raw transcript)',
        blurb='Keep the transcript exactly as the speech engine produced it. No cleanup pass.',
        is_local=True, cost_hint='Free',
    )

    def polish(self, text, timeout=120):
        return text
