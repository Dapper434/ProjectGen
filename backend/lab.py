"""The Lab: run one input through several drivers and compare (WP-2 §2.6).

Drivers within a run execute **serially**, not in parallel. A four-way bake-off
running concurrently would occupy every slot in the shared three-thread executor
and stall every brief in the system; the whole run takes one slot instead.
"""
import json
import time
from difflib import SequenceMatcher
from pathlib import Path

from database import db_session
from models import ComparisonResult, ComparisonRun
from providers import registry


def create_run(capability, input_kind, input_ref, driver_keys, created_by=None,
               input_meta=None, prompt_labels=None):
    """Create the run and one pending result row per column, so the UI can
    render the full table immediately and fill it in as each driver finishes."""
    run = ComparisonRun(
        capability=capability, input_kind=input_kind, input_ref=str(input_ref),
        input_meta=json.dumps(input_meta or {}), status='running', created_by=created_by,
    )
    db_session.add(run)
    db_session.flush()

    # A column is a (driver, prompt variant) pair. With prompt labels supplied,
    # the same driver appears once per label — that is how "is the concise
    # prompt as good on Nemotron?" gets answered on real data.
    columns = []
    for key in driver_keys:
        for label in (prompt_labels or [None]):
            columns.append((key, label))

    for key, label in columns:
        cls = registry.get_driver_class(capability, key)
        db_session.add(ComparisonResult(
            run_id=run.id, driver_key=key, label=label or (cls.info.label if cls else key),
            status='pending',
        ))
    db_session.commit()
    return run


def _estimate_cost(cls, usage):
    if not cls or not usage:
        return None
    rate_in, rate_out = cls.info.rate_per_mtok
    if not (rate_in or rate_out):
        return None
    prompt_tokens = usage.get('prompt_tokens') or 0
    completion_tokens = usage.get('completion_tokens') or 0
    if not (prompt_tokens or completion_tokens):
        total = usage.get('total_tokens') or 0
        return round(total / 1_000_000 * rate_in, 6) if total else None
    return round(prompt_tokens / 1_000_000 * rate_in + completion_tokens / 1_000_000 * rate_out, 6)


def run_generation_comparison(run_id, system_prompt_by_label, user_prompt):
    """Executor task for an `agent_llm` bake-off. Takes primitive IDs only and
    owns its own session cleanup, like every other background job here."""
    try:
        run = db_session.query(ComparisonRun).get(run_id)
        if not run:
            return
        results = db_session.query(ComparisonResult).filter_by(run_id=run_id).order_by(ComparisonResult.id).all()

        for result in results:
            cls = registry.get_driver_class(run.capability, result.driver_key)
            if cls is None or not cls.available():
                result.status = 'error'
                result.error = (
                    f"{result.driver_key} is not available"
                    + (f" (missing {', '.join(cls.missing_env())})" if cls else "")
                )
                db_session.commit()
                continue

            system_prompt = system_prompt_by_label.get(result.label) or system_prompt_by_label.get(None) or ''
            started = time.monotonic()
            try:
                driver = cls()
                content, usage = driver.complete(system_prompt, user_prompt, reasoning='off')
                result.status = 'ok'
                result.output = content
                result.word_count = len(content.split())
                result.tokens_used = (usage or {}).get('total_tokens')
                result.est_cost_usd = _estimate_cost(cls, usage)
            except Exception as e:
                result.status = 'error'
                result.error = str(e)[:500]
            result.latency_ms = int((time.monotonic() - started) * 1000)
            db_session.commit()

        _compute_similarity(run_id)
        run = db_session.query(ComparisonRun).get(run_id)
        run.status = 'done'
        db_session.commit()
    except Exception as e:
        db_session.rollback()
        run = db_session.query(ComparisonRun).get(run_id)
        if run:
            run.status = 'error'
            db_session.commit()
        print(f"Lab run {run_id} failed: {e}")
    finally:
        db_session.remove()


