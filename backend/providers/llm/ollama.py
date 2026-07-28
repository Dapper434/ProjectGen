"""Ollama — a local model, free per run and private.

Registered against agent_llm, coverage_llm and polish. Ollama is the *text*
stage only: it has no ASR runtime, so it can never serve stt_* (see the
blueprint's WP-4 §4.1 correction).

Uses Ollama's OpenAI-compatible /v1/chat/completions route rather than the
native /api/chat so the request shape matches every other LLM driver here.
"""
import time

import requests

from config import Config
from providers.base import DriverInfo, LLMDriver
from providers.registry import register

_MAX_TOKENS = {"off": 4096, "low": 8192, "full": 16384}


class _OllamaBase(LLMDriver):
    def _model(self):
        return self.options.get('model') or Config.OLLAMA_MODEL

    def complete(self, system_prompt, user_prompt, reasoning='full', timeout=300):
        # Local generation on CPU is slow; the default timeout is deliberately
        # far higher than the cloud drivers'.
        resp = requests.post(
            f"{Config.OLLAMA_BASE_URL.rstrip('/')}/v1/chat/completions",
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
        started = time.monotonic()
        try:
            resp = requests.get(f"{Config.OLLAMA_BASE_URL.rstrip('/')}/api/tags", timeout=3)
            latency = int((time.monotonic() - started) * 1000)
            if resp.status_code >= 400:
                return {"ok": False, "detail": f"HTTP {resp.status_code}", "latency_ms": latency}
            names = [m.get('name', '') for m in (resp.json().get('models') or [])]
            want = self._model()
            if want and not any(n == want or n.startswith(f"{want}:") for n in names):
                return {"ok": False,
                        "detail": f"Server up but '{want}' not pulled. Run: ollama pull {want}",
                        "latency_ms": latency}
            return {"ok": True, "detail": f"Reachable · {want}", "latency_ms": latency}
        except Exception as e:
            return {"ok": False,
                    "detail": f"Not reachable at {Config.OLLAMA_BASE_URL} ({str(e)[:70]})",
                    "latency_ms": int((time.monotonic() - started) * 1000)}


_SCHEMA = {
    'model': {'type': 'string', 'default': None, 'label': 'Model (blank = OLLAMA_MODEL)'},
    'temperature': {'type': 'number', 'default': 0.7, 'label': 'Temperature'},
}
_BLURB = 'Runs on your own hardware. No marginal cost, nothing leaves the building, slower than cloud.'


@register
class OllamaAgent(_OllamaBase):
    info = DriverInfo(key='ollama', capability='agent_llm', label='Ollama (local)',
                      blurb=_BLURB, is_local=True, cost_hint='No marginal cost',
                      options_schema=_SCHEMA)


@register
class OllamaCoverage(_OllamaBase):
    info = DriverInfo(key='ollama', capability='coverage_llm', label='Ollama (local)',
                      blurb='Ideal for coverage checks: they run every 90 seconds and this costs nothing per run.',
                      is_local=True, cost_hint='No marginal cost', options_schema=_SCHEMA)


@register
class OllamaPolish(_OllamaBase):
    info = DriverInfo(key='ollama', capability='polish', label='Ollama (local)',
                      blurb='Cleans up raw transcripts locally — filler removal and spelling, never rewriting.',
                      is_local=True, cost_hint='No marginal cost', options_schema=_SCHEMA)
