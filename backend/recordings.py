"""Recording Studio worker — WP-6.

Turns an uploaded recording into a reviewed transcript, then hands it to the
transcript endpoint that already exists. No brief agent of its own.

The semaphore is the important line in this file. Without it, three concurrent
uploads occupy all three shared executor threads and every brief in the system
stops generating — a one-line guard against a very annoying outage.
"""
import datetime
import json
import threading

from database import db_session
from locks import AlreadyProcessing, agent_lock
from models import RecordingJob, RecordingSegment
from providers import registry

# At most ONE transcription at a time, however many are queued.
_TRANSCRIBE_SEMAPHORE = threading.Semaphore(1)

TERMINAL_STATUSES = ('ready', 'attached', 'failed', 'cancelled')


def _set(job, **fields):
    for key, value in fields.items():
        setattr(job, key, value)
    db_session.commit()


def _persist_segments(job_id, segments):
    db_session.query(RecordingSegment).filter_by(job_id=job_id).delete()
    for seq, segment in enumerate(segments):
        db_session.add(RecordingSegment(
            job_id=job_id, seq=seq, text=segment.text,
            start_ms=segment.start_ms, end_ms=segment.end_ms,
            speaker=segment.speaker, confidence=segment.confidence,
        ))
    db_session.commit()


def run_recording_job(job_id):
    """Runs on the shared ThreadPoolExecutor, serialised by the semaphore."""
    import time

    import stt_hints
    import transcribe
    from config import Config
    from polish import polish

    prepared = None
    started = time.monotonic()

    with _TRANSCRIBE_SEMAPHORE:
        try:
            with agent_lock('transcription', 'recording_job', job_id, ttl_minutes=120):
                job = db_session.query(RecordingJob).get(job_id)
                if not job or job.status == 'cancelled':
                    return

                try:
                    _set(job, status='normalising', progress_pct=2)
                    prepared = transcribe.PreparedAudio(job.source_path)
                    _set(job, status='transcribing',
                         duration_sec=int(prepared.duration_s) if prepared.duration_s else None,
                         pieces_total=len(prepared.pieces), pieces_done=0, progress_pct=5)

                    hints = stt_hints.build_hints(job.engagement_id) if job.engagement_id \
                        else stt_hints.agency_vocabulary()
                    options = json.loads(job.driver_options) if job.driver_options else None

                    import stitch
                    all_segments = []
                    combined = ''
                    driver_used = None
                    degraded = False

                    for index, (piece_path, start_seconds) in enumerate(prepared.pieces):
                        with open(piece_path, 'rb') as fh:
                            result = transcribe.transcribe_piece(
                                fh.read(), 'audio/mpeg', capability='stt_batch',
                                hints=hints, language=job.language or 'en',
                                override=job.driver_key,
                            )
                        driver_used = driver_used or result['driver']
                        degraded = degraded or result['degraded']
                        combined = stitch.join(combined, result['text'])
                        all_segments = stitch.join_segments(
                            all_segments, result['segments'],
                            next_offset_ms=int(start_seconds * 1000),
                        )
                        # Persist as we go so a later failure can resume rather
                        # than re-transcribe an hour of audio from zero.
                        _persist_segments(job.id, all_segments)
                        job = db_session.query(RecordingJob).get(job_id)
                        _set(job, pieces_done=index + 1,
                             progress_pct=int((index + 1) / len(prepared.pieces) * 90),
                             raw_text=combined)

                    job = db_session.query(RecordingJob).get(job_id)
                    if driver_used and driver_used != job.driver_key:
                        # A mid-job failover is recorded, not hidden — the badge
                        # must tell the truth about which engine produced this.
                        _set(job, driver_key=driver_used)

                    _set(job, status='polishing', progress_pct=92)
                    polished, _prov = polish(combined, names=[n.strip() for n in hints.split(',') if n.strip()])

                    _set(job, status='ready', polished_text=polished, progress_pct=100,
                         latency_ms=int((time.monotonic() - started) * 1000),
                         completed_at=datetime.datetime.utcnow(), error=None)

                except Exception as e:
                    db_session.rollback()
                    job = db_session.query(RecordingJob).get(job_id)
                    if job:
                        _set(job, status='failed', error=f"{e.__class__.__name__}: {str(e)[:400]}")
                    print(f"Recording job {job_id} failed: {e}")
        except AlreadyProcessing:
            job = db_session.query(RecordingJob).get(job_id)
            if job:
                _set(job, status='failed', error="This recording is already being transcribed.")
        finally:
            # Text is the artefact; audio is a liability.
            from config import Config as _Config
            if prepared is not None:
                prepared.cleanup(remove_source=not _Config.STT_KEEP_AUDIO)
            db_session.remove()


def job_json(job, include_segments=False):
    out = {
        "id": job.id,
        "title": job.title,
        "status": job.status,
        "engagement_id": job.engagement_id,
        "client_id": job.client_id,
        "source_name": job.source_name,
        "source_bytes": job.source_bytes,
        "duration_sec": job.duration_sec,
        "driver_key": job.driver_key,
        "polish_driver": job.polish_driver,
        "language": job.language,
        "pieces_total": job.pieces_total,
        "pieces_done": job.pieces_done,
        "progress_pct": job.progress_pct,
        "raw_text": job.raw_text,
        "polished_text": job.polished_text,
        "edited_text": job.edited_text,
        "latency_ms": job.latency_ms,
        "error": job.error,
        "attached_transcript_id": job.attached_transcript_id,
        "comparison_run_id": job.comparison_run_id,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }
    driver_cls = registry.get_driver_class('stt_batch', job.driver_key)
    out["driver_label"] = driver_cls.info.label if driver_cls else job.driver_key
    out["is_local"] = driver_cls.info.is_local if driver_cls else None

    if include_segments:
        segments = (db_session.query(RecordingSegment)
                    .filter_by(job_id=job.id).order_by(RecordingSegment.seq).all())
        out["segments"] = [{
            "seq": s.seq, "text": s.text, "start_ms": s.start_ms,
            "end_ms": s.end_ms, "speaker": s.speaker,
        } for s in segments]
    return out


def estimate_seconds(duration_sec, driver_key):
    """Rough completion estimate for the upload form.

    The single most useful thing on that page: "Groq — about 2 minutes" versus
    "Local Whisper — about 22 minutes, free, nothing leaves this machine" is the
    whole decision, and it cannot be made without a number.
    """
    if not duration_sec:
        return None
    # Measured shape rather than vendor claims: Groq turbo runs ~30x real time,
    # faster-whisper `small` on CPU runs at roughly real time.
    factor = 0.033 if driver_key and driver_key.startswith('groq') else 1.05
    return int(duration_sec * factor) + 5
