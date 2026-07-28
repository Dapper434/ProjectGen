"""How aggressively an inbound Fathom meeting auto-attaches to a client (WP-8).

Every driver here obeys one rule: **zero or several candidates always return
None.** Fuzziness widens what counts as a confident match; it must never turn an
ambiguous case into a confident auto-attach. Attaching a transcript to the wrong
client is the one failure mode worse than a human clicking Attach.
"""
from difflib import SequenceMatcher

from providers.base import ClientMatchDriver, DriverInfo
from providers.registry import register


def _eligible(clients, cfg):
    min_len = cfg.get('min_client_name_length', 3)
    return [c for c in clients if c.name and len(c.name) >= min_len]


def _exact_match(title, clients, cfg):
    """Literal substring — the strongest signal there is, and the behaviour that
    existed before WP-8. Tried first by every driver except `exact` itself,
    because a ratio computed across a whole long title can score a title that
    literally contains the client name *below* threshold."""
    title_lower = (title or '').lower()
    hits = [c for c in _eligible(clients, cfg) if c.name.lower() in title_lower]
    return hits[0] if len(hits) == 1 else None, len(hits)


def _best_window_ratio(name, title_lower):
    """Score a client name against the best-matching window of the title rather
    than the whole string, so one short name inside a long title still scores
    high."""
    ratios = [SequenceMatcher(None, name, title_lower).ratio()]
    span = len(name)
    for i in range(max(1, len(title_lower) - span + 1)):
        ratios.append(SequenceMatcher(None, name, title_lower[i:i + span]).ratio())
    return max(ratios)


@register
class ExactMatch(ClientMatchDriver):
    info = DriverInfo(
        key='exact', capability='client_match', label='Exact name only',
        blurb='Auto-attach only when the client name appears literally in the meeting title. Most conservative.',
        is_local=True, cost_hint='Free',
    )

    def match(self, title, clients, cfg):
        if not title:
            return None
        return _exact_match(title, clients, cfg)[0]

    def health(self):
        return {"ok": True, "detail": "Pure function — always available.", "latency_ms": 0}


@register
class FuzzyDifflib(ClientMatchDriver):
    info = DriverInfo(
        key='fuzzy_difflib', capability='client_match', label='Fuzzy name matching',
        blurb='Catches typos and near-misses in the meeting title. Threshold is tunable in Authoritative Data.',
        is_local=True, cost_hint='Free',
    )

    def match(self, title, clients, cfg):
        if not title:
            return None
        exact, exact_count = _exact_match(title, clients, cfg)
        if exact:
            return exact
        if exact_count > 1:
            return None  # ambiguous on an exact reading; fuzzy cannot make it less so

        title_lower = title.lower()
        threshold = cfg.get('fuzzy_threshold', 0.75)
        scored = [
            c for c in _eligible(clients, cfg)
            if _best_window_ratio(c.name.lower(), title_lower) > threshold
        ]
        return scored[0] if len(scored) == 1 else None

    def health(self):
        return {"ok": True, "detail": "Pure function — always available.", "latency_ms": 0}


@register
class EngTagThenFuzzy(FuzzyDifflib):
    """Identical matching to fuzzy_difflib. The `[ENG-0042]` tag it is named for
    is checked in the webhook *before* any client matching runs (it resolves to a
    specific engagement, not a client), so this driver differs only in labelling
    — it documents that the tag path is active."""
    info = DriverInfo(
        key='eng_tag_then_fuzzy', capability='client_match', label='[ENG-XXXX] tag, then fuzzy',
        blurb='Honour an explicit engagement tag in the title first, then fall back to fuzzy name matching. Recommended.',
        is_local=True, cost_hint='Free',
    )
