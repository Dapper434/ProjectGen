"""Casting Agent — WP-10.

**The model does not pick the talent.** A deterministic scoring function produces
the ranked shortlist; the model only writes the human-readable rationale. Scoring
has to be reproducible, testable, and explainable to a talent who was *not*
chosen — an LLM is none of those things. It is very good at "here is why this
line-up hangs together and here is what worries me about it."
"""
from database import db_session
from models import Assignment, Talent, TalentSkill, Skill

DEFAULT_CASTING_POLICY = {
    "weights": {"tokens": 0.35, "skill_match": 0.30, "rating": 0.15, "inhouse": 0.10, "rate_fit": 0.10},
    "shortlist_size": 3,
    "inhouse_first": True,
    "require_human_approval": True,
    "offer_expiry_hours": 48,
    "max_concurrent_assignments_per_talent": 2,
}


def policy(engagement=None):
    from authoritative import resolve as auth_resolve
    body, prov = auth_resolve('casting_policy', engagement=engagement)
    if body is None:
        return DEFAULT_CASTING_POLICY, {"key": "casting_policy", "scope": "legacy_constant", "version": 0}
    return body, prov


def _norm(value, low, high):
    if high is None or low is None or high <= low:
        return 0.0
    return max(0.0, min(1.0, (value - low) / (high - low)))


def talent_skill_names(talent):
    rows = (db_session.query(Skill.name, TalentSkill.level, TalentSkill.verified_by_enrollment_id)
            .join(TalentSkill, TalentSkill.skill_id == Skill.id)
            .filter(TalentSkill.talent_id == talent.id).all())
    out = {}
    for name, level, verified in rows:
        out[name.lower()] = {"level": level or 3, "verified": verified is not None}
    # The pre-WP-9 free-text skills list still counts, unverified.
    for phrase in (talent.skills or []):
        out.setdefault(str(phrase).lower(), {"level": 3, "verified": False})
    return out


def skill_match_ratio(talent, role):
    """Verified skills weigh more than claimed ones — that distinction is the
    entire point of certification enrollment."""
    required = [s.lower() for s in (role.get('required_skills') or [])]
    if not required:
        return 0.5   # no stated requirement: neutral, neither reward nor punish
    have = talent_skill_names(talent)
    total = 0.0
    title_words = _tokens(talent.title)
    for want in required:
        hit = next((v for k, v in have.items() if want in k or k in want), None)
        if hit:
            total += 1.0 if hit['verified'] else 0.7
        elif _tokens(want) & title_words:
            # Title-only evidence is weaker than a recorded skill, and much
            # weaker than a certified one.
            total += 0.5
    return min(1.0, total / len(required))


def _tokens(text):
    return {w for w in ''.join(c.lower() if c.isalnum() else ' ' for c in (text or '')).split()
            if len(w) > 2 and w not in ('the', 'and', 'for', 'team', 'senior', 'junior', 'lead')}


def matches_role(talent, role):
    """Does this talent plausibly fill this role at all?

    Role labels coming out of a proposal's `team_shape` are **job titles**
    ("Account Director", "Video Production Team"), not skill names. Matching them
    only against the skill table eliminates almost everyone — so the talent's own
    `title` is checked as well, which is the same title-matching staffing.py has
    always done and the prior art the blueprint pointed at.
    """
    required = role.get('required_skills') or []
    label = role.get('label') or ''
    if not required and not label:
        return True

    have = talent_skill_names(talent)
    for want in required:
        w = want.lower()
        if any(w in k or k in w for k in have):
            return True

    # Title overlap: "Video Producer" fills "Video Production Team".
    role_words = _tokens(label) | {w for r in required for w in _tokens(r)}
    title_words = _tokens(talent.title)
    if role_words & title_words:
        return True
    # A word from the role appearing in a skill phrase also counts.
    return any(role_words & _tokens(k) for k in have)


def has_required_skills(talent, required):
    """Kept for callers that only have a bare skill list."""
    return matches_role(talent, {"required_skills": required, "label": ""})


def active_assignment_count(talent_id):
    return db_session.query(Assignment).filter(
        Assignment.talent_id == talent_id,
        Assignment.status.in_(('offered', 'accepted')),
    ).count()


