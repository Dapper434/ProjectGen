import json
from pydantic import BaseModel, Field, ValidationError
from typing import List, Optional
from config import Config
from models import Brief, Proposal, AgentEvent, PastProject, RateCardItem
from database import db_session

# Still read directly (not through the registry) because these gate *dummy mode*:
# with no NIM key configured the agent functions return clearly-marked placeholder
# content instead of calling anything. rag.py imports NIM_API_KEY for the same check.
NIM_API_KEY = Config.NIM_API_KEY

# The reasoning-effort presets that used to live here now belong to the NIM
# driver (providers/llm/nim.py) — they are Nemotron-specific, and each driver
# maps the shared "off | low | full" vocabulary onto its own knobs.


class ProductionBriefSchema(BaseModel):
    work_type: str = Field(description="One of: change-management campaign, employee engagement, creator campaign, video production, event")
    objectives: List[str] = Field(default_factory=list)
    audience: str = ""
    deliverables: List[str] = Field(default_factory=list)
    timeline_signals: str = ""
    budget_signals: str = ""
    key_stakeholders: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    open_questions: List[str] = Field(default_factory=list)
    summary: str = ""
    meeting_date: Optional[str] = None
    duration_minutes: Optional[int] = None
    attendees: List[str] = Field(default_factory=list)


class SignalExtractionSchema(BaseModel):
    decisions: List[str] = Field(default_factory=list)
    new_requirements: List[str] = Field(default_factory=list)
    budget_signals: List[str] = Field(default_factory=list)
    timeline_signals: List[str] = Field(default_factory=list)
    creative_feedback: List[str] = Field(default_factory=list)
    action_items: List[str] = Field(default_factory=list)
    questions_raised: List[str] = Field(default_factory=list)
    questions_answered: List[str] = Field(default_factory=list)
    flagged_unclear: List[str] = Field(default_factory=list)
    summary: str = ""
    meeting_date: Optional[str] = None
    duration_minutes: Optional[int] = None
    attendees: List[str] = Field(default_factory=list)


class PricingLineItem(BaseModel):
    category: str
    description: str
    qty: int
    rate_kes: int


class ProposalSchema(BaseModel):
    approach: str = ""
    scoped_deliverables: List[str] = Field(default_factory=list)
    phased_timeline: List[str] = Field(default_factory=list)
    team_shape: List[str] = Field(default_factory=list)
    pricing: List[PricingLineItem]
    changelog: List[str] = Field(default_factory=list)
    remaining_open_questions: List[str] = Field(default_factory=list)
    action_items: List[str] = Field(default_factory=list)


def call_nim_api(system_prompt: str, user_prompt: str, reasoning: str = "full", driver_override: str = None) -> tuple[str, dict]:
    """Run a completion through whichever `agent_llm` driver is currently selected.

    Kept under its original name and signature so the five agent functions below
    are unchanged, but it is no longer NIM-specific: the driver comes from the
    provider registry, so the model behind briefs and proposals is switchable at
    runtime (WP-2). NIM remains the registry's fallback, so behaviour with no
    configuration is identical to before.
    """
    from providers import registry
    driver = registry.get('agent_llm', override=driver_override)
    return driver.complete(system_prompt, user_prompt, reasoning=reasoning)


def _extract_json(raw_response: str) -> dict:
    """Strip an optional ```json / ``` code fence (robust to surrounding whitespace) and parse."""
    text = raw_response.strip()
    if text.startswith("```"):
        text = text[3:]
        if text.startswith("json"):
            text = text[4:]
        text = text.rsplit("```", 1)[0]
    return json.loads(text.strip())


# --- Deterministic renderers -------------------------------------------------
# The LLM used to be asked to author a full duplicate `rendered_markdown` document
# alongside the structured fields — pure duplicated generation work (the on-screen
# BriefReport/ProposalReport components and the PDF builders already render straight
# from structured_json, never from this markdown), which cost real output tokens and
# latency for zero information gain. These renderers reproduce an equivalent document
# from the structured fields instead, for the only two things that actually still read
# it: `ilike` search matching, and being fed as prompt context into the *next* agent
# call in the pipeline.

