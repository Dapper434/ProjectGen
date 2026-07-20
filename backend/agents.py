import os
import json
import requests
from pydantic import BaseModel, Field, ValidationError
from typing import List
from models import Brief, Proposal, AgentEvent
from database import db_session

NIM_API_KEY = os.environ.get("NIM_API_KEY", "")
NIM_MODEL = os.environ.get("NIM_MODEL", "meta/llama-3.1-70b-instruct")

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
    
    response = requests.post(url, headers=headers, json=payload)
    response.raise_for_status()
    data = response.json()
    return data['choices'][0]['message']['content']

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
            # Fallback for demo if no API key is provided
            print("WARNING: No NIM_API_KEY provided. Using dummy brief generator.")
            return {
                "client": client_name,
                "objectives": ["Understand transcript objectives (dummy)"],
                "audience": "Target audience (dummy)",
                "deliverables": ["Deliverable 1", "Deliverable 2"],
                "timeline_signals": "Q4",
                "budget_signals": "TBD",
                "key_stakeholders": ["Marketing"],
                "risks": ["No API Key"],
                "open_questions": ["What is the real brief?"],
                "work_type": "event"
            }

        raw_response = call_nim_api(system_prompt, user_prompt)
        
        # Strip potential markdown code blocks
        if raw_response.startswith("```json"):
            raw_response = raw_response[7:-3]
        elif raw_response.startswith("```"):
            raw_response = raw_response[3:-3]
            
        parsed_json = json.loads(raw_response)
        
        # Validate schema
        ProductionBriefSchema(**parsed_json)
        return parsed_json
        
    except (ValidationError, json.JSONDecodeError) as e:
        print(f"Agent validation failed: {e}. Retrying...")
        try:
            # Retry once
            retry_prompt = user_prompt + f"\n\nPREVIOUS ERROR (Fix this in your new JSON response):\n{str(e)}"
            raw_response = call_nim_api(system_prompt, retry_prompt)
            if raw_response.startswith("```json"):
                raw_response = raw_response[7:-3]
            elif raw_response.startswith("```"):
                raw_response = raw_response[3:-3]
            
            parsed_json = json.loads(raw_response)
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
"""

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
            print("WARNING: No NIM_API_KEY provided. Using dummy proposal generator.")
            return {
                "approach": "Dummy approach based on new transcript",
                "scoped_deliverables": brief.structured_json.get("deliverables", []) + ["New Dummy Deliverable"],
                "phased_timeline": ["Week 1: Strategy", "Week 2: Execution"],
                "team_shape": ["Strategist", "Designer"],
                "pricing": [{"category": "Strategy", "description": "Strategy Phase", "qty": 1, "rate_kes": 80000}]
            }

        raw_response = call_nim_api(system_prompt, user_prompt)
        if raw_response.startswith("```json"):
            raw_response = raw_response[7:-3]
        elif raw_response.startswith("```"):
            raw_response = raw_response[3:-3]
            
        parsed_json = json.loads(raw_response)
        ProposalSchema(**parsed_json)
        return parsed_json
    except (ValidationError, json.JSONDecodeError) as e:
        print(f"Agent validation failed: {e}. Retrying...")
        try:
            retry_prompt = user_prompt + f"\n\nPREVIOUS ERROR (Fix this in your new JSON response):\n{str(e)}"
            raw_response = call_nim_api(system_prompt, retry_prompt)
            if raw_response.startswith("```json"):
                raw_response = raw_response[7:-3]
            elif raw_response.startswith("```"):
                raw_response = raw_response[3:-3]
            
            parsed_json = json.loads(raw_response)
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

