"""Runtime driver selection: reading the current state and writing changes with
an audit trail (WP-2 §2.3).

Kept out of app.py so routes stay thin, and out of providers/registry.py so the
registry has no ORM write dependency.
"""
import json
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

from database import db_session
from models import RuntimeSetting, SettingChange
from providers import registry

# Health probes hit the network. They run in their own tiny pool, never the
# shared agent executor — a slow probe must not consume a slot that briefs need.
# See WP-2's acceptance criterion: the whole health sweep returns in under two
# seconds even when a local Whisper server is unreachable.
_health_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix='health')
_HEALTH_TTL_SECONDS = 30
_health_cache = {'at': 0.0, 'data': None}


class SettingsError(ValueError):
    """A rejected settings write — unknown capability or driver."""


def describe_driver(cls, capability, selected_key):
    return {
        "key": cls.info.key,
        "capability": capability,
        "label": cls.info.label,
        "blurb": cls.info.blurb,
        "is_local": cls.info.is_local,
        "cost_hint": cls.info.cost_hint,
        "requires_env": list(cls.info.requires_env),
        "missing_env": cls.missing_env(),
        "available": cls.available(),
        "options_schema": cls.info.options_schema or {},
        "selected": cls.info.key == selected_key,
    }


def list_capabilities():
    out = []
    for capability, meta in registry.CAPABILITIES.items():
        selected_key, source = registry.current_selection(capability)
        drivers = registry.drivers_for(capability)
        out.append({
            "capability": capability,
            "label": meta['label'],
            "fallback": meta['fallback'],
            "selected": selected_key,
            "selected_source": source,   # runtime | env | fallback
            "options": registry.runtime_options(capability),
            "drivers": [describe_driver(cls, capability, selected_key)
                        for _, cls in sorted(drivers.items())],
        })
    return out


def _probe(capability, key, cls):
    started = time.monotonic()
    try:
        result = cls(registry.runtime_options(capability) if key == registry.current_selection(capability)[0] else None).health()
    except Exception as e:
        # A driver's health() is contractually not allowed to raise, but if one
        # does it must not take the whole sweep down with it.
        result = {"ok": False, "detail": f"health() raised: {str(e)[:100]}", "latency_ms": None}
    result.setdefault('latency_ms', int((time.monotonic() - started) * 1000))
    return {"capability": capability, "driver_key": key, **result}


def health_all(force=False):
    """Live health for every registered driver. Probes run in parallel and the
    whole sweep is timeboxed, so one unreachable host cannot hang the page."""
    now = time.monotonic()
    if not force and _health_cache['data'] and (now - _health_cache['at']) < _HEALTH_TTL_SECONDS:
        return _health_cache['data']

    futures = {}
    for capability, drivers in ((c, registry.drivers_for(c)) for c in registry.CAPABILITIES):
        for key, cls in drivers.items():
            futures[_health_pool.submit(_probe, capability, key, cls)] = (capability, key)

    results = []
    deadline = time.monotonic() + 2.0
    for future, (capability, key) in futures.items():
        remaining = max(0.0, deadline - time.monotonic())
        try:
            results.append(future.result(timeout=remaining))
        except FuturesTimeout:
            results.append({"capability": capability, "driver_key": key, "ok": False,
                            "detail": "Health probe timed out.", "latency_ms": None})
        except Exception as e:
            results.append({"capability": capability, "driver_key": key, "ok": False,
                            "detail": str(e)[:120], "latency_ms": None})

    _health_cache['data'] = results
    _health_cache['at'] = now
    return results


def set_driver(capability, driver_key, options=None, changed_by=None, reason=None):
    """Point a capability at a driver. Takes effect on the very next request —
    the registry cache is invalidated here rather than left to expire."""
    if capability not in registry.CAPABILITIES:
        raise SettingsError(f"Unknown capability: {capability!r}")
    cls = registry.get_driver_class(capability, driver_key)
    if cls is None:
        raise SettingsError(f"{driver_key!r} is not a registered driver for {capability!r}")
    if not cls.available():
        raise SettingsError(
            f"{cls.info.label} cannot be selected: {', '.join(cls.missing_env())} is not set on the server."
        )

    previous, _ = registry.current_selection(capability)
    encoded = json.dumps(options) if options else None

    row = db_session.query(RuntimeSetting).filter_by(capability=capability).first()
    if row:
        row.driver_key = driver_key
        row.options = encoded
        row.updated_by = changed_by
    else:
        db_session.add(RuntimeSetting(capability=capability, driver_key=driver_key,
                                      options=encoded, updated_by=changed_by))

    db_session.add(SettingChange(capability=capability, from_driver=previous, to_driver=driver_key,
                                 options=encoded, changed_by=changed_by, reason=reason))
    db_session.commit()
    registry.invalidate_cache()
    return {"capability": capability, "from": previous, "to": driver_key}


def history(limit=100):
    rows = db_session.query(SettingChange).order_by(SettingChange.id.desc()).limit(limit).all()
    return [{
        "id": r.id, "capability": r.capability, "from_driver": r.from_driver,
        "to_driver": r.to_driver, "changed_by": r.changed_by, "reason": r.reason,
        "changed_at": r.changed_at.isoformat() if r.changed_at else None,
    } for r in rows]