def render_brief_markdown(data: dict, client_name: str) -> str:
    def bullets(items):
        items = [i for i in (items or []) if i]
        return "\n".join(f"- {i}" for i in items) if items else "- None noted"

    return f"""# Production Brief: {client_name}

**Work Type:** {(data.get('work_type') or 'Not specified').replace('-', ' ').title()}

## Objectives
{bullets(data.get('objectives'))}

## Audience
{data.get('audience') or 'Not specified — needs follow-up'}

## Deliverables
{bullets(data.get('deliverables'))}

## Timeline
{data.get('timeline_signals') or 'Not specified — needs follow-up'}

## Budget
{data.get('budget_signals') or 'Not specified — needs follow-up'}

## Key Stakeholders
{bullets(data.get('key_stakeholders'))}

## Risks
{bullets(data.get('risks'))}

## Open Questions
{bullets(data.get('open_questions'))}
"""


def render_signals_markdown(data: dict) -> str:
    def bullets(items):
        items = [i for i in (items or []) if i]
        return "\n".join(f"- {i}" for i in items) if items else "None"

    return f"""## Decisions Made
{bullets(data.get('decisions'))}

## New / Changed Requirements
{bullets(data.get('new_requirements'))}

## Budget Signals
{bullets(data.get('budget_signals'))}

## Timeline Signals
{bullets(data.get('timeline_signals'))}

## Creative Feedback
{bullets(data.get('creative_feedback'))}

## Action Items
{bullets(data.get('action_items'))}

## Questions Raised (Unresolved)
{bullets(data.get('questions_raised'))}

## Questions Answered
{bullets(data.get('questions_answered'))}

## Flagged as Unclear
{bullets(data.get('flagged_unclear'))}
"""


def render_proposal_markdown(data: dict, client_name: str) -> str:
    def bullets(items):
        items = [i for i in (items or []) if i]
        return "\n".join(f"- {i}" for i in items) if items else "- None noted"

    pricing = data.get('pricing') or []
    if pricing:
        rows = "\n".join(
            f"| {p.get('category', '')} | {p.get('description', '')} | {p.get('qty', 1)} | "
            f"{p.get('rate_kes', 0):,} | {(p.get('qty', 1) or 1) * (p.get('rate_kes', 0) or 0):,} |"
            for p in pricing
        )
        total = sum((p.get('qty', 1) or 1) * (p.get('rate_kes', 0) or 0) for p in pricing)
        pricing_block = f"""| Category | Description | Qty | Rate (KES) | Total (KES) |
|---|---|---|---|---|
{rows}

**Total Investment: KES {total:,}**"""
    else:
        pricing_block = "Not specified"

    remaining_questions = data.get('remaining_open_questions') or []
    open_questions_block = f"\n## Remaining Open Questions\n{bullets(remaining_questions)}\n" if remaining_questions else ""

    return f"""# Proposal: {client_name}

## Approach
{data.get('approach') or 'Not specified'}

## Scoped Deliverables
{bullets(data.get('scoped_deliverables'))}

## Phased Timeline
{bullets(data.get('phased_timeline'))}

## Team Shape
{bullets(data.get('team_shape'))}

## Pricing
{pricing_block}

## What Changed Since the Initial Brief
{bullets(data.get('changelog'))}
{open_questions_block}"""


