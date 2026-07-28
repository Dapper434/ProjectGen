"""Overlap-aware stitching (WP-4 §4.6) — priority-3 in AGENTS.md's test table,
but cheap and it protects the thing that is hardest to debug from a transcript:
a word silently dropped or doubled at a piece boundary.
"""
import stitch


def test_join_drops_the_duplicated_seam():
    prev = "the client wants a two minute brand film for the harvest campaign"
    nxt = "for the harvest campaign plus six social cutdowns"
    assert stitch.join(prev, nxt) == (
        "the client wants a two minute brand film for the harvest campaign "
        "plus six social cutdowns"
    )


def test_join_keeps_everything_when_there_is_no_overlap():
    prev = "budget is one point four million shillings"
    nxt = "delivery before the end of september"
    assert stitch.join(prev, nxt) == f"{prev} {nxt}"


def test_join_tolerates_small_transcription_differences_in_the_seam():
    # The same audio transcribed twice rarely comes back byte-identical; the
    # seam still has to collapse.
    prev = "we need the Kiswahili voiceover ready by friday"
    nxt = "we need the Kiswahili voice over ready by friday and the subtitles too"
    joined = stitch.join(prev, nxt)
    assert joined.endswith("and the subtitles too")
    assert joined.count("Kiswahili") == 1


def test_repeated_phrase_inside_the_overlap_collapses_once():
    # Longest-first matching matters here: checking short candidates first would
    # match the inner repeat and leave the outer duplicate behind.
    prev = "thank you thank you very much for your time today"
    nxt = "thank you very much for your time today lets begin"
    joined = stitch.join(prev, nxt)
    assert joined == "thank you thank you very much for your time today lets begin"


def test_genuine_repetition_outside_the_seam_is_preserved():
    prev = "yes yes exactly"
    nxt = "moving on to the budget"
    assert stitch.join(prev, nxt) == "yes yes exactly moving on to the budget"


def test_empty_inputs():
    assert stitch.join("", "hello there") == "hello there"
    assert stitch.join("hello there", "") == "hello there"
    assert stitch.join("", "") == ""


def test_join_all_folds_a_whole_recording():
    pieces = [
        "the first item on the agenda is the budget",
        "on the agenda is the budget and the timeline",
        "and the timeline which we agreed last week",
    ]
    assert stitch.join_all(pieces) == (
        "the first item on the agenda is the budget and the timeline "
        "which we agreed last week"
    )


def test_find_overlap_ignores_coincidental_short_matches():
    # Two pieces both containing "and" is not a seam.
    prev = "we discussed scope and".split()
    nxt = "and then we moved on".split()
    assert stitch.find_overlap(prev, nxt) == 0


def test_join_segments_shifts_timestamps_into_whole_recording_time():
    # Segment text here is deliberately realistic: a 2-second audio overlap is
    # several words, which is what MIN_OVERLAP_WORDS assumes. A two-word seam is
    # below that floor on purpose — see the coincidence test above.
    from providers.stt.base import Segment
    overlap_text = "so that covers the budget"
    first = [Segment(text=overlap_text, start_ms=0, end_ms=2000)]
    second = [
        Segment(text=overlap_text, start_ms=0, end_ms=2000),                    # the seam
        Segment(text="now lets talk timeline", start_ms=2000, end_ms=4000),
    ]
    joined = stitch.join_segments(first, second, next_offset_ms=598_000)
    assert [s.text for s in joined] == [overlap_text, "now lets talk timeline"]
    assert joined[1].start_ms == 600_000  # 2000ms into a piece starting at 598s
