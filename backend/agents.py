import os
import json
import requests
from pydantic import BaseModel, Field, ValidationError
from typing import List, Optional
from models import Brief, Proposal, AgentEvent, PastProject, RateCardItem
from database import db_session

NIM_API_KEY = os.environ.get("NIM_API_KEY")
NIM_MODEL = os.environ.get("NIM_MODEL")

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
    rendered_markdown: str

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
    rendered_markdown: str
    pricing: List[PricingLineItem]

def call_nim_api(system_prompt: str, user_prompt: str) -> str:
    url = "https://integrate.api.nvidia.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {NIM_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": NIM_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.2,
        # The proposal/brief schemas carry both the structured fields (objectives,
        # deliverables, pricing, ...) AND the full rendered_markdown document, which
        # is enough combined output to truncate mid-JSON at the old 4096 cap.
        "max_tokens": 8192,
    }

    response = requests.post(url, headers=headers, json=payload, timeout=120)
    response.raise_for_status()
    data = response.json()
    return data['choices'][0]['message']['content']


def _extract_json(raw_response: str) -> dict:
    """Strip an optional ```json / ``` code fence (robust to surrounding whitespace) and parse."""
    text = raw_response.strip()
    if text.startswith("```"):
        text = text[3:]
        if text.startswith("json"):
            text = text[4:]
        text = text.rsplit("```", 1)[0]
    return json.loads(text.strip())

def render_brief_markdown(brief_json: dict) -> str:
    return f"""# Production Brief: {brief_json.get('client', 'Unknown Client')}

**Work Type:** {brief_json.get('work_type', 'N/A')}

## Objectives
{chr(10).join(f"- {obj}" for obj in brief_json.get('objectives', []))}

## Audience
{brief_json.get('audience', 'N/A')}

## Deliverables
{chr(10).join(f"- {d}" for d in brief_json.get('deliverables', []))}

## Signals & Constraints
- **Timeline:** {brief_json.get('timeline_signals', 'N/A')}
- **Budget:** {brief_json.get('budget_signals', 'N/A')}

## Stakeholders & Risks
- **Key Stakeholders:** {', '.join(brief_json.get('key_stakeholders', []))}
- **Risks:** {chr(10).join(f"  - {r}" for r in brief_json.get('risks', []))}

## Open Questions
{chr(10).join(f"- {q}" for q in brief_json.get('open_questions', []))}
"""

def generate_brief(transcript_text: str, client_name: str) -> dict:
    system_prompt = f"""You are a Production Brief Generator for a creative agency middleman platform. Your job is to turn a raw meeting notes summary (captured by an AI notetaker during the client's intake call) into a structured, professional Production Brief that a creative team can act on.

<task>
1. Read the summary carefully and extract every piece of information relevant to a production brief.
2. Where information is missing or ambiguous, do NOT invent it. Instead, list it under "Open Questions" so the agency can follow up.
3. Organize everything into the Production Brief format below.
4. Keep language clear and professional — this brief may be shown to both the client and the creative team.
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
10. "rendered_markdown": A string containing the exact Markdown document described below. Use \\n for newlines in the string.

The structured fields above and the "rendered_markdown" document must tell the same story — the fields are the same content broken into discrete pieces for the UI, not a separate analysis.

The Markdown document inside "rendered_markdown" MUST follow this structure. Use "Not specified — needs follow-up" for any field with no information in the summary:

# Production Brief: [Project/Client Name]

## 1. Client Overview
- Client/Company:
- Point of contact:
- Industry/context:

## 2. Project Summary
[2-3 sentence plain-language summary of what's being requested and why]

## 3. Objectives
[Bulleted list — what success looks like for this project]

## 4. Target Audience
[Who the end output is for]

## 5. Deliverables Requested
[Bulleted list — as specific as the summary allows: format, quantity, platform, etc.]

## 6. Creative Direction / Tone
[Any style, mood, brand, or reference cues mentioned]

## 7. Timeline
- Requested deadline(s):
- Any milestone dates mentioned:

## 8. Budget
[Only include if explicitly mentioned — never estimate a figure]

## 9. Constraints & Must-Haves
[Any hard requirements, exclusions, brand guidelines, legal/compliance notes]

## 10. Open Questions
[Everything that needs clarifying before the creative team can start — this section matters as much as the rest]
</output_format>"""

    user_prompt = f"""<meeting_summary>
{transcript_text}
</meeting_summary>

Client Name context: {client_name}"""

    try:
        if not NIM_API_KEY:
            # Fallback for local/offline demo use when no NIM_API_KEY is configured.
            print("WARNING: No NIM_API_KEY provided. Using dummy brief generator.")
            return {
                "work_type": "event",
                "objectives": ["Not specified — needs follow-up"],
                "audience": "Not specified — needs follow-up",
                "deliverables": ["Not specified — needs follow-up"],
                "timeline_signals": "Not specified — needs follow-up",
                "budget_signals": "Not specified — needs follow-up",
                "key_stakeholders": [],
                "risks": [],
                "open_questions": ["Not specified — needs follow-up"],
                "rendered_markdown": f"# Production Brief: {client_name}\n\n## 1. Client Overview\n- Client/Company: {client_name}\n- Point of contact: Not specified — needs follow-up\n- Industry/context: Not specified — needs follow-up\n\n## 2. Project Summary\nNot specified — needs follow-up\n\n## 3. Objectives\n- Not specified — needs follow-up\n\n## 4. Target Audience\nNot specified — needs follow-up\n\n## 5. Deliverables Requested\n- Not specified — needs follow-up\n\n## 6. Creative Direction / Tone\nNot specified — needs follow-up\n\n## 7. Timeline\n- Requested deadline(s): Not specified — needs follow-up\n- Any milestone dates mentioned: Not specified — needs follow-up\n\n## 8. Budget\nNot specified — needs follow-up\n\n## 9. Constraints & Must-Haves\nNot specified — needs follow-up\n\n## 10. Open Questions\n- Not specified — needs follow-up"
            }

        raw_response = call_nim_api(system_prompt, user_prompt)
        parsed_json = _extract_json(raw_response)
        ProductionBriefSchema(**parsed_json)
        return parsed_json

    except Exception as e:
        print(f"Agent validation failed: {e}. Retrying...")
        try:
            retry_prompt = user_prompt + f"\n\nPREVIOUS ERROR (Fix this in your new JSON response):\n{str(e)}"
            raw_response = call_nim_api(system_prompt, retry_prompt)
            parsed_json = _extract_json(raw_response)
            ProductionBriefSchema(**parsed_json)
            return parsed_json
        except Exception as retry_e:
            print(f"Agent validation failed on retry: {retry_e}. Using fallback.")
            return {
                "work_type": "event",
                "objectives": [],
                "audience": "",
                "deliverables": [],
                "timeline_signals": "",
                "budget_signals": "",
                "key_stakeholders": [],
                "risks": [f"Brief generation failed: {retry_e}"],
                "open_questions": [],
                "rendered_markdown": f"# Error generating brief\n\nAgent failed with error: {retry_e}"
            }