DEFAULT_BRIEF_GENERATION_PROMPT = """You are a Production Brief Generator for a creative agency middleman platform. Your job is to turn a raw meeting notes summary (captured by an AI notetaker during the client's intake call) into a structured, professional Production Brief that a creative team can act on.

<task>
1. Read the summary carefully and extract every piece of information relevant to a production brief.
2. Where information is missing or ambiguous, do NOT invent it. Instead, list it under "open_questions" so the agency can follow up.
3. Also extract meeting metadata: only fill "meeting_date" or "duration_minutes" if explicitly stated in the transcript (e.g. "this was a 45 minute call" or "recorded March 3rd") — never guess or estimate a precise value. "attendees" lists people/roles who were actually present or speaking on the call (may overlap with key_stakeholders, but this is specifically about who was on THIS call). "summary" is a short, neutral 2-4 sentence recap of what was actually discussed in the call itself — distinct from the brief content below.
4. Keep language clear and professional — this brief may be shown to both the client and the creative team.
5. If this client's past engagement history is provided below, use it only for continuity and context (e.g. recognizing a repeat pattern, being consistent with past scoping) — never invent details for *this* engagement from it, and never treat it as a substitute for what this transcript actually says.
6. If agency-provided reference material is included below, use it to enrich this brief. Material labeled a structure/template reference shows the organization and phrasing conventions your field *values* should follow — the JSON keys themselves are fixed and must never change. Material labeled content/background (e.g. the client's own RFP, brand guidelines) may supply additional factual requirements and context that belong in this brief. If reference material conflicts with the transcript, the transcript wins. Never copy template boilerplate that doesn't apply to this engagement.
</task>

<output_format>
Respond ONLY with a JSON object. The JSON MUST have exactly these keys:
1. "work_type": A string representing the type of work. Must be one of: change-management campaign, employee engagement, creator campaign, video production, event.
2. "objectives": A list of short strings — what success looks like for this project.
3. "audience": A short string — who the end output is for.
4. "deliverables": A list of short strings — the concrete deliverables requested (format/quantity/platform where known).
5. "timeline_signals": A short string summarizing requested deadlines/milestones, or "Not specified — needs follow-up".
6. "budget_signals": A short string with any budget explicitly mentioned, or "Not specified — needs follow-up".
7. "key_stakeholders": A list of short strings naming people/roles mentioned (point of contact, decision-makers), empty list if none.
8. "risks": A list of short strings — hard constraints, exclusions, or risks called out, empty list if none.
9. "open_questions": A list of short strings — everything that needs clarifying before the creative team can start.
10. "summary": A short (2-4 sentence) neutral recap of what was discussed in this specific meeting.
11. "meeting_date": A string if a date was explicitly stated in the transcript, otherwise null. Never guess.
12. "duration_minutes": An integer if a call length was explicitly stated, otherwise null. Never guess.
13. "attendees": A list of short strings naming people/roles who were present on this call, empty list if not determinable.
</output_format>"""


def generate_brief(transcript_text: str, client_name: str, client_history: str = "", reference_material: str = "", system_prompt: Optional[str] = None) -> dict:
    if system_prompt is None:
        print("INFO: no authoritative brief_generation_prompt found — using legacy constant.")
        system_prompt = DEFAULT_BRIEF_GENERATION_PROMPT

    history_block = f"\n\n<this_clients_past_engagements>\n{client_history}\n</this_clients_past_engagements>" if client_history else ""
    reference_block = f"\n\n<reference_material>\n{reference_material}\n</reference_material>" if reference_material else ""

    user_prompt = f"""<meeting_summary>
{transcript_text}
</meeting_summary>

Client Name context: {client_name}{history_block}{reference_block}"""

    if not NIM_API_KEY:
        print("WARNING: No NIM_API_KEY provided. Using dummy brief generator.")
        dummy = {
            "work_type": "event",
            "objectives": ["Not specified — needs follow-up"],
            "audience": "Not specified — needs follow-up",
            "deliverables": ["Not specified — needs follow-up"],
            "timeline_signals": "Not specified — needs follow-up",
            "budget_signals": "Not specified — needs follow-up",
            "key_stakeholders": [],
            "risks": [],
            "open_questions": ["Not specified — needs follow-up"],
            "summary": "No NIM_API_KEY configured — this is placeholder content.",
            "meeting_date": None,
            "duration_minutes": None,
            "attendees": [],
        }
        dummy['rendered_markdown'] = render_brief_markdown(dummy, client_name)
        return dummy

    try:
        raw_response, usage = call_nim_api(system_prompt, user_prompt, reasoning="off")
        parsed_json = _extract_json(raw_response)
        ProductionBriefSchema(**parsed_json)
        parsed_json['rendered_markdown'] = render_brief_markdown(parsed_json, client_name)
        parsed_json['_tokens_used'] = usage.get('total_tokens', 0)
        return parsed_json

    except Exception as e:
        print(f"Agent validation failed: {e}. Retrying with escalated reasoning...")
        try:
            retry_prompt = user_prompt + f"\n\nPREVIOUS ERROR (Fix this in your new JSON response):\n{str(e)}"
            raw_response, usage = call_nim_api(system_prompt, retry_prompt, reasoning="full")
            parsed_json = _extract_json(raw_response)
            ProductionBriefSchema(**parsed_json)
            parsed_json['rendered_markdown'] = render_brief_markdown(parsed_json, client_name)
            parsed_json['_tokens_used'] = usage.get('total_tokens', 0)
            return parsed_json
        except Exception as retry_e:
            print(f"Agent validation failed on retry: {retry_e}. Using fallback.")
            fallback = {
                "work_type": "event",
                "objectives": [],
                "audience": "",
                "deliverables": [],
                "timeline_signals": "",
                "budget_signals": "",
                "key_stakeholders": [],
                "risks": [f"Brief generation failed: {retry_e}"],
                "open_questions": [],
                "summary": "",
                "meeting_date": None,
                "duration_minutes": None,
                "attendees": [],
                "_tokens_used": 0,
            }
            fallback['rendered_markdown'] = f"# Error generating brief\n\nAgent failed with error: {retry_e}"
            return fallback


