"""Deterministic production staffing — Part 2 of the FactoryOS pipeline.

When a client accepts an approved proposal, this module assembles the production
plan: which talents from the seeded pool fill the proposal's team_shape roles,
what tools/equipment the scoped deliverables call for, and the kickoff checklist.

Deliberately NOT an LLM call. Matching is transparent keyword/skill scoring
against the Talent table, so the result is instant, explainable (every pick
carries match_reasons), and identical on every run — exactly what a live demo
needs. The scoring is simple on purpose; swapping this for an embedding or
LLM-ranked matcher later only means replacing build_staffing_plan()'s internals.
"""
import re
from datetime import datetime

# Generic words that carry no signal when comparing a role name to a talent's
# title ('Senior Video Producer' should match the role 'Video Producer').
STOPWORDS = {'a', 'an', 'the', 'and', 'of', 'for', 'with', 'to', 'in', 'on',
             'senior', 'junior', 'lead', 'head', 'chief', 'assistant'}

# Near-synonyms between how proposals name roles and how talents title themselves.
ROLE_SYNONYMS = {
    'project': {'producer', 'production', 'account'},
    'manager': {'producer', 'director', 'coordinator'},
    'producer': {'production', 'project', 'manager'},
    'video': {'videographer', 'film', 'camera', 'cinematographer'},
    'videographer': {'video', 'camera'},
    'designer': {'design'},
    'design': {'designer'},
    'strategist': {'strategy'},
    'strategy': {'strategist'},
    'editor': {'editing', 'edit', 'post'},
    'writer': {'copywriter', 'copy'},
    'copywriter': {'writer'},
    'photographer': {'photography', 'photo'},
    'animator': {'animation', 'motion'},
    'audio': {'sound'},
    'sound': {'audio'},
}

# (trigger keywords in deliverables/approach text, category, items, why)
TOOL_RULES = [
    ({'video', 'videos', 'film', 'testimonial', 'testimonials', 'documentary',
      'shoot', 'tvc', 'interview', 'interviews'},
     'Camera & Video',
     ['Sony FX6 cinema camera kit', 'Aputure lighting kit', 'Wireless lav microphones', 'Gimbal & tripod set'],
     'Video deliverables in scope'),
    ({'video', 'videos', 'edit', 'editing', 'animation', 'motion', 'explainer'},
     'Post-Production',
     ['Adobe Premiere Pro', 'DaVinci Resolve grading suite', 'After Effects'],
     'Edit and finishing work required'),
    ({'event', 'events', 'launch', 'townhall', 'townhalls', 'activation',
      'hybrid', 'stage', 'ceremony'},
     'Event Production',
     ['PA & AV system', 'LED screen wall', 'Stage & rigging', 'Livestream encoder rig'],
     'Event / activation deliverables in scope'),
    ({'design', 'toolkit', 'toolkits', 'poster', 'posters', 'brand', 'branding',
      'guidelines', 'deck', 'print', 'canva', 'pdf'},
     'Design & Print',
     ['Adobe Creative Cloud', 'Figma workspace', 'Canva Pro workspace', 'Print vendor slot (large format)'],
     'Design / print deliverables in scope'),
    ({'photo', 'photos', 'photography', 'stills'},
     'Photography',
     ['Full-frame stills kit', 'Portable strobe lighting', 'Lightroom catalogue'],
     'Photography deliverables in scope'),
    ({'social', 'influencer', 'influencers', 'creator', 'creators', 'campaign', 'content'},
     'Social & Campaign',
     ['Meta Business Suite', 'Content calendar (Notion)', 'CapCut Pro', 'Influencer contracting templates'],
     'Social / campaign deliverables in scope'),
    ({'radio', 'audio', 'podcast', 'voiceover', 'jingle'},
     'Audio',
     ['Recording studio day hire', 'Podcast rig (Rode)', 'Voiceover talent roster'],
     'Audio deliverables in scope'),
]

# Every production gets these regardless of scope.
BASELINE_TOOLS = ('Production Ops',
                  ['Slack project channel', 'Google Drive workspace', 'Trello production board',
                   'Call sheets & release forms'],
                  'Standard for every production')

# When a proposal somehow has no team_shape, staff a sensible minimum crew.
DEFAULT_ROLES = ['Project Manager', 'Creative Director']


def _tokens(text):
    return [t for t in re.split(r'[^a-z0-9]+', (text or '').lower()) if t and t not in STOPWORDS]


def _title_match(role_tokens, talent):
    """Share of the role's words that appear in (or are synonyms of) the talent's title."""
    if not role_tokens:
        return 0.0
    title_tokens = set(_tokens(talent.title))
    hits = sum(
        1 for rt in role_tokens
        if rt in title_tokens or (ROLE_SYNONYMS.get(rt, set()) & title_tokens)
    )
    return hits / len(role_tokens)


