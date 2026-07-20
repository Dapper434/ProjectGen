import os
from flask import Flask, request, jsonify, session
from flask_cors import CORS
from database import db_session, init_db
from models import User, Client, Engagement, Transcript, Brief, Proposal, RateCardItem, PastProject, AgentEvent
from werkzeug.security import check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'super-secret-demo-key')
CORS(app, supports_credentials=True)

@app.teardown_appcontext
def shutdown_session(exception=None):
    db_session.remove()

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    print("Received login request:", data)
    
    if not data:
        print("Request JSON is missing or None. Headers:", request.headers)
        return jsonify({"error": "No JSON data"}), 400
        
    username = data.get('username')
    password = data.get('password')
    role = data.get('role') # User selects role in demo
    
    print(f"Attempting login for user: {username}, password: {password}")

    user = db_session.query(User).filter_by(username=username).first()
    print("User found in DB:", user)
    
    if user:
        is_valid = check_password_hash(user.password_hash, password)
        print("Password check result:", is_valid)
        if is_valid:
            session['user_id'] = user.id
            session['role'] = role or user.role
            return jsonify({"message": "Logged in successfully", "role": session['role']})
    else:
        print("User not found.")
    
    return jsonify({"error": "Invalid credentials"}), 401

@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({"message": "Logged out"})

@app.route('/api/me', methods=['GET'])
def me():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"error": "Not logged in"}), 401
    
    user = db_session.query(User).get(user_id)
    return jsonify({
        "username": user.username,
        "role": session.get('role')
    })

@app.route('/api/engagements', methods=['GET', 'POST'])
def engagements_list():
    if request.method == 'POST':
        # Create a new engagement for the first client (for demo purposes)
        client = db_session.query(Client).first()
        if not client:
            return jsonify({"error": "No clients found"}), 400
        
        new_eng = Engagement(client_id=client.id, status='awaiting_transcript')
        db_session.add(new_eng)
        db_session.commit()
        return jsonify({"id": new_eng.id, "client_name": client.name, "status": new_eng.status})
        
    # GET method
    engagements = db_session.query(Engagement).all()
    result = []
    for eng in engagements:
        result.append({
            "id": eng.id,
            "client_name": eng.client.name,
            "status": eng.status
        })
    return jsonify(result)

@app.route('/api/engagements/<int:eng_id>', methods=['GET'])
def get_engagement(eng_id):
    eng = db_session.query(Engagement).get(eng_id)
    if not eng:
        return jsonify({"error": "Not found"}), 404
    
    brief = db_session.query(Brief).filter_by(engagement_id=eng_id).order_by(Brief.id.desc()).first()
    proposal = db_session.query(Proposal).filter_by(engagement_id=eng_id).order_by(Proposal.id.desc()).first()
    events = db_session.query(AgentEvent).filter_by(engagement_id=eng_id).order_by(AgentEvent.created_at.asc()).all()
    
    return jsonify({
        "id": eng.id,
        "client_name": eng.client.name,
        "status": eng.status,
        "brief": {
            "id": brief.id,
            "structured_json": brief.structured_json,
            "rendered_markdown": brief.rendered_markdown
        } if brief else None,
        "proposal": {
            "id": proposal.id,
            "structured_json": proposal.structured_json,
            "rendered_markdown": proposal.rendered_markdown,
            "pricing_line_items": proposal.pricing_line_items,
            "status": proposal.status
        } if proposal else None,
        "events": [
            {
                "agent": e.agent,
                "reasoning_summary": e.reasoning_summary,
                "created_at": e.created_at.isoformat()
            } for e in events
        ]
    })