DEFAULT_SIGNAL_EXTRACTION_PROMPT = """You are a Meeting Signal Extractor for a creative agency middleman platform. You will receive a raw transcript from a client review meeting (e.g. a Zoom call), likely with speaker labels, timestamps, filler words, and crosstalk. Your job is NOT to summarize the whole conversation — it is to pull out only what's needed to update a Production Brief and draft a proposal, and discard everything else.

<task>
Read the full transcript. Ignore small talk, technical difficulties ("can you hear me?"), and off-topic tangents. Extract and categorize everything relevant into these buckets:

1. Decisions made — anything the group explicitly agreed on
2. New or changed requirements — anything different from what a prior brief would have said
3. Budget signals — any number, range, or budget-related constraint mentioned, and who said it
4. Timeline signals — any date, deadline, or scheduling constraint mentioned
5. Creative feedback — reactions to creative direction, references brought up, likes/dislikes expressed
6. Action items — anything someone committed to doing, and by whom if stated
7. Questions raised but unresolved on the call
8. Questions that appear to have been answered (useful for closing out a prior brief's "Open Questions")

For anything ambiguous — sarcasm, unclear pronouns, overlapping speech, a point that trails off — do not guess at the meaning. Mark it under "flagged_unclear" instead of resolving it silently.

Also extract meeting metadata: only fill "meeting_date" or "duration_minutes" if explicitly stated in the transcript — never guess or estimate. "attendees" lists people/roles present or speaking on this call. "summary" is a short, neutral 2-4 sentence recap of what was discussed.
</task>

<output_format>
Respond ONLY with a JSON object. The JSON MUST have exactly these keys, each a list of short strings (leave a list empty rather than stretching unrelated content to fill it), except where noted:
1. "decisions"
2. "new_requirements"
3. "budget_signals"
4. "timeline_signals"
5. "creative_feedback"
6. "action_items"
7. "questions_raised"
8. "questions_answered"
9. "flagged_unclear"
10. "summary": a short (2-4 sentence) string, not a list.
11. "meeting_date": a string if explicitly stated, otherwise null. Never guess.
12. "duration_minutes": an integer if explicitly stated, otherwise null. Never guess.
13. "attendees": a list of short strings, empty list if not determinable.
</output_format>"""


def extract_meeting_signals(transcript_text: str, system_prompt: Optional[str] = None) -> dict:
    if system_prompt is None:
        print("INFO: no authoritative signal_extraction_prompt found — using legacy constant.")
        system_prompt = DEFAULT_SIGNAL_EXTRACTION_PROMPT

    user_prompt = f"""<transcript>
{transcript_text}
</transcript>"""

    empty = {
        "decisions": [], "new_requirements": [], "budget_signals": [], "timeline_signals": [],
        "creative_feedback": [], "action_items": [], "questions_raised": [], "questions_answered": [],
        "flagged_unclear": [], "summary": "", "meeting_date": None, "duration_minutes": None,
        "attendees": [], "_tokens_used": 0,
    }

    if not NIM_API_KEY:
        empty["summary"] = "No NIM_API_KEY configured — this is placeholder content."
        return empty

    try:
        raw_response, usage = call_nim_api(system_prompt, user_prompt, reasoning="off")
        parsed_json = _extract_json(raw_response)
        SignalExtractionSchema(**parsed_json)
        parsed_json['_tokens_used'] = usage.get('total_tokens', 0)
        return parsed_json
    except Exception as e:
        print(f"Signal extraction failed: {e}. Retrying with escalated reasoning...")
        try:
            retry_prompt = user_prompt + f"\n\nPREVIOUS ERROR (Fix this in your new JSON response):\n{str(e)}"
            raw_response, usage = call_nim_api(system_prompt, retry_prompt, reasoning="full")
            parsed_json = _extract_json(raw_response)
            SignalExtractionSchema(**parsed_json)
            parsed_json['_tokens_used'] = usage.get('total_tokens', 0)
            return parsed_json
        except Exception as retry_e:
            print(f"Signal extraction failed on retry: {retry_e}. Using empty buckets.")
            empty["flagged_unclear"] = [f"Signal extraction failed: {retry_e}"]
            return empty


