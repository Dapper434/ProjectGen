"""Transcript cleanup — WP-4 §4.7.

Closes the gap between raw Whisper output and a transcript a producer would have
typed, at zero marginal cost on hardware the agency already owns.

Two rules that are not negotiable:

1. **Polish runs once over the whole transcript, never per chunk.** Per-chunk
   polishing destroys mid-sentence context, multiplies latency, and reads worse
   than the raw text.
2. **Cleanup never invents.** It removes filler and fixes spelling of known
   names; it does not summarise, infer, or add. The raw segments stay stored
   verbatim as the record — the polished version is a derived field alongside
   them, not a replacement.
"""
from providers import registry

DEFAULT_POLISH_PROMPT = """You are cleaning a raw speech-to-text transcript from a client meeting.

Rules:
- Remove filler words and false starts. Do not remove content.
- Fix obvious mis-transcriptions of these known names: {names}
- Add sentence punctuation and paragraph breaks.
- Label speakers as Speaker 1 / Speaker 2 only where turn changes are unambiguous.
- NEVER add, infer, summarise, or invent anything that was not said. If a passage
  is garbled, leave it as it is rather than guessing what was meant.

Return only the cleaned transcript, with no preamble or commentary."""


def polish(text, names=(), driver_override=None):
    """Returns (polished_text, provenance).

    Falls back to the raw text on any failure — a cleanup pass is a nice-to-have,
    and losing the transcript because the polish model was down would be absurd.
    """
    text = (text or '').strip()
    driver = registry.get('polish', override=driver_override)

    if driver.info.key == 'off' or not text:
        return text, {"driver": "off", "prompt": None}

    from authoritative import resolve as auth_resolve
    template, prompt_ref = auth_resolve('polish_prompt')
    if template is None:
        template = DEFAULT_POLISH_PROMPT

    system_prompt = template.replace('{names}', ', '.join(names) if names else 'none supplied')

    try:
        cleaned, _usage = driver.complete(system_prompt, text, reasoning='off')
    except Exception as e:
        return text, {"driver": driver.info.key, "prompt": prompt_ref,
                      "error": f"Polish failed, keeping the raw transcript: {str(e)[:150]}"}

    cleaned = (cleaned or '').strip()
    if not cleaned:
        return text, {"driver": driver.info.key, "prompt": prompt_ref,
                      "error": "Polish returned nothing; keeping the raw transcript."}

    return cleaned, {"driver": driver.info.key, "prompt": prompt_ref}
