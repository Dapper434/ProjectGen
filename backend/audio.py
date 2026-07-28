"""ffmpeg wrappers: normalise, probe, split — WP-4 §4.6.

Every engine here caps a request at 25 MB, so long recordings have to be cut up.
The numbers below are derived from that ceiling rather than guessed: at 64 kbps
mono, ten minutes of audio is roughly 4.8 MB, comfortably inside it, and a
60-minute recording becomes six requests instead of the ~240 the live path would
need for the same hour.

ffmpeg is a system dependency (`apt install ffmpeg`), not a Python package.
"""
import json
import shutil
import subprocess
from pathlib import Path

# 10-minute pieces with 2s of overlap. The overlap exists so a word straddling a
# cut survives: both pieces contain it, and stitch.join() drops the duplicate.
PIECE_SECONDS = 600
OVERLAP_SECONDS = 2


class AudioError(RuntimeError):
    """ffmpeg missing, or a file it could not decode."""


def ffmpeg_available():
    return bool(shutil.which('ffmpeg') and shutil.which('ffprobe'))


def _run(cmd, timeout=1800):
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except FileNotFoundError as e:
        raise AudioError("ffmpeg is not installed on this server (apt install ffmpeg).") from e
    except subprocess.TimeoutExpired as e:
        raise AudioError(f"ffmpeg timed out after {timeout}s.") from e
    if result.returncode != 0:
        tail = (result.stderr or b'').decode('utf-8', 'replace').strip().splitlines()
        raise AudioError(f"ffmpeg failed: {tail[-1] if tail else 'unknown error'}")
    return result


def probe_duration(src):
    """Duration in seconds, or None when ffprobe cannot determine it."""
    result = _run([
        'ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', str(src),
    ], timeout=60)
    try:
        return float(json.loads(result.stdout)['format']['duration'])
    except (ValueError, KeyError, TypeError):
        return None


def normalise(src, dst=None):
    """Any container or codec → 16 kHz mono MP3. Video in, audio out.

    16 kHz mono is what Whisper models actually consume; sending 48 kHz stereo
    just makes the upload bigger for no accuracy gain.
    """
    src = Path(src)
    dst = Path(dst) if dst else src.with_suffix('.norm.mp3')
    _run([
        'ffmpeg', '-y', '-i', str(src),
        '-vn', '-ac', '1', '-ar', '16000',
        '-c:a', 'libmp3lame', '-b:a', '64k',
        str(dst),
    ])
    return dst


def split(src, piece_seconds=PIECE_SECONDS, overlap_seconds=OVERLAP_SECONDS, out_dir=None):
    """Cut into overlapping pieces small enough for one request each.

    Returns [(path, start_seconds), ...] in order. A file shorter than one piece
    comes back as a single entry — callers do not special-case short recordings.
    """
    src = Path(src)
    out_dir = Path(out_dir) if out_dir else src.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    duration = probe_duration(src)
    if duration is None or duration <= piece_seconds:
        return [(src, 0.0)]

    pieces = []
    start = 0.0
    index = 0
    while start < duration:
        dst = out_dir / f"{src.stem}.part{index:03d}.mp3"
        # -ss before -i seeks by keyframe and is fast; re-encoding here (rather
        # than -c copy) guarantees each piece is independently decodable, which
        # a stream copy of a mid-file segment is not.
        _run([
            'ffmpeg', '-y', '-ss', str(start), '-t', str(piece_seconds),
            '-i', str(src), '-vn', '-ac', '1', '-ar', '16000',
            '-c:a', 'libmp3lame', '-b:a', '64k', str(dst),
        ])
        pieces.append((dst, start))
        index += 1
        if start + piece_seconds >= duration:
            break
        start += piece_seconds - overlap_seconds

    return pieces
