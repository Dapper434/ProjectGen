"""Groq — cloud inference, very fast, generous free tier.

Registered against agent_llm, coverage_llm and polish. OpenAI-compatible route
shape, so this is structurally the same driver as the others with a different
base URL and key.
"""
import time

import requests

from config import Config
from providers.base import DriverInfo, LLMDriver
from providers.registry import register

GROQ_BASE_URL = 'https://api.groq.com/openai/v1'
_MAX_TOKENS = {"off": 4096, "low": 8192, "full": 16384}


class _GroqBase(LLMDriver):
    def _model(self):
        return self.options.get('model') or Config.GROQ_LLM_MODEL

    def complete(self, system_prompt, user_prompt, reasoning='full', timeout=120):
        resp = requests.post(
            f"{GROQ_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {Config.GROQ_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": self._model(),
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": self.options.get('temperature', 0.7),
                "max_tokens": _MAX_TOKENS.get(reasoning, 8192),
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        return data['choices'][0]['message']['content'], (data.get('usage') or {})

    def health(self):
        if not self.available():
            return {"ok": False, "detail": "GROQ_API_KEY not set", "latency_ms": None}
        started = time.monotonic()
        try:
            resp = requests.get(f"{GROQ_BASE_URL}/models",
                                headers={"Authorization": f"Bearer {Config.GROQ_API_KEY}"}, timeout=5)
            latency = int((time.monotonic() - started) * 1000)
            if resp.status_code >= 400:
                return {"ok": False, "detail": f"HTTP {resp.status_code}", "latency_ms": latency}
            return {"ok": True, "detail": f"Reachable · {self._model()}", "latency_ms": latency}
        except Exception as e:
            return {"ok": False, "detail": str(e)[:120],
                    "latency_ms": int((time.monotonic() - started) * 1000)}


_SCHEMA = {
    'model': {'type': 'string', 'default': None, 'label': 'Model (blank = GROQ_LLM_MODEL)'},
    'temperature': {'type': 'number', 'default': 0.7, 'label': 'Temperature'},
}


@register
class GroqAgent(_GroqBase):
    info = DriverInfo(key='groq_llm', capability='agent_llm', label='Groq (cloud, fast)',
                      blurb='Very fast cloud inference with a generous free tier. Weaker reasoning than Nemotron.',
                      is_local=False, requires_env=('GROQ_API_KEY',),
                      cost_hint='Free tier available; metered above it',
                      rate_per_mtok=(0.59, 0.79), options_schema=_SCHEMA)


@register
class GroqCoverage(_GroqBase):
    info = DriverInfo(key='groq_llm', capability='coverage_llm', label='Groq (cloud, fast)',
                      blurb='Fast enough for a 90-second coverage loop without a local GPU.',
                      is_local=False, requires_env=('GROQ_API_KEY',),
                      cost_hint='Free tier available; metered above it',
                      rate_per_mtok=(0.59, 0.79), options_schema=_SCHEMA)


@register
class GroqPolish(_GroqBase):
    info = DriverInfo(key='groq_llm', capability='polish', label='Groq (cloud, fast)',
                      blurb='Cloud transcript cleanup — quick, but sends the transcript off-site.',
                      is_local=False, requires_env=('GROQ_API_KEY',),
                      cost_hint='Free tier available; metered above it',
                      rate_per_mtok=(0.59, 0.79), options_schema=_SCHEMA)