def score_pool(role, candidates, pol):
    """Hard filters eliminate; they never merely penalise. An unavailable or
    unqualified talent must not appear at all, rather than appearing with a low
    score that a hurried producer might still click."""
    import tokens as tokens_mod
    from availability import is_available

    max_concurrent = pol.get('max_concurrent_assignments_per_talent', 2)
    start, end = role.get('start_at'), role.get('end_at')
    max_rate = role.get('max_day_rate_kes') or 10 ** 9

    eligible = []
    for t in candidates:
        if (t.status or 'active') != 'active' or not t.is_active:
            continue
        if not matches_role(t, role):
            continue
        if not is_available(t.id, start, end)[0]:
            continue
        if (t.day_rate_kes or 0) > max_rate:
            continue
        if active_assignment_count(t.id) >= max_concurrent:
            continue
        eligible.append(t)

    if not eligible:
        return []

    balances = {t.id: tokens_mod.balance(t) for t in eligible}
    totals = [balances[t.id]['total'] for t in eligible]
    rates = [t.day_rate_kes or 0 for t in eligible]
    lo_tok, hi_tok = min(totals), max(totals)
    lo_rate, hi_rate = min(rates), max(rates)

    weights = pol.get('weights', DEFAULT_CASTING_POLICY['weights'])
    scored = []
    for t in eligible:
        components = {
            "tokens": _norm(balances[t.id]['total'], lo_tok, hi_tok) if hi_tok > lo_tok else 1.0,
            "skill_match": skill_match_ratio(t, role),
            "rating": _norm(t.avg_rating if t.avg_rating is not None else 3.0, 1, 5),
            "inhouse": 1.0 if t.engagement_type == 'inhouse' else 0.0,
            "rate_fit": 1.0 - (_norm(t.day_rate_kes or 0, lo_rate, hi_rate) if hi_rate > lo_rate else 0.0),
        }
        # Round the contributions first, then sum them into the score — not the
        # other way round. The `why` breakdown has to *account for* the number
        # shown next to it: an Account Manager explaining a ranking to a producer
        # cannot have the parts fail to add up to the whole.
        why = [{"component": k, "raw": round(components[k], 6), "weight": weights.get(k, 0),
                "contribution": round(weights.get(k, 0) * components[k], 6)} for k in weights]
        score = sum(w['contribution'] for w in why)
        scored.append({
            "talent": t, "score": round(score, 6), "why": why,
            "tokens": balances[t.id]['total'], "idle_days": balances[t.id]['idle_days'],
        })

    # Deterministic tie-break through all five levels: score → tokens → idle
    # days → lower rate → id. Identical inputs must always give identical order.
    scored.sort(key=lambda e: (-e['score'], -e['tokens'], -e['idle_days'],
                               e['talent'].day_rate_kes or 0, e['talent'].id))

    if pol.get('inhouse_first'):
        # A pre-sort, not a weight bump: the agency pays in-house staff anyway, so
        # benching them while paying a contractor is a straight loss. Kept
        # separate from the weights so the policy decision stays visible.
        scored.sort(key=lambda e: 0 if e['talent'].engagement_type == 'inhouse' else 1)

    return scored


def serialise(entry):
    t = entry['talent']
    return {
        "talent_id": t.id, "name": t.name, "title": t.title,
        "engagement_type": t.engagement_type, "seniority": t.seniority,
        "day_rate_kes": t.day_rate_kes, "location": t.location,
        "avg_rating": t.avg_rating, "highlight": t.highlight,
        "score": entry['score'], "why": entry['why'],
        "tokens": entry['tokens'], "idle_days": entry['idle_days'],
    }


def flag_concerns(role, shortlist):
    """Cheap, deterministic checks worth surfacing without a model call."""
    concerns = []
    if not shortlist:
        concerns.append("No eligible talent for this role — widen the dates, the rate, or the skills.")
        return concerns
    if all(e['talent'].engagement_type != 'inhouse' for e in shortlist):
        concerns.append("Everyone shortlisted is on contract — no in-house cover for this role.")
    if len(shortlist) < 2:
        concerns.append("Only one eligible candidate — there is no fallback if they decline.")
    if all((e['talent'].avg_rating or 0) == 0 for e in shortlist):
        concerns.append("None of these have a completed-assignment rating yet.")
    return concerns


