"""Overlap-aware joining of transcript pieces — WP-4 §4.6.

`audio.split()` deliberately overlaps pieces so no word is lost at a cut. That
means the same words appear at the end of one piece and the start of the next,
and something has to drop the duplicate without also dropping real repetition.

Uses `difflib.SequenceMatcher` — the same tool the client-name matching uses, so
there is one familiar failure mode in the codebase rather than two.
"""
from difflib import SequenceMatcher

MAX_OVERLAP_WORDS = 40
# Below this, an apparent overlap is more likely coincidence (two pieces both
# ending and starting with "and the") than a genuine duplicated seam.
MIN_OVERLAP_WORDS = 3
SIMILARITY_THRESHOLD = 0.86


def _norm(word):
    return ''.join(ch for ch in word.lower() if ch.isalnum())


def find_overlap(prev_words, next_words, max_overlap_words=MAX_OVERLAP_WORDS):
    """Length, in words, of the longest suffix of `prev` that matches a prefix of
    `next`. Zero when there is no convincing overlap.

    Two passes, and the order is load-bearing. An **exact** token match is
    unambiguous evidence of a seam; a fuzzy one is a guess. Interleaving them
    lets a near-miss at a longer size outrank an exact match at a shorter size
    and swallow a real word — e.g. joining
    "thank you thank you very much for your time today" with
    "thank you very much for your time today lets begin" scores 0.897 at size 9
    (over the threshold) while the true seam is the exact match at size 8, and
    taking the fuzzy answer silently drops "lets".

    Within each pass, longest-first, so a genuinely repeated phrase inside the
    overlap window collapses once rather than partially.
    """
    limit = min(len(prev_words), len(next_words), max_overlap_words)
    if limit < MIN_OVERLAP_WORDS:
        return 0

    tails = {size: [_norm(w) for w in prev_words[-size:]] for size in range(limit, MIN_OVERLAP_WORDS - 1, -1)}
    heads = {size: [_norm(w) for w in next_words[:size]] for size in range(limit, MIN_OVERLAP_WORDS - 1, -1)}

    for size in range(limit, MIN_OVERLAP_WORDS - 1, -1):
        if any(tails[size]) and tails[size] == heads[size]:
            return size

    for size in range(limit, MIN_OVERLAP_WORDS - 1, -1):
        if not any(tails[size]):
            continue
        if SequenceMatcher(None, ' '.join(tails[size]), ' '.join(heads[size])).ratio() >= SIMILARITY_THRESHOLD:
            return size

    return 0


def join(prev_text, next_text, max_overlap_words=MAX_OVERLAP_WORDS):
    """Concatenate two pieces, dropping the duplicated seam."""
    prev_text = (prev_text or '').strip()
    next_text = (next_text or '').strip()
    if not prev_text:
        return next_text
    if not next_text:
        return prev_text

    prev_words = prev_text.split()
    next_words = next_text.split()
    overlap = find_overlap(prev_words, next_words, max_overlap_words)
    return ' '.join(prev_words + next_words[overlap:])


def join_all(texts, max_overlap_words=MAX_OVERLAP_WORDS):
    """Fold a list of piece transcripts into one, seam by seam."""
    result = ''
    for text in texts:
        result = join(result, text, max_overlap_words)
    return result


def join_segments(prev_segments, next_segments, next_offset_ms=0, max_overlap_words=MAX_OVERLAP_WORDS):
    """Segment-level join that also shifts the next piece's timestamps into
    whole-recording time. Segments fully inside the duplicated seam are dropped.
    """
    prev_segments = list(prev_segments or [])
    next_segments = list(next_segments or [])
    if not prev_segments:
        return _shift(next_segments, next_offset_ms)
    if not next_segments:
        return prev_segments

    prev_words = ' '.join(s.text for s in prev_segments).split()
    next_words = ' '.join(s.text for s in next_segments).split()
    overlap = find_overlap(prev_words, next_words, max_overlap_words)

    kept, consumed = [], 0
    for segment in next_segments:
        words = len(segment.text.split())
        if consumed + words <= overlap:
            consumed += words
            continue
        kept.append(segment)
    return prev_segments + _shift(kept, next_offset_ms)


def _shift(segments, offset_ms):
    if not offset_ms:
        return list(segments)
    shifted = []
    for s in segments:
        s.start_ms = None if s.start_ms is None else s.start_ms + offset_ms
        s.end_ms = None if s.end_ms is None else s.end_ms + offset_ms
        shifted.append(s)
    return shifted