DEFAULT_PROPOSAL_GENERATION_PROMPT = """You are a Proposal Generator for a creative agency middleman platform. A Production Brief was already created from the client's intake call. Since then, the agency held a client review meeting — its transcript has already been processed by a signal-extraction step, and you now have that structured extraction rather than the raw transcript. Your job is to merge the original brief with the extracted signals into ONE final, coherent, client-ready proposal, and also generate pricing line items.

<task>
1. Treat the original brief as the baseline.
2. Apply the extracted signals on top of it:
   - New/Changed Requirements → update the relevant brief section, and log the change
   - Budget Signals / Timeline Signals → finalize those fields if they were previously unspecified, or update them if changed
   - Creative Feedback → fold into "approach"
   - Questions Answered → resolve the matching item from the brief's Open Questions
   - Questions Raised (Unresolved) + anything still in "Flagged as Unclear" that matters → carry into "remaining_open_questions"
   - Action Items → note in "action_items" anywhere they affect scope or timeline
3. If a signal contradicts the original brief, the signal wins (it's more recent) — but state the change explicitly in "changelog" so nothing is overwritten silently.
4. Use "Past Projects for Reference" below as a guide for realistic scoping, phrasing, and pricing patterns when this engagement resembles one of them — but never force a match, and never invent deliverables or pricing that aren't grounded in the brief, the signals, or the rate card.
4b. If "This Client's Own Engagement History" is provided, use it for continuity with this specific client (recognizing a repeat relationship, staying consistent with how past work for them was scoped/priced) — it is more relevant than the generic past-projects reference, but still never invent this engagement's content from it.
4c. If a "<reference_material>" section is provided, use it to enrich this proposal. Material labeled a structure/template reference shows how the agency organizes and phrases proposals within the fixed JSON fields (e.g. how phases are named, how pricing lines are described, how the approach narrative is framed) — the JSON keys themselves never change. Material labeled content/background (e.g. the client's own RFP or brand material) may supply factual requirements this proposal must honor. On client-specific facts, the brief and the extracted signals always win over reference material.
5. Do not invent details that appear in neither the brief nor the signals.
6. Write the proposal in a persuasive but honest tone — this is the document the client will use to sign off on the work.
</task>

<output_format>
Respond ONLY with a JSON object. The JSON MUST have exactly these keys:
1. "approach": A short string (2-3 sentences) summarizing the creative approach.
2. "scoped_deliverables": A list of short strings — the finalized deliverables, one per item.
3. "phased_timeline": A list of short strings, one per phase/milestone (e.g. "Week 1-2: Video Production").
4. "team_shape": A list of short strings naming the roles staffed on this engagement (e.g. "Project Manager", "Creative Director"), empty list if not determinable.
5. "pricing": A list of objects representing pricing line items. Each object must have "category" (string), "description" (string), "qty" (int), and "rate_kes" (int). Base this purely on the Available Rate Card Items and the deliverables required.
6. "changelog": A list of short strings — each one a distinct change made relative to the original brief, and why. This is the transparency record the client/AM sees for "what changed since the brief."
7. "remaining_open_questions": A list of short strings — anything still unresolved before work can formally begin. Empty list if none remain.
8. "action_items": A list of short strings — commitments from the review meeting that affect scope, timeline, or delivery (who owns what), empty list if none.
</output_format>"""