def _skill_hits(talent, context_tokens):
    """Talent skills whose wording overlaps the proposal's deliverables/approach."""
    hits = []
    for skill in (talent.skills or []):
        if any(tok in context_tokens for tok in _tokens(skill)):
            hits.append(skill)
    return hits


def _score_talent(talent, role_tokens, context_tokens):
    title = _title_match(role_tokens, talent)
    if title == 0:
        return None  # wrong discipline entirely — better unfilled than a bogus assignment

    skills = _skill_hits(talent, context_tokens)
    available = talent.availability == 'available'

    score = round(60 * title + 28 * min(len(skills), 4) / 4 + 12 * (1.0 if available else 0.25))

    reasons = []
    if title >= 1.0:
        reasons.append(f"Title is an exact fit ({talent.title})")
    else:
        reasons.append(f"Title closely matches ({talent.title})")
    if skills:
        reasons.append("Skills matching this scope: " + ", ".join(skills[:3]))
    if available:
        reasons.append("Available to start now")
    elif talent.available_from:
        reasons.append(f"On another project — free from {talent.available_from}")
    if talent.years_experience:
        reasons.append(f"{talent.years_experience} yrs experience")

    return {"score": score, "skills": skills, "reasons": reasons}


def _talent_json(talent):
    return {
        "id": talent.id,
        "name": talent.name,
        "title": talent.title,
        "day_rate_kes": talent.day_rate_kes,
        "availability": talent.availability,
        "available_from": talent.available_from,
        "location": talent.location,
        "years_experience": talent.years_experience,
        "highlight": talent.highlight,
    }


def _match_tools(context_tokens):
    tools = []
    for keywords, category, items, reason in TOOL_RULES:
        if keywords & context_tokens:
            tools.append({"category": category, "items": items, "reason": reason})
    category_names = {t["category"] for t in tools}
    if BASELINE_TOOLS[0] not in category_names:
        tools.append({"category": BASELINE_TOOLS[0], "items": BASELINE_TOOLS[1], "reason": BASELINE_TOOLS[2]})
    return tools


def _kickoff_checklist(client_name, has_unfilled):
    items = [
        {"item": f"Send contract & statement of work to {client_name} for signature", "owner": "Account Manager"},
        {"item": "Raise mobilisation invoice (60% deposit)", "owner": "Finance"},
        {"item": "Confirm crew dates & issue booking notes", "owner": "Producer"},
        {"item": "Reserve equipment & studio slots", "owner": "Production Ops"},
        {"item": f"Open shared drive & comms channel with {client_name}", "owner": "Account Manager"},
        {"item": "Schedule internal kickoff & crew briefing", "owner": "Producer"},
    ]
    if has_unfilled:
        items.insert(2, {"item": "Source external freelancer(s) for unfilled roles", "owner": "Producer"})
    return items


def build_staffing_plan(proposal, talents, client_name):
    """Assemble the full production plan dict stored on StaffingPlan.plan.

    Greedy one-talent-per-role assignment in team_shape order: each role gets the
    highest-scoring unassigned talent, ties broken by experience then id so the
    outcome never changes between runs.
    """
    data = proposal.structured_json or {}
    roles = [r for r in (data.get('team_shape') or []) if r] or DEFAULT_ROLES

    context_text = ' '.join(
        (data.get('scoped_deliverables') or [])
        + [data.get('approach') or '']
        + (data.get('phased_timeline') or [])
    )
    context_tokens = set(_tokens(context_text))

    team, unfilled, used_ids = [], [], set()
    for role in roles:
        role_tokens = _tokens(role)
        candidates = []
        for talent in talents:
            if talent.id in used_ids:
                continue
            result = _score_talent(talent, role_tokens, context_tokens)
            if result:
                candidates.append((result["score"], talent.years_experience or 0, -talent.id, talent, result))

        if not candidates:
            unfilled.append({
                "role": role,
                "note": "No match in the current talent pool — brief an external freelancer.",
            })
            continue

        candidates.sort(reverse=True)
        _, _, _, best, result = candidates[0]
        used_ids.add(best.id)
        team.append({
            "role": role,
            "talent": _talent_json(best),
            "match_score": min(result["score"], 98),  # never claim a perfect match
            "match_reasons": result["reasons"],
        })

    return {
        "generated_at": datetime.now().isoformat(),
        "source_proposal_version": proposal.version,
        "team": team,
        "unfilled": unfilled,
        "team_day_rate_kes": sum(m["talent"]["day_rate_kes"] or 0 for m in team),
        "tools": _match_tools(context_tokens),
        "kickoff_checklist": _kickoff_checklist(client_name, bool(unfilled)),
        "phases": data.get('phased_timeline') or [],
    }
