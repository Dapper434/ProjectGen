"""NVIDIA NIM (Nemotron) — the incumbent engine for briefs and proposals.

Carries the reasoning-effort presets that used to live in agents.py. Nemotron
exposes a vLLM-native `chat_template_kwargs` field (a real top-level field on
NIM's OpenAI-compatible endpoint, not an SDK `extra_body` wrapper) controlling
how much of the token budget is spent thinking before the final answer:

  off  — no reasoning tokens. Fastest; right for pure extraction (read a
         transcript, fill in known fields).
  low  — light reasoning, for judgment/arithmetic (pricing against a rate card,
         merging conflicting signals) without paying for full deliberation.
  full — reserved as an escalation path when a fast attempt fails validation,
         not the default for every call.

NVIDIA recommends temperature=1.0 / top_p=0.95 for this model at every reasoning
level.
"""
import time

import requests

from config import Config
from providers.base import DriverInfo, LLMDriver
from providers.registry import register

REASONING_PRESETS = {
    "off":  {"chat_template_kwargs": {"enable_thinking": False}, "max_tokens": 4096},
    "low":  {"chat_template_kwargs": {"enable_thinking": True, "low_effort": True}, "max_tokens": 8192},
    "full": {"chat_template_kwargs": {"enable_thinking": True}, "max_tokens": 16384},
}


class _NimBase(LLMDriver):
    model_attr = 'NIM_MODEL'

    def _model(self):
        return self.options.get('model') or getattr(Config, self.model_attr) or Config.NIM_MODEL

    def complete(self, system_prompt, user_prompt, reasoning='full', timeout=120):
        preset = REASONING_PRESETS.get(reasoning, REASONING_PRESETS['full'])
        resp = requests.post(
            f"{Config.NIM_BASE_URL.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {Config.NIM_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": self._model(),
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": self.options.get('temperature', 1.0),
                "top_p": self.options.get('top_p', 0.95),
                "max_tokens": preset["max_tokens"],
                "chat_template_kwargs": preset["chat_template_kwargs"],
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        return data['choices'][0]['message']['content'], (data.get('usage') or {})

    def health(self):
        if not self.available():
            return {"ok": False, "detail": f"{', '.join(self.missing_env())} not set", "latency_ms": None}
        started = time.monotonic()
        try:
            resp = requests.get(
                f"{Config.NIM_BASE_URL.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {Config.NIM_API_KEY}"},
                timeout=5,
            )
            latency = int((time.monotonic() - started) * 1000)
            if resp.status_code >= 400:
                return {"ok": False, "detail": f"HTTP {resp.status_code}", "latency_ms": latency}
            return {"ok": True, "detail": f"Reachable · {self._model()}", "latency_ms": latency}
        except Exception as e:
            return {"ok": False, "detail": str(e)[:120], "latency_ms": int((time.monotonic() - started) * 1000)}


@register
class NimNemotron(_NimBase):
    model_attr = 'NIM_MODEL'
    info = DriverInfo(
        key='nim_nemotron', capability='agent_llm', label='NVIDIA NIM · Nemotron',
        blurb='The reasoning model this system was built on. Highest quality, highest latency.',
        is_local=False, requires_env=('NIM_API_KEY',),
        cost_hint='Metered per token on your NVIDIA account',
        rate_per_mtok=(0.60, 0.60),
        options_schema={
            'model': {'type': 'string', 'default': None, 'label': 'Model override (blank = NIM_MODEL)'},
            'temperature': {'type': 'number', 'default': 1.0, 'label': 'Temperature'},
        },
    )


@register
class NimNemotronCoverage(_NimBase):
    """Same engine registered against coverage_llm — the boardroom's coverage
    check runs every 90s, so it gets its own switch and can be pointed at a
    cheaper model without touching brief/proposal generation."""
    model_attr = 'NIM_MODEL'
    info = DriverInfo(
        key='nim_nemotron', capability='coverage_llm', label='NVIDIA NIM · Nemotron',
        blurb='Same model as brief generation. Accurate but expensive to run every 90 seconds.',
        is_local=False, requires_env=('NIM_API_KEY',),
        cost_hint='Metered per token on your NVIDIA account',
        rate_per_mtok=(0.60, 0.60),
        options_schema={'model': {'type': 'string', 'default': None, 'label': 'Model override'}},
    )


@register
class NimSmall(_NimBase):
    model_attr = 'NIM_SMALL_MODEL'
    info = DriverInfo(
        key='nim_small', capability='coverage_llm', label='NVIDIA NIM · small model',
        blurb='A cheaper NIM model for high-frequency coverage checks. Set NIM_SMALL_MODEL.',
        is_local=False, requires_env=('NIM_API_KEY', 'NIM_SMALL_MODEL'),
        cost_hint='Cheaper per token than Nemotron',
        rate_per_mtok=(0.10, 0.10),
        options_schema={'model': {'type': 'string', 'default': None, 'label': 'Model override'}},
    )
