"""Single source of truth for environment configuration.

Replaces scattered `os.environ.get(...)` calls across the backend. Every
switchable capability gets its env-level default here — the bottom of the
resolution order described in the blueprint (§3.1): hardcoded fallback <
env default (this file) < runtime setting (WP-2) < per-request override.

Most of the keys below aren't consumed anywhere yet — they're the env-level
floor for capabilities landing in WP-2/4/6/9/12. Adding them now means each
of those WPs only has to read `Config.X`, never add another env lookup.
"""
import os


def _bool(key, default="false"):
    return os.environ.get(key, default).strip().lower() in ("1", "true", "yes", "on")


class Config:
    # --- core ---------------------------------------------------------
    # `or`, not `.get(key, default)` — a blank value in .env (e.g. `SECRET_KEY=`
    # left empty after copying .env.example) must fall back too, not become "".
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'super-secret-demo-key'
    DATABASE_URL = os.environ.get('DATABASE_URL') or 'sqlite:///factoryos.db'
    PRODUCTION = os.environ.get('PRODUCTION') == '1'
    APP_BASE_URL = os.environ.get('APP_BASE_URL', 'http://localhost:5173')
    UPLOAD_DIR = os.environ.get('UPLOAD_DIR', './var/uploads')

    # --- existing integrations (agents.py, fathom.py) -------------------
    NIM_API_KEY = os.environ.get('NIM_API_KEY')
    NIM_MODEL = os.environ.get('NIM_MODEL') or 'nvidia/nemotron-3-super-120b-a12b'
    NIM_BASE_URL = os.environ.get('NIM_BASE_URL', 'https://integrate.api.nvidia.com/v1')
    FATHOM_API_KEY = os.environ.get('FATHOM_API_KEY')
    FATHOM_WEBHOOK_SECRET = os.environ.get('FATHOM_WEBHOOK_SECRET')

    # --- model providers, not yet wired up (WP-2) ------------------------
    NIM_SMALL_MODEL = os.environ.get('NIM_SMALL_MODEL', '')
    GROQ_API_KEY = os.environ.get('GROQ_API_KEY')
    GROQ_LLM_MODEL = os.environ.get('GROQ_LLM_MODEL', 'llama-3.3-70b-versatile')
    OLLAMA_BASE_URL = os.environ.get('OLLAMA_BASE_URL', 'http://localhost:11434')
    OLLAMA_MODEL = os.environ.get('OLLAMA_MODEL', 'qwen2.5:7b-instruct')

    # --- speech, not yet wired up (WP-4) ----------------------------------
    GROQ_STT_MODEL = os.environ.get('GROQ_STT_MODEL', 'whisper-large-v3-turbo')
    WHISPER_BASE_URL = os.environ.get('WHISPER_BASE_URL', 'http://localhost:8001/v1')
    WHISPER_MODEL = os.environ.get('WHISPER_MODEL', 'Systran/faster-whisper-small')
    WISPRFLOW_API_KEY = os.environ.get('WISPRFLOW_API_KEY')
    STT_KEEP_AUDIO = _bool('STT_KEEP_AUDIO')
    STT_DAILY_SECONDS_PER_USER = int(os.environ.get('STT_DAILY_SECONDS_PER_USER', '7200'))

    # --- email, not yet wired up (WP-12) ----------------------------------
    SENDGRID_API_KEY = os.environ.get('SENDGRID_API_KEY')
    POSTMARK_TOKEN = os.environ.get('POSTMARK_SERVER_TOKEN')
    RESEND_API_KEY = os.environ.get('RESEND_API_KEY')
    EMAIL_FROM = os.environ.get('EMAIL_FROM', 'proposals@gdfkenya.com')

    # --- default driver per capability (WP-2's runtime settings override) --
    DEFAULT_DRIVERS = {
        'stt_live': os.environ.get('STT_LIVE_DRIVER', 'groq_chunked'),
        'stt_batch': os.environ.get('STT_BATCH_DRIVER', 'groq_batch'),
        'polish': os.environ.get('POLISH_DRIVER', 'ollama'),
        'agent_llm': os.environ.get('AGENT_LLM_DRIVER', 'nim_nemotron'),
        'coverage_llm': os.environ.get('COVERAGE_LLM_DRIVER', 'ollama'),
        'email': os.environ.get('EMAIL_DRIVER', 'console'),
        'client_match': os.environ.get('CLIENT_MATCH_DRIVER', 'eng_tag_then_fuzzy'),
    }

    # --- feature flags: all default false, enable one at a time -----------
    FLAGS = {
        'auth_data': _bool('FEATURE_AUTH_DATA'),
        'lab': _bool('FEATURE_LAB'),
        'voice': _bool('FEATURE_VOICE'),
        'recordings': _bool('FEATURE_RECORDINGS'),
        'boardroom': _bool('FEATURE_BOARDROOM'),
        'talent': _bool('FEATURE_TALENT'),
        'talent_portal': _bool('FEATURE_TALENT_PORTAL'),
        'email': _bool('FEATURE_EMAIL'),
    }
