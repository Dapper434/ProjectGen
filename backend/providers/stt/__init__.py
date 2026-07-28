"""Speech-to-text drivers. Importing the package registers all of them."""
from providers.stt import browser_webspeech, off, whisper_api, wispr  # noqa: F401
