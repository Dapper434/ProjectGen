import os
from flask import Flask, request, jsonify, session, send_file
from flask_cors import CORS
from database import db_session, init_db
from models import User, Client, Engagement, Transcript, Brief, Proposal, RateCardItem, PastProject, AgentEvent
from werkzeug.security import check_password_hash
from weasyprint import HTML
import io
import html
from datetime import datetime

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
        data = request.get_json(silent=True) or {}
        client_id = data.get('client_id')

        if not isinstance(client_id, int):
            return jsonify({"error": "A valid client_id is required"}), 400

        client = db_session.get(Client, client_id)
        if not client:
            return jsonify({"error": "Client not found"}), 404
        
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

@app.route('/api/clients', methods=['GET', 'POST'])
def clients_list():
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        name = (data.get('name') or '').strip()
        industry = (data.get('industry') or '').strip()
        notes = (data.get('notes') or '').strip()

        if not name:
            return jsonify({"error": "Company name is required"}), 400

        existing_client = db_session.query(Client).filter(Client.name.ilike(name)).first()
        if existing_client:
            return jsonify({"error": "A company with that name already exists"}), 409

        client = Client(name=name, industry=industry or None, notes=notes or None)
        db_session.add(client)
        db_session.commit()
        return jsonify({"id": client.id, "name": client.name}), 201

    clients = db_session.query(Client).order_by(Client.name.asc()).all()
    return jsonify([
        {"id": client.id, "name": client.name}
        for client in clients
    ])

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

    from agents import generate_brief

    if eng.status == 'awaiting_transcript':
        # Agent 1 Flow
        transcript = Transcript(engagement_id=eng_id, kind='client_meeting', raw_text=raw_text, uploaded_by=user_id)
        db_session.add(transcript)
        db_session.flush()

        try:
            brief_json = generate_brief(raw_text, eng.client.name)
            brief_md = brief_json.get('rendered_markdown', '')
            
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
        from agents import generate_proposal

        past_projects = db_session.query(PastProject).limit(3).all()
        rate_card = db_session.query(RateCardItem).all()

        try:
            proposal_json = generate_proposal(raw_text, brief, eng.client.name, past_projects, rate_card)
            proposal_md = proposal_json.get('rendered_markdown', '')
            extracted_signals = proposal_json.get('extracted_signals', '')
            
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
            
            # Create Agent Event for Proposal Generation
            ev = AgentEvent(
                engagement_id=eng_id,
                agent='Proposal Generator',
                trigger='review_meeting_transcript_upload',
                reasoning_summary='Combined brief, review notes, rate card, and past projects to draft a full client proposal.',
                action='Created Proposal',
                tokens_used=0
            )
            db_session.add(ev)

            # Create Agent Event for Extracted Signals (B1)
            ev_signals = AgentEvent(
                engagement_id=eng_id,
                agent='Signal Extractor',
                trigger='review_meeting_transcript_upload',
                reasoning_summary=extracted_signals,
                action='Extracted Meeting Signals',
                tokens_used=0
            )
            db_session.add(ev_signals)
            
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
        from agents import generate_proposal
        
        brief = db_session.query(Brief).filter_by(engagement_id=eng_id).order_by(Brief.id.desc()).first()
        transcript = db_session.query(Transcript).get(proposal.review_transcript_id)
        
        past_projects = db_session.query(PastProject).limit(3).all()
        rate_card = db_session.query(RateCardItem).all()
        
        try:
            proposal_json = generate_proposal(transcript.raw_text, brief, eng.client.name, past_projects, rate_card, additional_notes=notes)
            proposal_md = proposal_json.get('rendered_markdown', '')
            extracted_signals = proposal_json.get('extracted_signals', '')
            
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

            ev_signals = AgentEvent(
                engagement_id=eng_id,
                agent='Signal Extractor',
                trigger='manager_send_back',
                reasoning_summary=extracted_signals,
                action='Extracted Meeting Signals',
                tokens_used=0
            )
            db_session.add(ev_signals)

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

# ---------------------------------------------------------------------------
# PDF Generation Helpers
# ---------------------------------------------------------------------------
# These build the PDF straight from each document's structured_json, mirroring
# the on-screen report layout, rather than round-tripping through markdown.

def _esc(value):
    return html.escape(str(value)) if value is not None else ''


def _bullets(items, empty_text='None noted'):
    items = [i for i in (items or []) if i]
    if not items:
        return f'<p class="muted">{_esc(empty_text)}</p>'
    lis = ''.join(f'<li>{_esc(i)}</li>' for i in items)
    return f'<ul>{lis}</ul>'


def _tags(items, empty_text):
    items = [i for i in (items or []) if i]
    if not items:
        return f'<p class="muted">{_esc(empty_text)}</p>'
    return ''.join(f'<span class="tag">{_esc(i)}</span>' for i in items)