def generate_proposal(new_transcript: str, brief: Brief, client_name: str, past_projects: List[PastProject], rate_card: List[RateCardItem], client_history: str = "", reference_material: str = "", system_prompt: Optional[str] = None, signal_system_prompt: Optional[str] = None) -> dict:

    signals = extract_meeting_signals(new_transcript, system_prompt=signal_system_prompt)
    signal_tokens = signals.pop('_tokens_used', 0)
    signals_markdown = render_signals_markdown(signals)

    rate_card_text = chr(10).join(f"{r.category} - {r.description} ({r.unit}): {r.rate_kes} KES" for r in rate_card)

    if past_projects:
        past_projects_text = chr(10).join(
            f"- [{p.client_type}, {p.work_type}] {p.summary} Typical pricing pattern: {p.typical_pricing_notes}"
            for p in past_projects
        )
    else:
        past_projects_text = "None on file."

    client_history_text = client_history or "None on file — this is the first engagement with this client, or no prior history was found."

    if system_prompt is None:
        print("INFO: no authoritative proposal_generation_prompt found — using legacy constant.")
        system_prompt = DEFAULT_PROPOSAL_GENERATION_PROMPT

    user_prompt = f"""<original_brief>
{brief.rendered_markdown}
</original_brief>

<extracted_meeting_signals>
{signals_markdown}
</extracted_meeting_signals>

Available Rate Card Items (KES):
{rate_card_text}

Past Projects for Reference:
{past_projects_text}

This Client's Own Engagement History:
{client_history_text}

Client Name: {client_name}"""

    if reference_material:
        user_prompt += f"\n\n<reference_material>\n{reference_material}\n</reference_material>"

    def _finish(parsed_json, proposal_tokens):
        parsed_json['rendered_markdown'] = render_proposal_markdown(parsed_json, client_name)
        parsed_json['extracted_signals'] = signals
        parsed_json['extracted_signals_markdown'] = signals_markdown
        parsed_json['_signal_tokens_used'] = signal_tokens
        parsed_json['_proposal_tokens_used'] = proposal_tokens
        return parsed_json

    if not NIM_API_KEY:
        print("WARNING: No NIM_API_KEY provided. Using dummy proposal generator.")
        dummy = {
            "approach": "Not specified — needs follow-up",
            "scoped_deliverables": ["Not specified — needs follow-up"],
            "phased_timeline": ["Not specified — needs follow-up"],
            "team_shape": [],
            "pricing": [{"category": "Strategy", "description": "Strategy Phase", "qty": 1, "rate_kes": 80000}],
            "changelog": ["Initial proposal drafted (dummy mode)."],
            "remaining_open_questions": [],
            "action_items": [],
        }
        return _finish(dummy, 0)

    try:
        raw_response, usage = call_nim_api(system_prompt, user_prompt, reasoning="low")
        parsed_json = _extract_json(raw_response)
        ProposalSchema(**parsed_json)
        return _finish(parsed_json, usage.get('total_tokens', 0))

    except Exception as e:
        print(f"Agent validation failed: {e}. Retrying with escalated reasoning...")
        try:
            retry_prompt = user_prompt + f"\n\nPREVIOUS ERROR (Fix this in your new JSON response):\n{str(e)}"
            raw_response, usage = call_nim_api(system_prompt, retry_prompt, reasoning="full")
            parsed_json = _extract_json(raw_response)
            ProposalSchema(**parsed_json)
            return _finish(parsed_json, usage.get('total_tokens', 0))
        except Exception as retry_e:
            print(f"Agent validation failed on retry: {retry_e}. Using fallback.")
            fallback = {
                "approach": "",
                "scoped_deliverables": [],
                "phased_timeline": [],
                "team_shape": [],
                "pricing": [{"category": "Error", "description": "Failed to parse pricing", "qty": 1, "rate_kes": 0}],
                "changelog": [f"Proposal generation failed: {retry_e}"],
                "remaining_open_questions": [],
                "action_items": [],
            }
            return _finish(fallback, 0)


