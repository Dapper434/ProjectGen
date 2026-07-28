"""Whisper parrots its `prompt` back as transcription when handed silence or
non-speech audio. Confirmed live against Groq: a 6-second pure tone with hints
"Aisha, Twiga Foods, Nairobi" transcribed as exactly that string.

Unguarded, that writes names nobody said into a client transcript — which breaks
the invariant that transcription never invents content (AGENTS.md §2.11). These
tests pin the guard.
"""
from providers.stt.whisper_api import _looks_like_echoed_hints, _parse_segments

HINTS = "Aisha, Twiga Foods, Nairobi, harvest campaign"


def test_exact_echo_is_caught():
    assert _looks_like_echoed_hints("Aisha, Twiga Foods, Nairobi, harvest campaign", HINTS)


def test_echo_is_caught_regardless_of_punctuation_and_case():
    assert _looks_like_echoed_hints("aisha twiga foods nairobi harvest campaign.", HINTS)


def test_partial_echo_is_caught():
    assert _looks_like_echoed_hints("Twiga Foods, Nairobi", HINTS)


def test_real_speech_containing_a_hinted_name_is_kept():
    # The whole point of hints is that these names DO get said. Only output made
    # entirely of hint words, with nothing else, is suspicious.
    assert not _looks_like_echoed_hints(
        "Aisha said the harvest campaign needs to launch before September.", HINTS
    )


def test_long_output_is_never_treated_as_an_echo():
    assert not _looks_like_echoed_hints(
        "Nairobi Nairobi Nairobi Twiga Twiga Aisha Aisha harvest harvest campaign campaign Twiga Aisha",
        HINTS,
    )


def test_no_hints_means_no_suppression():
    assert not _looks_like_echoed_hints("Aisha, Twiga Foods", "")


def test_parse_segments_drops_echoed_segments():
    payload = {"segments": [
        {"text": " Aisha, Twiga Foods, Nairobi", "start": 0.0, "end": 6.0},
    ]}
    assert _parse_segments(payload, 'groq_batch', hints=HINTS) == []


def test_parse_segments_keeps_genuine_speech():
    payload = {"segments": [
        {"text": " Aisha wants the film delivered by September.", "start": 0.0, "end": 4.0},
    ]}
    segments = _parse_segments(payload, 'groq_batch', hints=HINTS)
    assert len(segments) == 1
    assert segments[0].start_ms == 0 and segments[0].end_ms == 4000


def test_punctuation_only_segments_are_dropped():
    # Verified live: 6 seconds of pure tone transcribed as exactly ".".
    # A dictation UI appending one of those per silent chunk looks broken.
    payload = {"segments": [{"text": " .", "start": 0.0, "end": 6.0}]}
    assert _parse_segments(payload, 'groq_chunked', hints='') == []


def test_parse_segments_falls_back_to_flat_text_field():
    # A minimal Whisper build that ignores timestamp_granularities still works.
    payload = {"text": "the budget is one point four million"}
    segments = _parse_segments(payload, 'local_whisper_batch', hints=HINTS)
    assert len(segments) == 1
    assert segments[0].start_ms is None