PDF_STYLE = '''
  @page {
    size: A4;
    margin: 0;
    @bottom-center {
      content: counter(page) " / " counter(pages);
      font-size: 8.5pt;
      color: #9ca3af;
      font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
    }
  }
  * { box-sizing: border-box; }
  body {
    font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
    font-size: 10.5pt;
    line-height: 1.6;
    color: #374151;
    margin: 0;
  }
  .banner { background: linear-gradient(135deg, ACCENT_FROM, ACCENT_TO); color: #ffffff; padding: 16mm 16mm 12mm 16mm; }
  .banner .eyebrow { font-size: 8.5pt; letter-spacing: 0.15em; text-transform: uppercase; opacity: 0.85; margin: 0 0 8px 0; }
  .banner h1 { font-size: 24pt; margin: 0; color: #ffffff; font-weight: 700; }
  .banner .badge { display: inline-block; background: rgba(255,255,255,0.18); padding: 4px 13px; border-radius: 999px; font-size: 9pt; margin-top: 12px; }
  .body { padding: 14mm 16mm 4mm 16mm; }
  .section { margin-bottom: 20px; }
  .section-label { font-size: 8.5pt; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase; color: ACCENT_FROM; margin: 0 0 8px 0; }
  .muted { color: #9ca3af; font-style: italic; margin: 0; }
  .info-grid { display: flex; gap: 12px; margin-bottom: 22px; }
  .info-box { flex: 1; background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px; padding: 11px 14px; }
  .info-box .label { font-size: 8pt; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: #9ca3af; margin-bottom: 3px; }
  .info-box .value { font-size: 10pt; color: #111827; }
  .tag { display: inline-block; font-size: 9pt; padding: 4px 11px; border-radius: 999px; margin: 0 6px 6px 0; background: ACCENT_TINT; color: ACCENT_FROM; border: 1px solid ACCENT_TINT_BORDER; }
  .callout { border-radius: 8px; padding: 13px 16px; margin-bottom: 20px; background: #fffbeb; border: 1px solid #fde68a; color: #92400e; }
  .callout .section-label { color: #92400e; }
  ul { margin: 0; padding-left: 20px; }
  li { margin-bottom: 6px; }
  p { margin: 0; }
  table.pricing { width: 100%; border-collapse: collapse; font-size: 9.5pt; margin-top: 6px; }
  table.pricing th { background: #f3f4f6; color: #6b7280; font-weight: 600; text-align: left; padding: 9px 12px; border: 1px solid #e5e7eb; }
  table.pricing td { padding: 9px 12px; border: 1px solid #e5e7eb; }
  table.pricing tfoot td { font-weight: 700; color: #111827; border-top: 2px solid #111827; background: #f9fafb; }
  .footer { padding: 14px 16mm 24px 16mm; border-top: 1px solid #e5e7eb; font-size: 8.5pt; color: #9ca3af; text-align: center; margin-top: 10px; }
'''


def _pdf_shell(accent_from, accent_to, accent_tint, accent_tint_border, eyebrow, heading, badge, body_html):
    style = (PDF_STYLE
             .replace('ACCENT_TINT_BORDER', accent_tint_border)
             .replace('ACCENT_TINT', accent_tint)
             .replace('ACCENT_FROM', accent_from)
             .replace('ACCENT_TO', accent_to))
    badge_html = f'<span class="badge">{_esc(badge)}</span>' if badge else ''
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<style>{style}</style>
</head>
<body>
<div class="banner">
  <p class="eyebrow">FactoryOS &middot; {_esc(eyebrow)}</p>
  <h1>{_esc(heading)}</h1>
  {badge_html}
