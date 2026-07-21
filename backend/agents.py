import os
import json
import requests
from pydantic import BaseModel, Field, ValidationError
from typing import List
from models import Brief, Proposal, AgentEvent, PastProject, RateCardItem
from database import db_session

NIM_API_KEY = os.environ.get("NIM_API_KEY", "")  # blank is meaningful here — it's the "not configured" signal
NIM_MODEL = os.environ.get("NIM_MODEL") or "meta/llama-3.1-70b-instruct"

class ProductionBriefSchema(BaseModel):
    client: str
    objectives: List[str]
    audience: str
    deliverables: List[str]
    timeline_signals: str
    budget_signals: str
    key_stakeholders: List[str]
    risks: List[str]
    open_questions: List[str]
    work_type: str = Field(description="One of: change-management campaign, employee engagement, creator campaign, video production, event")

class PricingLineItem(BaseModel):
    category: str
    description: str
    qty: int
    rate_kes: int

class ProposalSchema(BaseModel):
    approach: str
    scoped_deliverables: List[str]
    phased_timeline: List[str]
    team_shape: List[str]
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
        "max_tokens": 4096,
    }
    
    response = requests.post(url, headers=headers, json=payload, timeout=60)
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
    system_prompt = f"""You are the Brief Generator Agent for GDF Kenya. 
Your job is to read a raw meeting transcript for the client '{client_name}' and produce a structured JSON Production Brief.
Return ONLY valid JSON matching the exact schema provided. Do not include markdown formatting or conversational text."""

    user_prompt = f"""Transcript:
{transcript_text}

Output JSON Schema:
{{
  "client": "string",
  "objectives": ["string"],
  "audience": "string",
  "deliverables": ["string"],
  "timeline_signals": "string",
  "budget_signals": "string",
  "key_stakeholders": ["string"],
  "risks": ["string"],
  "open_questions": ["string"],
  "work_type": "string (change-management campaign, employee engagement, creator campaign, video production, event)"
}}"""

    try:
        if not NIM_API_KEY:
            # Fallback for local/offline demo use when no NIM_API_KEY is configured.
            # Kept free of internal/debug text since it renders straight into a client-facing document.
            print("WARNING: No NIM_API_KEY provided. Using placeholder brief generator.")
            return {
                "client": client_name,
                "objectives": ["Objectives to be finalized based on transcript review"],
                "audience": "To be defined",
                "deliverables": ["Deliverable scope to be finalized"],
                "timeline_signals": "TBD",
                "budget_signals": "TBD",
                "key_stakeholders": [],
                "risks": [],
                "open_questions": ["What are the primary objectives for this engagement?"],
                "work_type": "event"
            }

        raw_response = call_nim_api(system_prompt, user_prompt)
        parsed_json = _extract_json(raw_response)

        # Validate schema
        ProductionBriefSchema(**parsed_json)
        return parsed_json

    except (ValidationError, json.JSONDecodeError, requests.exceptions.RequestException) as e:
        print(f"Agent call/validation failed: {e}. Retrying...")
        try:
            # Retry once
            retry_prompt = user_prompt + f"\n\nPREVIOUS ERROR (Fix this in your new JSON response):\n{str(e)}"
            raw_response = call_nim_api(system_prompt, retry_prompt)
            parsed_json = _extract_json(raw_response)
            ProductionBriefSchema(**parsed_json)
            return parsed_json
        except Exception as retry_e:
            print(f"Agent validation failed on retry: {retry_e}. Using fallback.")
            return {
                "client": client_name,
                "objectives": ["Failed to parse transcript objectives"],
                "audience": "N/A",
                "deliverables": ["Error in generation"],
                "timeline_signals": "TBD",
                "budget_signals": "TBD",
                "key_stakeholders": ["N/A"],
                "risks": ["Agent failed to generate structured data"],
                "open_questions": ["Please review transcript manually"],
                "work_type": "event"
            }

