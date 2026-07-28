"""Capability registry and driver resolution — WP-2 §2.2.

Resolution order, lowest priority to highest:

    hardcoded fallback  <  env default (Config)  <  runtime setting (DB)  <  per-request override

The fallback tier is the point of the whole design: a broken config or a missing
API key degrades to a working engine with a warning, never a 500.

Adding a driver is one class with `@register` — no route, settings, or Lab code
changes.
"""
import json
import logging
import threading
import time
from collections import defaultdict

from config import Config

log = logging.getLogger(__name__)

CAPABILITIES = {
    'stt_live':     {'label': 'Live speech-to-text',     'fallback': 'off'},
    'stt_batch':    {'label': 'Recording transcription', 'fallback': 'off'},
    'polish':       {'label': 'Transcript cleanup',      'fallback': 'off'},
    'agent_llm':    {'label': 'Brief & proposal model',  'fallback': 'nim_nemotron'},
    'coverage_llm': {'label': 'Coverage check model',    'fallback': 'nim_nemotron'},
    'email':        {'label': 'Email delivery',          'fallback': 'console'},
    'client_match': {'label': 'Fathom auto-matching',    'fallback': 'exact'},
}

_DRIVERS = defaultdict(dict)


def register(cls):
    """Class decorator. The only step needed to add a driver."""
    _DRIVERS[cls.info.capability][cls.info.key] = cls
    return cls


def drivers_for(capability):
    return dict(_DRIVERS.get(capability, {}))


def get_driver_class(capability, key):
    return _DRIVERS.get(capability, {}).get(key)


# --- runtime settings cache -------------------------------------------------
# get() runs on nearly every request that touches an agent; a database round
# trip per call is not acceptable. Cached behind a short TTL and invalidated
# explicitly whenever a setting is written, so a UI change still takes effect on
# the very next request rather than up to TTL seconds later.
_CACHE_TTL_SECONDS = 30
_cache = {'at': 0.0, 'settings': {}}
_cache_lock = threading.Lock()


def invalidate_cache():
    with _cache_lock:
        _cache['at'] = 0.0
        _cache['settings'] = {}


def _runtime_settings():
    now = time.monotonic()
    with _cache_lock:
        if _cache['settings'] and (now - _cache['at']) < _CACHE_TTL_SECONDS:
            return _cache['settings']

    # Imported here, not at module scope: registry.py is imported by driver
    # modules, and pulling the ORM in at import time would make the provider
    # package depend on database bootstrapping order.
    from database import db_session
    from models import RuntimeSetting

    settings = {}
    try:
        for row in db_session.query(RuntimeSetting).all():
            try:
                options = json.loads(row.options) if row.options else {}
            except (ValueError, TypeError):
                options = {}
            settings[row.capability] = {'driver_key': row.driver_key, 'options': options}
    except Exception as e:  # a missing table (fresh DB, pre-migration) must not break resolution
        log.warning("runtime settings unavailable, using env defaults: %s", e)
        return {}

    with _cache_lock:
        _cache['settings'] = settings
        _cache['at'] = now
    return settings


def current_selection(capability):
    """What get() would pick right now, and where that choice came from — the
    'source' is what ProviderSettings shows so a user can tell a deliberate
    runtime choice from an env default."""
    settings = _runtime_settings()
    if capability in settings:
        return settings[capability]['driver_key'], 'runtime'
    env_default = Config.DEFAULT_DRIVERS.get(capability)
    if env_default:
        return env_default, 'env'
    return CAPABILITIES[capability]['fallback'], 'fallback'


def runtime_options(capability):
    return _runtime_settings().get(capability, {}).get('options', {})


def get(capability, override=None, options=None):
    """Resolve and instantiate the driver for `capability`.

    Never raises for a missing or unavailable driver — it logs and falls back,
    because every caller is on a path where a hard failure would be worse than a
    degraded engine.
    """
    if capability not in CAPABILITIES:
        raise KeyError(f"Unknown capability: {capability!r}")

    key = override or current_selection(capability)[0]
    cls = get_driver_class(capability, key)

    if cls is None:
        log.warning("driver %s/%s is not registered; falling back to %s",
                    capability, key, CAPABILITIES[capability]['fallback'])
    elif not cls.available():
        log.warning("driver %s/%s unavailable (missing %s); falling back to %s",
                    capability, key, ', '.join(cls.missing_env()),
                    CAPABILITIES[capability]['fallback'])
        cls = None

    if cls is None:
        fallback_key = CAPABILITIES[capability]['fallback']
        cls = get_driver_class(capability, fallback_key)
        if cls is None:
            raise RuntimeError(
                f"No driver available for {capability!r}: neither {key!r} nor the "
                f"fallback {fallback_key!r} is registered."
            )
        options = None  # the requested options belong to a different driver

    return cls(options if options is not None else runtime_options(capability))


def load_drivers():
    """Import every driver module so its @register decorator runs. Called once
    from app.py at startup; safe to call repeatedly."""
    from providers import client_match, email, llm, stt  # noqa: F401