DEFAULT_PROPOSAL_REVISION_PROMPT = """You are a Proposal Revision Agent for a creative agency middleman platform. An Account Manager has reviewed a client-ready proposal and requested specific changes before it can be approved. Your job is to apply ONLY the requested changes to the existing proposal — this is a targeted edit, not a rewrite.

<task>
1. Treat the Current Proposal below as the source of truth. Copy "approach", "phased_timeline", "team_shape", "remaining_open_questions", "action_items", and every pricing line item VERBATIM (identical wording, identical field values) unless the Account Manager's request specifically requires changing that exact field. Do not rephrase, rename, reformat, reorder, or "clean up" anything you were not asked to change — this is a targeted edit, not a rewrite.
2. "team_shape" lists the staffed roles for the engagement. It is independent of the "pricing" line items (a role can exist without its own pricing line, and vice versa) — never resync, prune, or reword team_shape to match the pricing categories. Only touch it if the request explicitly adds/removes/changes a staffed role.
3. Apply the Account Manager's requested changes precisely and nowhere else.
4. If a change affects scope (adding/removing/resizing a deliverable), update the "pricing" line items to match using the Available Rate Card Items — remove stale line items for scope that was cut, add line items for scope that was added, and don't invent categories the rate card doesn't support. Leave every other pricing line item completely untouched (same category, description, qty, rate_kes, byte-for-byte).
5. If a requested change is ambiguous, make the smallest reasonable interpretation rather than guessing broadly, and surface the interpretation as a new changelog entry.
6. You MUST copy every existing entry in "changelog" verbatim, in order, and then append exactly ONE new string at the end describing this specific revision. A response whose "changelog" list is identical (missing the new entry) or that rewrites/reorders prior entries is wrong — re-check before responding.
</task>

<output_format>
Respond ONLY with a JSON object. The JSON MUST have exactly these keys, matching the Current Proposal's structure:
1. "approach": A short string (2-3 sentences) summarizing the creative approach.
2. "scoped_deliverables": A list of short strings — the finalized deliverables, one per item.
3. "phased_timeline": A list of short strings, one per phase/milestone.
4. "team_shape": A list of short strings naming the roles staffed on this engagement.
5. "pricing": A list of objects representing pricing line items. Each object must have "category" (string), "description" (string), "qty" (int), and "rate_kes" (int).
6. "changelog": Every prior entry verbatim, plus exactly one new entry describing this revision.
7. "remaining_open_questions": A list of short strings, copied verbatim unless the request resolves or adds one.
8. "action_items": A list of short strings, copied verbatim unless the request changes one.
</output_format>"""


def revise_proposal(current_proposal: Proposal, manager_notes: str, client_name: str, rate_card: List[RateCardItem], system_prompt: Optional[str] = None) -> dict:
    rate_card_text = chr(10).join(f"{r.category} - {r.description} ({r.unit}): {r.rate_kes} KES" for r in rate_card)

    if system_prompt is None:
        print("INFO: no authoritative proposal_revision_prompt found — using legacy constant.")
        system_prompt = DEFAULT_PROPOSAL_REVISION_PROMPT

    current_fields = {
        k: v for k, v in (current_proposal.structured_json or {}).items()
        if k not in ('rendered_markdown', 'extracted_signals', 'extracted_signals_markdown')
    }

    user_prompt = f"""<current_proposal_structured_fields_json>
{json.dumps(current_fields, indent=2)}
</current_proposal_structured_fields_json>

This JSON is the exact source of truth for every field — copy it verbatim except where the requested changes below require an update.

<account_manager_requested_changes>
{manager_notes}
</account_manager_requested_changes>

Available Rate Card Items (KES):
{rate_card_text}

Client Name: {client_name}"""

    def _finish(parsed_json, tokens):
        parsed_json['rendered_markdown'] = render_proposal_markdown(parsed_json, client_name)
        parsed_json['_tokens_used'] = tokens
        return parsed_json

    if not NIM_API_KEY:
        print("WARNING: No NIM_API_KEY provided. Revision is a no-op in dummy mode.")
        unchanged = dict(current_proposal.structured_json or {})
        unchanged.setdefault('changelog', [])
        unchanged['pricing'] = current_proposal.pricing_line_items or []
        return _finish(unchanged, 0)

    try:
        raw_response, usage = call_nim_api(system_prompt, user_prompt, reasoning="low")
        parsed_json = _extract_json(raw_response)
        ProposalSchema(**parsed_json)
        return _finish(parsed_json, usage.get('total_tokens', 0))

    except Exception as e:
        print(f"Revision agent validation failed: {e}. Retrying with escalated reasoning...")
        try:
            retry_prompt = user_prompt + f"\n\nPREVIOUS ERROR (Fix this in your new JSON response):\n{str(e)}"
            raw_response, usage = call_nim_api(system_prompt, retry_prompt, reasoning="full")
            parsed_json = _extract_json(raw_response)
            ProposalSchema(**parsed_json)
            return _finish(parsed_json, usage.get('total_tokens', 0))
        except Exception as retry_e:
            print(f"Revision agent validation failed on retry: {retry_e}. Aborting — leaving the existing proposal as-is.")
            raise RuntimeError(f"Could not apply the requested changes: {retry_e}") from retry_e


