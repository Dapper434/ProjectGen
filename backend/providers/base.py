"""Driver interface for every pluggable capability — WP-2 §2.1.

The contract that matters: **a driver that cannot run says so through
`available()` / `health()` and never raises at call time.** A missing
GROQ_API_KEY must degrade to another engine with a visible badge, not throw a
500 in the middle of a client meeting.

Capability-specific subclasses add the actual work method — `LLMDriver.complete()`,
`EmailDriver.send()`, `STTDriver.transcribe()`.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from config import Config


@dataclass
class DriverInfo:
    key: str                              # 'groq_llm'
    capability: str                       # 'agent_llm'
    label: str                            # 'Groq (cloud, fast)'
    blurb: str = ''                       # one sentence shown in the UI
    is_local: bool = False                # runs on our own hardware
    requires_env: tuple = ()              # ('GROQ_API_KEY',)
    cost_hint: str = ''                   # 'free tier: 2k req/day' | 'no marginal cost'
    options_schema: dict = field(default_factory=dict)
    # Rough $/1M tokens (input, output) for the Lab's cost estimate. Approximate
    # and always labelled as such in the UI — it exists to catch order-of-magnitude
    # differences between engines, not to bill anyone.
    rate_per_mtok: tuple = (0.0, 0.0)


class Driver(ABC):
    info: DriverInfo

    def __init__(self, options=None):
        self.options = {**self.defaults(), **(options or {})}

    @classmethod
    def defaults(cls):
        return {k: v.get('default') for k, v in (cls.info.options_schema or {}).items()}

    @abstractmethod
    def health(self):
        """{'ok': bool, 'detail': str, 'latency_ms': int|None}. Must never raise."""

    @classmethod
    def available(cls):
        """False when a required env var is missing, so the driver is neither
        selectable in the UI nor chosen by get()."""
        return all(getattr(Config, k, None) for k in cls.info.requires_env)

    @classmethod
    def missing_env(cls):
        return [k for k in cls.info.requires_env if not getattr(Config, k, None)]


class LLMDriver(Driver):
    @abstractmethod
    def complete(self, system_prompt, user_prompt, reasoning='full', timeout=120):
        """Returns (content: str, usage: dict). `usage` carries at least
        prompt_tokens / completion_tokens / total_tokens where the provider
        reports them."""


class EmailDriver(Driver):
    @abstractmethod
    def send(self, to, subject, body_html, body_text=None, attachments=None):
        """Returns {'ok': bool, 'detail': str, 'provider_id': str|None}."""


class STTDriver(Driver):
    @abstractmethod
    def transcribe(self, audio_path, language=None, timeout=300):
        """Returns {'text': str, 'segments': list|None, 'duration_s': float|None}."""


class ClientMatchDriver(Driver):
    @abstractmethod
    def match(self, title, clients, cfg):
        """The single Client this meeting title unambiguously names, or None.
        Zero or several candidates must return None — ambiguity always falls
        through to a human in the Inbox."""
