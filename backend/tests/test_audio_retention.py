"""WP-4 acceptance criterion: audio bytes are not persisted when
STT_KEEP_AUDIO=false — asserted by inspecting the filesystem afterwards.

This caught a real leak: the Lab passed keep_audio=True per driver (so every
column could read the same file) and only deleted the *original* at the end,
leaving ~14 MB of normalised and split pieces on disk after every bake-off.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

import audio
import transcribe


def _make_wav(path, seconds=3):
    subprocess.run(
        ['ffmpeg', '-y', '-f', 'lavfi', '-i', f'sine=frequency=300:duration={seconds}',
         '-ar', '16000', '-ac', '1', str(path)],
        capture_output=True, check=True,
    )


requires_ffmpeg = pytest.mark.skipif(
    not audio.ffmpeg_available(), reason="ffmpeg is not installed"
)


@pytest.fixture
def work_dir(tmp_path):
    d = tmp_path / 'audio'
    d.mkdir()
    yield d
    shutil.rmtree(d, ignore_errors=True)


@requires_ffmpeg
def test_prepared_audio_cleanup_removes_every_derived_file(work_dir):
    src = work_dir / 'rec.wav'
    _make_wav(src)

    prepared = transcribe.PreparedAudio(src)
    derived = list(prepared.derived)
    assert derived, "normalise should have produced at least one derived file"
    assert all(p.exists() for p in derived)

    prepared.cleanup(remove_source=False)
    assert not any(p.exists() for p in derived), "derived audio must be deleted"
    assert src.exists(), "remove_source=False must leave the original alone"


@requires_ffmpeg
def test_cleanup_can_also_remove_the_original(work_dir):
    src = work_dir / 'rec.wav'
    _make_wav(src)

    prepared = transcribe.PreparedAudio(src)
    prepared.cleanup(remove_source=True)

    assert not src.exists()
    assert list(work_dir.iterdir()) == [], "nothing at all should remain on disk"


@requires_ffmpeg
def test_transcribe_file_leaves_no_derived_audio_even_when_every_engine_fails(work_dir, monkeypatch):
    """The failure path is the one that leaks in practice — an exception must not
    skip cleanup."""
    src = work_dir / 'rec.wav'
    _make_wav(src)

    def _explode(*args, **kwargs):
        raise transcribe.STTUnavailable("no engine available")

    monkeypatch.setattr(transcribe, 'transcribe_piece', _explode)

    with pytest.raises(transcribe.STTUnavailable):
        transcribe.transcribe_file(str(src), keep_audio=True)

    leftovers = [p.name for p in work_dir.iterdir()]
    assert leftovers == ['rec.wav'], f"derived audio left behind: {leftovers}"


@requires_ffmpeg
def test_split_pieces_stay_under_the_request_ceiling(work_dir):
    """Both Groq and the Whisper servers cap a request at 25 MB."""
    src = work_dir / 'long.wav'
    _make_wav(src, seconds=1300)  # ~21 minutes → forces multiple pieces

    normalised = audio.normalise(src)
    pieces = audio.split(normalised, out_dir=work_dir)

    assert len(pieces) > 1, "a 21-minute recording must split"
    for path, _start in pieces:
        assert path.stat().st_size < 25 * 1024 * 1024

    # The 2s overlap is what stitch.join() relies on to avoid losing a word at a cut.
    starts = [start for _p, start in pieces]
    assert starts[1] == pytest.approx(audio.PIECE_SECONDS - audio.OVERLAP_SECONDS)
