# The Exodus

**Turning stakeholder engagement into measurable change management.**

## The Problem
For a communications agency like GDF Kenya, a huge amount of producer and account-manager time goes into turning client conversations into usable internal documents. We listen back to meetings, write up briefs by hand, and turn second-round discussions into full client proposals—while cross-referencing rate cards and past work. It's slow, inconsistent, and relies heavily on manual translation of complex client signals. Time lost to write-ups is time lost to strategic thinking and change management.

## The Solution: The Exodus
The Exodus is a focused, two-agent system that sits directly on top of our real meeting workflow. It transforms raw transcripts into structured, actionable documents, giving our Account Managers a massive head start.

![Agent Architecture Diagram](https://dummyimage.com/800x300/18181b/4f46e5&text=Transcript+%E2%86%92+Brief+Generator+%E2%86%92+Proposal+Generator+%E2%86%92+Human+Review)

### How It Works
1. **Agent 1 (Brief Generator):** A Producer uploads a messy client meeting transcript. Agent 1 instantly parses the noise into a structured Production Brief (objectives, deliverables, timeline, budget, risks).
2. **Agent 2 (Proposal Generator):** Following a brief review meeting, the Producer uploads the second transcript. Agent 2 combines the existing Brief, the new Transcript, our agency Rate Card, and patterns from Past Projects to draft a comprehensive Client Proposal with a scoped pricing table.
3. **Human Review:** The Account Manager is always in the loop. They review the generated Proposal, edit inline, or send it back to the agent with notes. Nothing goes to a client without human approval.

## Demo Instructions (Under 2 Minutes)

To run the full stage demo:
1. Log in as **Producer** using the demo credentials (`producer` / `demo`).
2. Go to the **Dashboard** and select the "awaiting transcript" engagement for *KCB Bank Group*.
3. **Upload Transcript 1:** Paste the messy first-meeting transcript (or use a sample) and click "Generate Document". Watch the Brief Generator produce a clean brief in seconds.
4. **Upload Transcript 2:** The UI now asks for a Brief Review transcript. Paste the second transcript where the client changes the scope, and click "Generate Document". Watch the Proposal Generator produce a full proposal reflecting the changes.
5. **Human Review:** Log out, and log back in as **Account Manager** (`am` / `demo`). Open the same engagement.
6. Click **Approve** on the proposal. The pipeline is complete!

## Setup

1. **Backend:**
   ```bash
   cd backend
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt # (Flask, SQLAlchemy, pydantic, requests)
   export NIM_API_KEY="your_nvidia_nim_api_key"
   python seed.py
   flask run
   ```

2. **Frontend:**
   ```bash
   cd frontend
   npm install
   npm run dev
   ```

*Note: Ensure both servers are running. The Exodus uses SQLite for easy local development.*
