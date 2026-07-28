"""The shared transcription pipeline — WP-4.

Both post-meeting paths (cloud and local) run through here and differ only by
driver. That is the whole point of the abstraction: the same recording can be
transcribed both ways and diffed in the Lab before anyone commits.

The failover rule is the part that matters in a live room: on a 429, back off
once by the amount the server asked for, then **move to the next available
driver rather than dropping audio**. A dropped chunk is a hole in the record.
"""
import time

from providers import registry
from providers.stt.base import STTError, STTRateLimited, STTUnavailable

# Tried in order when the selected driver fails. Ends at the browser tier for
# live capture, which is the only one that survives a dead connection.
FAILOVER_CHAINS = {
    'stt_batch': ['groq_batch', 'local_whisper_batch', 'wispr_batch'],
    'stt_live': ['groq_chunked', 'local_whisper_chunked', 'wispr_stream', 'browser_webspeech'],
}


def _candidates(capability, override=None):
    """Selected driver first, then the rest of the chain — skipping unavailable
    engines and the browser marker driver, which cannot transcribe server-side."""
    selected = override or registry.current_selection(capability)[0]
    ordered = [selected] + [k for k in FAILOVER_CHAINS.get(capability, []) if k != selected]

    out = []
    for key in ordered:
        cls = registry.get_driver_class(capability, key)
        if cls is None or key in ('off', 'browser_webspeech'):
            continue
        if not cls.available():
            continue
        out.append((key, cls))
    return out


def transcribe_piece(audio_bytes, mime, capability='stt_batch', hints='', language='en',
                     override=None, on_event=None):
    """One piece of audio through the first driver that can handle it.

    Returns {'segments', 'text', 'driver', 'degraded', 'attempts', 'latency_ms'}.
    `degraded` is True when the engine that answered was not the one selected —
    the UI shows that as a badge rather than pretending nothing happened.
    """
    candidates = _candidates(capability, override)
    if not candidates:
        raise STTUnavailable(
            f"No {capability} engine is available. Check Providers — the selected driver "
            f"may be missing an API key, or the local server may be down."
        )

    selected_key = candidates[0][0]
    attempts = []
    started = time.monotonic()

    for key, cls in candidates:
        driver = cls()
        for attempt in (1, 2):
            try:
                segments = driver.transcribe(audio_bytes, mime, hints=hints, language=language)
                return {
                    "segments": segments,
                    "text": ' '.join(s.text for s in segments).strip(),
                    "driver": key,
                    "driver_label": cls.info.label,
                    "is_local": cls.info.is_local,
                    "degraded": key != selected_key,
                    "attempts": attempts,
                    "latency_ms": int((time.monotonic() - started) * 1000),
                }
            except STTRateLimited as e:
                attempts.append({"driver": key, "error": "rate_limited", "retry_after": e.retry_after})
                if on_event:
                    on_event({"type": "rate_limited", "driver": key, "retry_after": e.retry_after})
                if attempt == 1:
                    # Honour the server's own hint, but never stall a request path
                    # for long — failing over is better than waiting a minute.
                    time.sleep(min(e.retry_after, 10))
                    continue
                break  # second 429: stop retrying this driver, fail over
            except (STTUnavailable, STTError) as e:
                attempts.append({"driver": key, "error": str(e)[:200]})
                if on_event:
                    on_event({"type": "driver_failed", "driver": key, "detail": str(e)[:200]})
                break
            except Exception as e:
                attempts.append({"driver": key, "error": f"{e.__class__.__name__}: {str(e)[:180]}"})
                break

    raise STTUnavailable(
        "Every available speech engine failed: "
        + '; '.join(f"{a['driver']} ({a.get('error')})" for a in attempts)
    )


class PreparedAudio:
    """Normalised, split audio ready to hand to one or more engines.

    Separated from transcription because the Lab runs several drivers over the
    *same* recording: preparing once avoids re-running ffmpeg per driver, and —
    more importantly — gives one owner for the derived files so they cannot be
    left on disk when STT_KEEP_AUDIO is false. Use as a context manager.
    """

    def __init__(self, path):
        import audio as audio_mod
        from pathlib import Path

        if not audio_mod.ffmpeg_available():
            raise STTUnavailable("ffmpeg is not installed on this server, so recordings cannot be split.")

        self._audio_mod = audio_mod
        self.source = Path(path)
        self.derived = []

        self.normalised = audio_mod.normalise(self.source)
        self.derived.append(self.normalised)
        self.duration_s = audio_mod.probe_duration(self.normalised)
        self.pieces = audio_mod.split(self.normalised)
        self.derived.extend(p for p, _ in self.pieces if p != self.normalised)

    def cleanup(self, remove_source=False):
        """Delete every derived file, and optionally the original. Client meeting
        audio is sensitive by default — 'not persisted' has to mean gone from the
        filesystem, not merely unreferenced."""
        targets = list(self.derived) + ([self.source] if remove_source else [])
        for temp in targets:
            try:
                if temp.exists():
                    temp.unlink()
            except OSError:
                pass
        self.derived = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def transcribe_prepared(prepared, capability='stt_batch', hints='', language='en',
                        override=None, on_progress=None):
    """Transcribe already-prepared pieces and stitch them back together."""
    import stitch

    all_segments = []
    combined = ''
    driver_used = None
    degraded = False

    for index, (piece_path, start_seconds) in enumerate(prepared.pieces):
        if on_progress:
            on_progress({"piece": index + 1, "of": len(prepared.pieces)})
        with open(piece_path, 'rb') as fh:
            result = transcribe_piece(fh.read(), 'audio/mpeg', capability=capability,
                                      hints=hints, language=language, override=override)
        driver_used = driver_used or result['driver']
        degraded = degraded or result['degraded']
        combined = stitch.join(combined, result['text'])
        all_segments = stitch.join_segments(all_segments, result['segments'],
                                            next_offset_ms=int(start_seconds * 1000))

    return {
        "text": combined,
        "segments": all_segments,
        "driver": driver_used,
        "degraded": degraded,
        "pieces": len(prepared.pieces),
        "duration_s": prepared.duration_s,
    }


def transcribe_file(path, capability='stt_batch', hints='', language='en', override=None,
                    on_progress=None, keep_audio=False):
    """A whole recording, end to end: normalise, split, transcribe, stitch.

    Returns {'text', 'segments', 'driver', 'degraded', 'pieces', 'duration_s'}.
    Derived audio is always cleaned up; `keep_audio` only controls the original.
    """
    prepared = PreparedAudio(path)
    try:
        return transcribe_prepared(prepared, capability=capability, hints=hints,
                                   language=language, override=override, on_progress=on_progress)
    finally:
        prepared.cleanup(remove_source=not keep_audio)