@app.route('/api/engagements/<int:eng_id>/transcripts', methods=['POST'])
def upload_transcript(eng_id):
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401
    
    data = request.json
    raw_text = data.get('raw_text')
    if not raw_text:
        return jsonify({"error": "No transcript provided"}), 400

    eng = db_session.query(Engagement).get(eng_id)
    if not eng:
        return jsonify({"error": "Engagement not found"}), 404

    from agents import generate_brief, render_brief_markdown

    if eng.status == 'awaiting_transcript':
        # Agent 1 Flow
        transcript = Transcript(engagement_id=eng_id, kind='client_meeting', raw_text=raw_text, uploaded_by=user_id)
        db_session.add(transcript)
        db_session.flush()

        try:
            brief_json = generate_brief(raw_text, eng.client.name)
            brief_md = render_brief_markdown(brief_json)
            
            brief = Brief(
                engagement_id=eng_id,
                transcript_id=transcript.id,
                structured_json=brief_json,
                rendered_markdown=brief_md,
                work_type=brief_json.get('work_type', 'unknown')
            )
            eng.status = 'brief_ready'
            db_session.add(brief)
            
            # Create Agent Event
            ev = AgentEvent(
                engagement_id=eng_id,
                agent='Brief Generator',
                trigger='client_meeting_transcript_upload',
                reasoning_summary='Processed initial client transcript to generate structured production brief.',
                action='Created Brief',
                tokens_used=0 # Ignored for this demo
            )
            db_session.add(ev)
            db_session.commit()
            
            return jsonify({"message": "Brief generated successfully"})
        except Exception as e:
            db_session.rollback()
            return jsonify({"error": f"Agent failed: {str(e)}"}), 500

    elif eng.status == 'awaiting_review_transcript' or eng.status == 'brief_ready':
        # Agent 2 Flow
        transcript = Transcript(engagement_id=eng_id, kind='brief_review_meeting', raw_text=raw_text, uploaded_by=user_id)
        db_session.add(transcript)
        db_session.flush()

        brief = db_session.query(Brief).filter_by(engagement_id=eng_id).order_by(Brief.id.desc()).first()
        if not brief:
            db_session.rollback()
            return jsonify({"error": "No brief found for this engagement"}), 400

        from models import PastProject, RateCardItem
        from agents import generate_proposal, render_proposal_markdown

        past_projects = db_session.query(PastProject).limit(3).all()
        rate_card = db_session.query(RateCardItem).all()

        try:
            proposal_json = generate_proposal(raw_text, brief, eng.client.name, past_projects, rate_card)
            proposal_md = render_proposal_markdown(proposal_json, eng.client.name)
            
            proposal = Proposal(
                engagement_id=eng_id,
                brief_id=brief.id,
                review_transcript_id=transcript.id,
                structured_json=proposal_json,
                rendered_markdown=proposal_md,
                pricing_line_items=proposal_json.get('pricing', []),
                status='draft'
            )
            eng.status = 'proposal_ready'
            db_session.add(proposal)
            
            # Create Agent Event
            ev = AgentEvent(
                engagement_id=eng_id,
                agent='Proposal Generator',
                trigger='review_meeting_transcript_upload',
                reasoning_summary='Combined brief, review notes, rate card, and past projects to draft a full client proposal.',
                action='Created Proposal',
                tokens_used=0
            )
            db_session.add(ev)
            db_session.commit()
            
            return jsonify({"message": "Proposal generated successfully"})
        except Exception as e:
            db_session.rollback()
            return jsonify({"error": f"Agent 2 failed: {str(e)}"}), 500

    return jsonify({"error": "Invalid engagement state for upload"}), 400

@app.route('/api/engagements/<int:eng_id>/proposals/review', methods=['POST'])
def review_proposal(eng_id):
    user_id = session.get('user_id')
    role = session.get('role')
    if not user_id or role != 'Account Manager':
        return jsonify({"error": "Unauthorized. Account Manager role required."}), 403
    
    data = request.json
    action = data.get('action') # 'approve' or 'send_back'
    notes = data.get('notes', '')

    eng = db_session.query(Engagement).get(eng_id)
    if not eng:
        return jsonify({"error": "Engagement not found"}), 404

    proposal = db_session.query(Proposal).filter_by(engagement_id=eng_id).order_by(Proposal.id.desc()).first()
    if not proposal:
        return jsonify({"error": "No proposal found"}), 404

    if action == 'approve':
        proposal.status = 'approved'
        eng.status = 'approved'
        ev = AgentEvent(
            engagement_id=eng_id,
            agent='Account Manager (Human)',
            trigger='proposal_review',
            reasoning_summary='Reviewed and approved the proposal.',
            action='Approved Proposal',
            tokens_used=0
        )
        db_session.add(ev)
        db_session.commit()
        return jsonify({"message": "Proposal approved"})
        
    elif action == 'send_back':
        # Re-run Agent 2 with notes
        from models import PastProject, RateCardItem
        from agents import generate_proposal, render_proposal_markdown
        
        brief = db_session.query(Brief).filter_by(engagement_id=eng_id).order_by(Brief.id.desc()).first()
        transcript = db_session.query(Transcript).get(proposal.review_transcript_id)
        
        past_projects = db_session.query(PastProject).limit(3).all()
        rate_card = db_session.query(RateCardItem).all()
        
        try:
            proposal_json = generate_proposal(transcript.raw_text, brief, eng.client.name, past_projects, rate_card, additional_notes=notes)
            proposal_md = render_proposal_markdown(proposal_json, eng.client.name)
            
            new_proposal = Proposal(
                engagement_id=eng_id,
                brief_id=brief.id,
                review_transcript_id=transcript.id,
                structured_json=proposal_json,
                rendered_markdown=proposal_md,
                pricing_line_items=proposal_json.get('pricing', []),
                status='in_review',
                version=proposal.version + 1
            )
            eng.status = 'in_review'
            db_session.add(new_proposal)
            
            ev = AgentEvent(
                engagement_id=eng_id,
                agent='Proposal Generator',
                trigger='manager_send_back',
                reasoning_summary=f'Regenerated proposal incorporating manager feedback: {notes}',
                action='Regenerated Proposal',
                tokens_used=0
            )
            db_session.add(ev)
            db_session.commit()
            
            return jsonify({"message": "Proposal regenerated with notes"})
        except Exception as e:
            db_session.rollback()
            return jsonify({"error": f"Agent 2 failed on regeneration: {str(e)}"}), 500

    return jsonify({"error": "Invalid action"}), 400

@app.route('/api/rate-card', methods=['GET'])
def get_rate_card():
    items = db_session.query(RateCardItem).all()
    return jsonify([{
        "category": item.category,
        "description": item.description,
        "unit": item.unit,
        "rate_kes": item.rate_kes
    } for item in items])

if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5000)