def render_proposal_markdown(proposal_json: dict, client_name: str) -> str:
    pricing_items = proposal_json.get('pricing', []) or []
    if pricing_items:
        rows = []
        grand_total = 0
        for item in pricing_items:
            qty = item.get('qty', 1) or 1
            rate = item.get('rate_kes', 0) or 0
            line_total = qty * rate
            grand_total += line_total
            rows.append(
                f"| {item.get('category', '')} | {item.get('description', '')} | {qty} | "
                f"KES {rate:,} | KES {line_total:,} |"
            )
        pricing_section = f"""## Pricing Structure
| Category | Description | Qty | Rate (KES) | Total (KES) |
|---|---|---|---|---|
{chr(10).join(rows)}
| | | | **Total Investment** | **KES {grand_total:,}** |
"""
    else:
        pricing_section = "## Pricing Structure\nNo pricing line items yet.\n"

    return f"""# Proposal: {client_name}

## Approach
{proposal_json.get('approach', 'N/A')}

## Note on Changes
This proposal reflects the updated scope as discussed in the review meeting.

## Deliverables
{chr(10).join(f"- {d}" for d in proposal_json.get('scoped_deliverables', []))}

## Timeline
{chr(10).join(f"- {t}" for t in proposal_json.get('phased_timeline', []))}

## Team Shape
{chr(10).join(f"- {t}" for t in proposal_json.get('team_shape', []))}

{pricing_section}"""

def generate_proposal(new_transcript: str, brief: Brief, client_name: str, past_projects: List[PastProject], rate_card: List[RateCardItem], additional_notes: str = "") -> dict:
    system_prompt = f"""You are the Proposal Generator Agent for GDF Kenya.
Your job is to combine the original Production Brief, a new follow-up meeting transcript (or review notes), internal rate cards, and past project data to generate a structured Client Proposal.
Return ONLY valid JSON matching the exact schema provided. Do not include markdown formatting or conversational text."""

    rate_card_text = chr(10).join(f"{r.category} - {r.description} ({r.unit}): {r.rate_kes} KES" for r in rate_card)
    past_projects_text = chr(10).join(f"Project Type: {p.work_type}\nSummary: {p.summary}\nTypical Pricing: {p.typical_pricing_notes}" for p in past_projects)

    user_prompt = f"""Client: {client_name}
    
Original Brief JSON:
{json.dumps(brief.structured_json, indent=2)}

New Transcript / Notes:
{new_transcript}
{("Additional Manager Notes: " + additional_notes) if additional_notes else ""}

Available Rate Card Items (KES):
{rate_card_text}

Past Comparable Projects:
{past_projects_text}

Output JSON Schema:
{{
  "approach": "string (narrative approach)",
  "scoped_deliverables": ["string"],
  "phased_timeline": ["string"],
  "team_shape": ["string"],
  "pricing": [
    {{
      "category": "string",
      "description": "string",
      "qty": 1,
      "rate_kes": 100000
    }}
  ]
}}"""

    try:
        if not NIM_API_KEY:
            print("WARNING: No NIM_API_KEY provided. Using placeholder proposal generator.")
            return {
                "approach": "Approach to be finalized based on the review meeting discussion",
                "scoped_deliverables": brief.structured_json.get("deliverables", []),
                "phased_timeline": ["Week 1: Strategy", "Week 2: Execution"],
                "team_shape": ["Strategist", "Designer"],
                "pricing": [{"category": "Strategy", "description": "Strategy Phase", "qty": 1, "rate_kes": 80000}]
            }

        raw_response = call_nim_api(system_prompt, user_prompt)
        parsed_json = _extract_json(raw_response)
        ProposalSchema(**parsed_json)
        return parsed_json
    except (ValidationError, json.JSONDecodeError, requests.exceptions.RequestException) as e:
        print(f"Agent call/validation failed: {e}. Retrying...")
        try:
            retry_prompt = user_prompt + f"\n\nPREVIOUS ERROR (Fix this in your new JSON response):\n{str(e)}"
            raw_response = call_nim_api(system_prompt, retry_prompt)
            parsed_json = _extract_json(raw_response)
            ProposalSchema(**parsed_json)
            return parsed_json
        except Exception as retry_e:
            print(f"Agent validation failed on retry: {retry_e}. Using fallback.")
            return {
                "approach": "Failed to generate approach",
                "scoped_deliverables": ["Error in generation"],
                "phased_timeline": ["TBD"],
                "team_shape": ["TBD"],
                "pricing": [{"category": "Error", "description": "Failed to parse pricing", "qty": 1, "rate_kes": 0}]
            }