DEFAULT_BRIEF_REFINEMENT_PROMPT = """You are a Production Brief Refinement Agent for a creative agency middleman platform. A Production Brief already exists from an earlier client meeting. The agency has since had another client meeting, and you have its raw transcript. Your job is to update ONLY what this new transcript actually adds or changes — this is a targeted edit, not a rewrite.

<task>
1. Treat the Current Brief below as the source of truth. Copy every field verbatim unless the new transcript specifically adds, changes, or resolves something in it.
2. New information fills gaps (e.g. resolves an open question, adds a missing budget figure) — move resolved items out of "open_questions".
3. Changed information (e.g. a deliverable was added/dropped, a deadline moved) updates the relevant field — do not silently drop the old value, just replace it since brief fields are current-state, not a changelog.
4. Do not invent details that appear in neither the current brief nor the new transcript.
5. Extract this new meeting's own metadata (summary/date/duration/attendees) — these describe THIS meeting, not the whole relationship, so they are not "copied verbatim," they are freshly extracted from the new transcript only.
</task>

<output_format>
Respond ONLY with a JSON object with exactly these keys, matching the Current Brief's structure:
1. "work_type", "objectives", "audience", "deliverables", "timeline_signals", "budget_signals", "key_stakeholders", "risks", "open_questions" — updated brief fields (copy verbatim unless the new transcript changes them).
2. "summary": A short (2-4 sentence) neutral recap of what was discussed in THIS new meeting specifically.
3. "meeting_date": A string if explicitly stated in this new transcript, otherwise null. Never guess.
4. "duration_minutes": An integer if explicitly stated in this new transcript, otherwise null. Never guess.
5. "attendees": A list of short strings present on this new call, empty list if not determinable.
</output_format>"""


def refine_brief(existing_brief: Brief, new_transcript: str, client_name: str, system_prompt: Optional[str] = None) -> dict:
    """Targeted-edit refinement of an existing brief with a second (or later) intake
    meeting transcript, for engagements that need more than one client-meeting round
    before moving to the proposal stage. Mirrors revise_proposal's copy-verbatim-unless-
    changed pattern rather than regenerating the brief from scratch."""

    if system_prompt is None:
        print("INFO: no authoritative brief_refinement_prompt found — using legacy constant.")
        system_prompt = DEFAULT_BRIEF_REFINEMENT_PROMPT

    current_fields = {
        k: v for k, v in (existing_brief.structured_json or {}).items()
        if k not in ('rendered_markdown', 'summary', 'meeting_date', 'duration_minutes', 'attendees')
    }

    user_prompt = f"""<current_brief_structured_fields_json>
{json.dumps(current_fields, indent=2)}
</current_brief_structured_fields_json>

<new_meeting_transcript>
{new_transcript}
</new_meeting_transcript>

Client Name: {client_name}"""

    def _finish(parsed_json, tokens):
        parsed_json['rendered_markdown'] = render_brief_markdown(parsed_json, client_name)
        parsed_json['_tokens_used'] = tokens
        return parsed_json

    if not NIM_API_KEY:
        print("WARNING: No NIM_API_KEY provided. Refinement is a no-op in dummy mode.")
        unchanged = dict(current_fields)
        unchanged.update({"summary": "No NIM_API_KEY configured — placeholder content.", "meeting_date": None, "duration_minutes": None, "attendees": []})
        return _finish(unchanged, 0)

    try:
        raw_response, usage = call_nim_api(system_prompt, user_prompt, reasoning="low")
        parsed_json = _extract_json(raw_response)
        ProductionBriefSchema(**parsed_json)
        return _finish(parsed_json, usage.get('total_tokens', 0))

    except Exception as e:
        print(f"Brief refinement validation failed: {e}. Retrying with escalated reasoning...")
        try:
            retry_prompt = user_prompt + f"\n\nPREVIOUS ERROR (Fix this in your new JSON response):\n{str(e)}"
            raw_response, usage = call_nim_api(system_prompt, retry_prompt, reasoning="full")
            parsed_json = _extract_json(raw_response)
            ProductionBriefSchema(**parsed_json)
            return _finish(parsed_json, usage.get('total_tokens', 0))
        except Exception as retry_e:
            print(f"Brief refinement failed on retry: {retry_e}. Aborting — leaving the existing brief as-is.")
            raise RuntimeError(f"Could not refine the brief: {retry_e}") from retry_e