def run_transcription_comparison(run_id, audio_path, hints=''):
    """Executor task for an `stt_batch` bake-off — the same recording through
    each selected engine, serially. This is what makes "is local good enough?"
    answerable on the agency's own audio rather than on a vendor benchmark."""
    import transcribe
    from config import Config

    prepared = None
    try:
        run = db_session.query(ComparisonRun).get(run_id)
        if not run:
            return
        results = db_session.query(ComparisonResult).filter_by(run_id=run_id).order_by(ComparisonResult.id).all()

        # Prepared once, not per driver: every column transcribes the same pieces,
        # so ffmpeg runs once and there is a single owner for the derived files.
        prepared = transcribe.PreparedAudio(audio_path)

        for result in results:
            cls = registry.get_driver_class(run.capability, result.driver_key)
            if cls is None or not cls.available():
                result.status = 'error'
                result.error = f"{result.driver_key} is not available on this server."
                db_session.commit()
                continue

            started = time.monotonic()
            try:
                out = transcribe.transcribe_prepared(
                    prepared, capability=run.capability, hints=hints,
                    override=result.driver_key,
                )
                result.status = 'ok'
                result.output = out['text']
                result.word_count = len(out['text'].split())
                duration = out.get('duration_s')
                result.metrics = json.dumps({
                    "pieces": out['pieces'],
                    "duration_s": duration,
                    # A driver that silently drops half the audio shows up here
                    # instantly, where a raw word count would look plausible.
                    "words_per_audio_minute": (
                        round(len(out['text'].split()) / (duration / 60), 1)
                        if duration else None
                    ),
                })
            except Exception as e:
                result.status = 'error'
                result.error = str(e)[:500]
            result.latency_ms = int((time.monotonic() - started) * 1000)
            db_session.commit()

        _compute_similarity(run_id, keep_existing_metrics=True)
        run = db_session.query(ComparisonRun).get(run_id)
        run.status = 'done'
        db_session.commit()
    except Exception as e:
        db_session.rollback()
        run = db_session.query(ComparisonRun).get(run_id)
        if run:
            run.status = 'error'
            db_session.commit()
        print(f"Lab transcription run {run_id} failed: {e}")
    finally:
        # Derived audio always goes; the uploaded original only survives when the
        # operator explicitly asked to keep audio.
        if prepared is not None:
            prepared.cleanup(remove_source=not Config.STT_KEEP_AUDIO)
        elif not Config.STT_KEEP_AUDIO:
            try:
                Path(audio_path).unlink(missing_ok=True)
            except OSError:
                pass
        db_session.remove()


def _compute_similarity(run_id, keep_existing_metrics=False):
    """Agreement with the first successful column.

    This is explicitly NOT a word error rate — there is no ground truth here.
    But "the local model agrees with Nemotron 94% of the time" is the
    decision-grade number you actually want before switching engines.
    """
    results = db_session.query(ComparisonResult).filter_by(run_id=run_id).order_by(ComparisonResult.id).all()
    reference = next((r for r in results if r.status == 'ok' and r.output), None)
    if not reference:
        return
    for result in results:
        if result.status != 'ok' or not result.output:
            continue
        existing = {}
        if keep_existing_metrics and result.metrics:
            try:
                existing = json.loads(result.metrics)
            except (ValueError, TypeError):
                existing = {}
        ratio = SequenceMatcher(None, reference.output, result.output).ratio()
        result.metrics = json.dumps({
            **existing,
            "similarity_to_reference": round(ratio, 4),
            "reference_driver": reference.driver_key,
            "reference_label": reference.label,
            "is_reference": result.id == reference.id,
        })
    db_session.commit()


def run_json(run, include_output=True):
    results = db_session.query(ComparisonResult).filter_by(run_id=run.id).order_by(ComparisonResult.id).all()
    return {
        "id": run.id,
        "capability": run.capability,
        "input_kind": run.input_kind,
        "input_ref": run.input_ref,
        "input_meta": json.loads(run.input_meta) if run.input_meta else {},
        "status": run.status,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "results": [{
            "id": r.id,
            "driver_key": r.driver_key,
            "label": r.label,
            "status": r.status,
            "output": (r.output if include_output else None),
            "error": r.error,
            "latency_ms": r.latency_ms,
            "word_count": r.word_count,
            "tokens_used": r.tokens_used,
            "est_cost_usd": r.est_cost_usd,
            "metrics": json.loads(r.metrics) if r.metrics else None,
        } for r in results],
    }