def extract_meeting_signals(transcript_text: str) -> str:
    system_prompt = """You are a Meeting Signal Extractor for a creative agency middleman platform. You will receive a raw transcript from a client review meeting (e.g. a Zoom call), likely with speaker labels, timestamps, filler words, and crosstalk. Your job is NOT to summarize the whole conversation — it is to pull out only what's needed to update a Production Brief and draft a proposal, and discard everything else.

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

For anything ambiguous — sarcasm, unclear pronouns, overlapping speech, a point that trails off — do not guess at the meaning. Mark it under "Flagged as Unclear" instead of resolving it silently.
</task>

<output_format>
Respond ONLY in this exact structure in Markdown. Leave a bucket empty (write "None") rather than stretching unrelated content to fill it.

## Decisions Made
## New / Changed Requirements
## Budget Signals
## Timeline Signals
## Creative Feedback
## Action Items
## Questions Raised (Unresolved)
## Questions Answered
## Flagged as Unclear
</output_format>"""

    user_prompt = f"""<transcript>
{transcript_text}
</transcript>"""

    if not NIM_API_KEY:
        return "## Decisions Made\nNone\n## New / Changed Requirements\nNone\n## Budget Signals\nNone\n## Timeline Signals\nNone\n## Creative Feedback\nNone\n## Action Items\nNone\n## Questions Raised (Unresolved)\nNone\n## Questions Answered\nNone\n## Flagged as Unclear\nNone"

    return call_nim_api(system_prompt, user_prompt)