</div>
<div class="body">
{body_html}
</div>
<div class="footer">Generated by FactoryOS on {datetime.now().strftime('%B %d, %Y')}</div>
</body>
</html>'''


def build_brief_pdf_html(brief, client_name):
    data = brief.structured_json or {}
    work_type = (data.get('work_type') or '').replace('-', ' ').title()

    body = f'''
      <div class="section">
        <p class="section-label">Objectives</p>
        {_bullets(data.get('objectives'))}
      </div>
      <div class="section">
        <p class="section-label">Audience</p>
        <p>{_esc(data.get('audience') or 'Not specified')}</p>
      </div>
      <div class="section">
        <p class="section-label">Deliverables</p>
        {_bullets(data.get('deliverables'))}
      </div>
      <div class="info-grid">
        <div class="info-box">
          <div class="label">Timeline</div>
          <div class="value">{_esc(data.get('timeline_signals') or 'TBD')}</div>
        </div>
        <div class="info-box">
          <div class="label">Budget</div>
          <div class="value">{_esc(data.get('budget_signals') or 'TBD')}</div>
        </div>
      </div>
      <div class="section">
        <p class="section-label">Key Stakeholders</p>
        {_tags(data.get('key_stakeholders'), 'None noted')}
      </div>
      {f'<div class="callout"><p class="section-label">Risks</p>{_bullets(data.get("risks"))}</div>' if data.get('risks') else ''}
      {f'<div class="section"><p class="section-label">Open Questions</p>{_bullets(data.get("open_questions"))}</div>' if data.get('open_questions') else ''}
    '''

    return _pdf_shell(
        accent_from='#4f46e5', accent_to='#4338ca',
        accent_tint='#eef2ff', accent_tint_border='#e0e7ff',
        eyebrow='Production Brief',
        heading=client_name,
        badge=work_type or None,
        body_html=body
    )


def build_proposal_pdf_html(proposal, client_name):
    data = proposal.structured_json or {}
    pricing_items = proposal.pricing_line_items or []

    rows = ''
    grand_total = 0
    for item in pricing_items:
        qty = item.get('qty', 1) or 1
        rate = item.get('rate_kes', 0) or 0
        line_total = qty * rate
        grand_total += line_total
        rows += f'''
          <tr>
            <td>{_esc(item.get('category', ''))}</td>
            <td>{_esc(item.get('description', ''))}</td>
            <td style="text-align:center;">{qty}</td>
            <td style="text-align:right;">KES {rate:,}</td>
            <td style="text-align:right;">KES {line_total:,}</td>
          </tr>'''

    pricing_html = ''
    if pricing_items:
        pricing_html = f'''
          <div class="section">
            <p class="section-label">Pricing Structure</p>
            <table class="pricing">
              <thead>
                <tr>
                  <th>Category</th><th>Description</th><th style="text-align:center;">Qty</th>
                  <th style="text-align:right;">Rate (KES)</th><th style="text-align:right;">Total (KES)</th>
                </tr>
              </thead>
              <tbody>{rows}</tbody>
              <tfoot>
                <tr>
                  <td colspan="4" style="text-align:right;">Total Investment</td>
                  <td style="text-align:right;">KES {grand_total:,}</td>
                </tr>
              </tfoot>
            </table>
          </div>'''

    body = f'''
      <div class="section">
        <p class="section-label">Approach</p>
        <p>{_esc(data.get('approach') or 'Not specified')}</p>
      </div>
      <div class="section">
        <p class="section-label">Scoped Deliverables</p>
        {_bullets(data.get('scoped_deliverables'))}
      </div>
      <div class="section">
        <p class="section-label">Phased Timeline</p>
        {_bullets(data.get('phased_timeline'))}
      </div>
      <div class="section">
        <p class="section-label">Team Shape</p>
        {_tags(data.get('team_shape'), 'Not specified')}
      </div>
      {pricing_html}
    '''

    return _pdf_shell(
        accent_from='#059669', accent_to='#047857',
        accent_tint='#ecfdf5', accent_tint_border='#d1fae5',
        eyebrow='Client Proposal',
        heading=client_name,
        badge='Approved' if proposal.status == 'approved' else None,
        body_html=body
    )


@app.route('/api/engagements/<int:eng_id>/brief/pdf', methods=['GET'])
def download_brief_pdf(eng_id):
    eng = db_session.query(Engagement).get(eng_id)
    if not eng:
        return jsonify({"error": "Engagement not found"}), 404

    brief = db_session.query(Brief).filter_by(engagement_id=eng_id).order_by(Brief.id.desc()).first()
    if not brief:
        return jsonify({"error": "No brief found for this engagement"}), 404

    try:
        html_content = build_brief_pdf_html(brief, eng.client.name)
        pdf_buffer = io.BytesIO()
        HTML(string=html_content).write_pdf(pdf_buffer)
        pdf_buffer.seek(0)

        filename = f"{eng.client.name.replace(' ', '_')}_Production_Brief.pdf"
        return send_file(
            pdf_buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        return jsonify({"error": f"PDF generation failed: {str(e)}"}), 500


@app.route('/api/engagements/<int:eng_id>/proposal/pdf', methods=['GET'])
def download_proposal_pdf(eng_id):
    eng = db_session.query(Engagement).get(eng_id)
    if not eng:
        return jsonify({"error": "Engagement not found"}), 404

    proposal = db_session.query(Proposal).filter_by(engagement_id=eng_id).order_by(Proposal.id.desc()).first()
    if not proposal:
        return jsonify({"error": "No proposal found for this engagement"}), 404

    try:
        html_content = build_proposal_pdf_html(proposal, eng.client.name)
        pdf_buffer = io.BytesIO()
        HTML(string=html_content).write_pdf(pdf_buffer)
        pdf_buffer.seek(0)

        filename = f"{eng.client.name.replace(' ', '_')}_Client_Proposal.pdf"
        return send_file(
            pdf_buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        return jsonify({"error": f"PDF generation failed: {str(e)}"}), 500


if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5000)