def extract_roles_from_brief(engagement):
    """Read required roles out of the Production Brief.

    When the brief is thin this returns what it found and marks the rest
    `needs_input` rather than inventing roles — an invented role produces a
    confidently wrong shortlist, which is worse than an empty one.
    """
    from models import Brief, Proposal

    brief = (db_session.query(Brief).filter_by(engagement_id=engagement.id)
             .order_by(Brief.id.desc()).first())
    proposal = (db_session.query(Proposal).filter_by(engagement_id=engagement.id)
                .order_by(Proposal.id.desc()).first())

    team_shape = ((proposal.structured_json or {}).get('team_shape') if proposal else None) or []
    if not team_shape and brief:
        team_shape = (brief.structured_json or {}).get('key_stakeholders') or []

    roles = []
    for label in team_shape:
        label = str(label).strip()
        if not label:
            continue
        roles.append({
            "key": label.lower().replace(' ', '_')[:60],
            "label": label,
            "required_skills": [label],
            "start_at": None, "end_at": None,
        })

    if not roles:
        return [], "needs_input"
    return roles, "ok"


def narrate(role, shortlist, engagement):
    """The model's only job here: prose from numbers it did not choose."""
    if not shortlist:
        return None
    from providers import registry

    lines = [
        f"{i + 1}. {e['talent'].name} — {e['talent'].title or 'unspecified'}, "
        f"{e['talent'].engagement_type}, KES {e['talent'].day_rate_kes or 0}/day, "
        f"{e['tokens']} tokens, idle {e['idle_days']}d, score {e['score']:.3f}"
        for i, e in enumerate(shortlist)
    ]
    system = (
        "You are a casting assistant for a creative agency. You are given a role and an ALREADY-RANKED "
        "shortlist produced by a deterministic scoring function. You did NOT choose these people and you "
        "must not re-rank them.\n\n"
        "Write two or three sentences explaining why this line-up makes sense for the role, referring only "
        "to the facts given. Then, if anything about it worries you, say so plainly. Never invent skills, "
        "credits, or availability that are not in the data."
    )
    user = (f"Role: {role.get('label')}\nClient: {engagement.client.name if engagement.client else 'unknown'}\n"
            f"Required skills: {', '.join(role.get('required_skills') or []) or 'not specified'}\n\n"
            "Ranked shortlist:\n" + "\n".join(lines))

    try:
        driver = registry.get('agent_llm')
        text, usage = driver.complete(system, user, reasoning='off')
        return (text or '').strip(), (usage or {}).get('total_tokens', 0)
    except Exception as e:
        return f"(Could not generate a rationale: {str(e)[:120]})", 0


def run_casting(engagement_id, roles=None, created_by=None):
    """Executor task. Locked per engagement so two producers cannot cast the same
    job concurrently."""
    from authoritative import build_refs
    from locks import AlreadyProcessing, agent_lock
    from models import AgentEvent, CastingRun, Engagement

    try:
        with agent_lock('casting', 'engagement', engagement_id, engagement_id=engagement_id, ttl_minutes=15):
            eng = db_session.query(Engagement).get(engagement_id)
            if not eng:
                return
            pol, prov = policy(eng)

            status = 'ok'
            if not roles:
                roles, status = extract_roles_from_brief(eng)

            run = CastingRun(engagement_id=engagement_id, roles=roles, status='running',
                             created_by=created_by)
            db_session.add(run)
            db_session.flush()

            candidates = db_session.query(Talent).filter(Talent.is_active == True).all()  # noqa: E712
            result = {}
            total_tokens = 0

            for role in roles:
                ranked = score_pool(role, candidates, pol)
                shortlist = ranked[:pol.get('shortlist_size', 3)]
                narration = narrate(role, shortlist, eng)
                rationale, used = narration if isinstance(narration, tuple) else (narration, 0)
                total_tokens += used or 0
                result[role['key']] = {
                    "label": role.get('label'),
                    "shortlist": [serialise(e) for e in shortlist],
                    "rationale": rationale,
                    "concerns": flag_concerns(role, shortlist),
                    "pool_size": len(ranked),
                }

            run.result = result
            run.status = 'needs_input' if status == 'needs_input' else 'done'
            run.tokens_used = total_tokens
            db_session.add(AgentEvent(
                engagement_id=engagement_id, agent='Casting Agent', trigger='casting_run',
                reasoning_summary=(
                    f"Scored {len(candidates)} talents against {len(roles)} role(s). "
                    + '; '.join(f"{k}: {len(v['shortlist'])} shortlisted of {v['pool_size']} eligible"
                                for k, v in result.items())
                ) if roles else "No roles could be read from the brief — needs producer input.",
                action=f"Cast {len(roles)} role(s)", tokens_used=total_tokens,
                authoritative_refs=build_refs(prov),
            ))
            db_session.commit()
    except AlreadyProcessing:
        return
    finally:
        db_session.remove()
