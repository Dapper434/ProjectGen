import json
from dotenv import load_dotenv

# Load .env before database.py reads DATABASE_URL, so seeding always targets
# the same database the Flask app (which also loads .env) will serve from.
load_dotenv()

from database import init_db, db_session
from models import User, Client, Engagement, Transcript, Brief, Proposal, RateCardItem, PastProject, AgentEvent
from werkzeug.security import generate_password_hash

def seed_db():
    init_db()

    # Clear existing data just in case
    db_session.query(AgentEvent).delete()
    db_session.query(User).delete()
    db_session.query(Proposal).delete()
    db_session.query(Brief).delete()
    db_session.query(Transcript).delete()
    db_session.query(Engagement).delete()
    db_session.query(Client).delete()
    db_session.query(RateCardItem).delete()
    db_session.query(PastProject).delete()
    
    db_session.commit()

    # 1. Users (Demo purposes)
    producer = User(username='producer', password_hash=generate_password_hash('demo'), role='Producer')
    account_manager = User(username='am', password_hash=generate_password_hash('demo'), role='Account Manager')
    db_session.add_all([producer, account_manager])
    db_session.commit()

    # 2. Clients
    bank = Client(name='KCB Bank Group', industry='Financial Services', notes='Mid-ERP-rollout, sensitive to employee pushback.')
    telco = Client(name='Safaricom', industry='Telecommunications', notes='Internal culture activation focused on agility and youth.')
    beverage = Client(name='EABL', industry='FMCG / Beverages', notes='Looking for creator campaigns to launch new malt variant.')
    db_session.add_all([bank, telco, beverage])
    db_session.commit()

    # 3. Seeded Engagement (Proposal Ready / In Review)
    eng_seeded = Engagement(client_id=telco.id, status='in_review')
    db_session.add(eng_seeded)
    db_session.commit()

    # Transcripts for seeded engagement
    t1_seeded = Transcript(
        engagement_id=eng_seeded.id,
        kind='client_meeting',
        raw_text='We need to launch our new internal culture manifesto. We want posters, a launch event, and some video testimonials from the executive team.',
        uploaded_by=producer.id
    )
    t2_seeded = Transcript(
        engagement_id=eng_seeded.id,
        kind='brief_review_meeting',
        raw_text='Actually, let us scratch the posters. Instead, focus heavily on the video testimonials and add a digital toolkit for branch managers. Also the event should be hybrid.',
        uploaded_by=producer.id
    )
    db_session.add_all([t1_seeded, t2_seeded])
    db_session.commit()

    brief_seeded_json = {
        "client": "Safaricom",
        "objectives": ["Launch internal culture manifesto", "Engage branch managers"],
        "audience": "Internal employees, specifically branch managers",
        "deliverables": ["Launch event", "Executive video testimonials", "Digital toolkit for managers"],
        "timeline_signals": "Launch next month",
        "budget_signals": "Standard internal comms budget",
        "key_stakeholders": ["HR Director", "CEO"],
        "risks": ["Low branch manager adoption"],
        "open_questions": []
    }
    brief_seeded_md = """# Production Brief: Safaricom Culture Activation
**Objectives:** Launch internal culture manifesto.
**Deliverables:** Hybrid launch event, Executive video testimonials, Digital Toolkit.
"""

    brief_seeded = Brief(
        engagement_id=eng_seeded.id,
        transcript_id=t1_seeded.id,
        structured_json=brief_seeded_json,
        rendered_markdown=brief_seeded_md,
        work_type='employee engagement'
    )
    db_session.add(brief_seeded)
    db_session.commit()

    proposal_seeded_json = {
        "approach": "A hybrid activation focusing on peer-led video messaging and decentralized toolkits.",
        "scoped_deliverables": ["Hybrid Event Production", "3x Executive Videos", "Branch Manager Toolkit (PDF/Canva)"],
        "phased_timeline": ["Week 1-2: Video Production", "Week 3: Toolkit Design", "Week 4: Event"],
        "team_shape": ["Project Manager", "Creative Director", "Video Producer"],
    }
    proposal_seeded_md = """# Proposal: Safaricom Culture Activation
## Approach
A hybrid activation focusing on peer-led video messaging and decentralized toolkits.

## Note on Changes
As discussed in the review meeting, posters have been removed in favor of a digital toolkit, and the event has been scoped as hybrid.

## Deliverables
- Hybrid Event Production
- 3x Executive Videos
- Branch Manager Toolkit (PDF/Canva)
"""
    pricing = [
        {"category": "Video Production", "description": "3x Executive Videos", "qty": 1, "rate_kes": 300000},
        {"category": "Strategy & Design", "description": "Branch Manager Toolkit", "qty": 1, "rate_kes": 150000},
        {"category": "Event Production", "description": "Hybrid Event Setup", "qty": 1, "rate_kes": 500000}
    ]

    proposal_seeded = Proposal(
        engagement_id=eng_seeded.id,
        brief_id=brief_seeded.id,
        review_transcript_id=t2_seeded.id,
        structured_json=proposal_seeded_json,
        rendered_markdown=proposal_seeded_md,
        pricing_line_items=pricing,
        status='in_review'
    )
    db_session.add(proposal_seeded)
    db_session.commit()

    # 4. In-Progress Engagement (Awaiting Transcript / Ready for Demo)
    eng_demo = Engagement(client_id=bank.id, status='awaiting_transcript')
    db_session.add(eng_demo)
    db_session.commit()

    # 5. Rate Card Items
    rates = [
        RateCardItem(category='Strategy', description='Senior Strategist Day Rate', unit='Day', rate_kes=80000),
        RateCardItem(category='Design', description='Creative Director Day Rate', unit='Day', rate_kes=90000),
        RateCardItem(category='Design', description='Graphic Designer Day Rate', unit='Day', rate_kes=40000),
        RateCardItem(category='Video', description='Standard Shoot Day (1 Cam, 1 Crew)', unit='Day', rate_kes=120000),
        RateCardItem(category='Video', description='Video Editing (Per Day)', unit='Day', rate_kes=50000),
        RateCardItem(category='Project Management', description='Account Director (Retainer/Monthly)', unit='Month', rate_kes=250000),
        RateCardItem(category='Project Management', description='Producer (Day Rate)', unit='Day', rate_kes=60000)
    ]
    db_session.add_all(rates)

    # 6. Past Projects
    projects = [
        PastProject(
            client_type='Financial Services',
            work_type='change-management campaign',
            summary='Led the change comms for a major banking core system migration over 6 months.',
            deliverables_used='["Weekly newsletter", "Change Champions network", "Training videos", "Townhall presentations"]',
            typical_pricing_notes='Usually requires heavily embedded project management (approx 25% of budget) and significant video production for training.'
        ),
        PastProject(
            client_type='FMCG',
            work_type='creator campaign',
            summary='Managed 15 micro-influencers for a new energy drink launch.',
            deliverables_used='["Influencer sourcing", "Content guidelines", "Contracting", "Performance reporting"]',
            typical_pricing_notes='Creator fees are pass-through, agency charges 20% management fee plus flat strategy fee.'
        )
    ]
    db_session.add_all(projects)

    db_session.commit()
    print("Database seeded successfully.")

if __name__ == '__main__':
    seed_db()
