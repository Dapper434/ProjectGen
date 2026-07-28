"""Browser Web Speech API — a marker driver.

Transcription happens entirely client-side via the browser's `SpeechRecognition`,
so this driver never receives audio. It exists so the browser tier is a
first-class, selectable option in Provider Settings and the fallback chain
rather than a special case hidden in the frontend.

**Do not delete this because a better engine exists.** It is the only tier that
survives a dead connection, and it costs nothing.
"""
from providers.base import DriverInfo
from providers.registry import register
from providers.stt.base import STTDriver, STTUnavailable


@register
class BrowserWebSpeech(STTDriver):
    supports_live = True
    supports_timestamps = False
    info = DriverInfo(
        key='browser_webspeech', capability='stt_live', label='Browser (on-device)',
        blurb='Uses the browser\'s own speech recognition. Free, works offline, no audio leaves the device — but quality varies by browser and it is Chrome-centric.',
        is_local=True, cost_hint='Free',
    )

    def transcribe(self, audio, mime, hints="", language="en"):
        raise STTUnavailable(
            "browser_webspeech transcribes in the browser — the server never receives audio for it."
        )

    def health(self):
        return {"ok": True, "detail": "Runs in the browser; nothing to reach.", "latency_ms": 0}