def generate_proposal(new_transcript: str, brief: Brief, client_name: str, past_projects: List[PastProject], rate_card: List[RateCardItem], additional_notes: str = "") -> dict:
    
    extracted_signals = extract_meeting_signals(new_transcript)
    if additional_notes:
        extracted_signals += f"\n\n## Manager Additional Notes\n{additional_notes}"
    
    rate_card_text = chr(10).join(f"{r.category} - {r.description} ({r.unit}): {r.rate_kes} KES" for r in rate_card)

    system_prompt = """You are a Proposal Generator for a creative agency middleman platform. A Production Brief was already created from the client's intake call. Since then, the agency held a client review meeting — its transcript has already been processed by a signal-extraction step, and you now have that structured extraction rather than the raw transcript. Your job is to merge the original brief with the extracted signals into ONE final, coherent, client-ready proposal, and also generate pricing line items.

<task>
1. Treat the original brief as the baseline.
2. Apply the extracted signals on top of it:
   - New/Changed Requirements → update the relevant brief section, and log the change
   - Budget Signals / Timeline Signals → finalize those fields if they were previously unspecified, or update them if changed
   - Creative Feedback → fold into "Creative Approach"
   - Questions Answered → resolve the matching item from the brief's Open Questions
   - Questions Raised (Unresolved) + anything still in "Flagged as Unclear" that matters → carry into the proposal's Remaining Open Questions
   - Action Items → note anywhere they affect scope or timeline
3. If a signal contradicts the original brief, the signal wins (it's more recent) — but state the change explicitly in "What Changed" so nothing is overwritten silently.
4. Do not invent details that appear in neither input.
5. Write the final proposal in a persuasive but honest tone — this is the document the client will use to sign off on the work.
</task>

<output_format>
Respond ONLY with a JSON object. The JSON MUST have exactly these keys:
1. "approach": A short string (2-3 sentences) summarizing the creative approach — this also drives the "Creative Approach" section.
2. "scoped_deliverables": A list of short strings — the finalized deliverables, one per item.
3. "phased_timeline": A list of short strings, one per phase/milestone (e.g. "Week 1-2: Video Production").
4. "team_shape": A list of short strings naming the roles staffed on this engagement (e.g. "Project Manager", "Creative Director"), empty list if not determinable.
5. "pricing": A list of objects representing pricing line items. Each object must have "category" (string), "description" (string), "qty" (int), and "rate_kes" (int). Base this purely on the Available Rate Card Items and the deliverables required.
6. "rendered_markdown": A string containing the exact Markdown document described below. Use \\n for newlines in the string.

The structured fields above and the "rendered_markdown" document must tell the same story — the fields are the same content broken into discrete pieces for the UI, not a separate analysis.

The Markdown document inside "rendered_markdown" MUST follow this exact structure:

# Proposal: [Project/Client Name]

## Executive Summary
[3-4 sentences: what's being proposed, why it fits the client's goals, and the outcome they can expect]

## Scope of Work
[Clear bulleted breakdown of deliverables, now finalized]

## Creative Approach
[How the team plans to execute — incorporating feedback from the review meeting]

## Target Audience & Objectives
[Carried over/refined from the brief]

## Timeline
[Finalized milestones and deadlines]

## Investment / Budget
[Provide the final budget context here based on signals and pricing]

## Terms & Assumptions
[Any constraints, dependencies, or things the proposal assumes to be true]

## What Changed Since the Initial Brief
[Short bulleted list — transparency on what shifted after the review meeting, and why]

## Remaining Open Questions
[Anything still unresolved before work can formally begin — omit this section entirely if none remain]
</output_format>"""

    user_prompt = f"""<original_brief>
{brief.rendered_markdown}
</original_brief>

<extracted_meeting_signals>
{extracted_signals}
</extracted_meeting_signals>

Available Rate Card Items (KES):
{rate_card_text}

Client Name: {client_name}"""

    try:
        if not NIM_API_KEY:
            print("WARNING: No NIM_API_KEY provided. Using dummy proposal generator.")
            return {
                "approach": "Not specified — needs follow-up",
                "scoped_deliverables": ["Not specified — needs follow-up"],
                "phased_timeline": ["Not specified — needs follow-up"],
                "team_shape": [],
                "pricing": [{"category": "Strategy", "description": "Strategy Phase", "qty": 1, "rate_kes": 80000}],
                "rendered_markdown": f"# Proposal: {client_name}\n\n## Executive Summary\nDummy Proposal\n\n## Scope of Work\n- Dummy\n\n## Creative Approach\nDummy\n\n## Target Audience & Objectives\nDummy\n\n## Timeline\nDummy\n\n## Investment / Budget\nDummy\n\n## Terms & Assumptions\nDummy\n\n## What Changed Since the Initial Brief\nDummy\n\n## Remaining Open Questions\nNone",
                "extracted_signals": extracted_signals
            }

        raw_response = call_nim_api(system_prompt, user_prompt)
        parsed_json = _extract_json(raw_response)
        ProposalSchema(**parsed_json)
        parsed_json['extracted_signals'] = extracted_signals # return this so app.py can log it
        return parsed_json

    except Exception as e:
        print(f"Agent validation failed: {e}. Retrying...")
        try:
            retry_prompt = user_prompt + f"\n\nPREVIOUS ERROR (Fix this in your new JSON response):\n{str(e)}"
            raw_response = call_nim_api(system_prompt, retry_prompt)
            parsed_json = _extract_json(raw_response)
            ProposalSchema(**parsed_json)
            parsed_json['extracted_signals'] = extracted_signals
            return parsed_json
        except Exception as retry_e:
            print(f"Agent validation failed on retry: {retry_e}. Using fallback.")
            return {
                "approach": "",
                "scoped_deliverables": [],
                "phased_timeline": [],
                "team_shape": [],
                "pricing": [{"category": "Error", "description": "Failed to parse pricing", "qty": 1, "rate_kes": 0}],
                "rendered_markdown": f"# Error generating proposal\n\nAgent failed with error: {retry_e}",
                "extracted_signals": extracted_signals
            }
