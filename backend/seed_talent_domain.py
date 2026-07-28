"""Seed the WP-9 talent domain: skills, certifications, events, token history.

Idempotent. Enriches the talents seed_talents.py already created rather than
replacing them, and gives them varied `last_assigned_at` values so idle accrual
is actually visible in the UI instead of every balance looking the same.
"""
import datetime
import json
import random

from dotenv import load_dotenv

load_dotenv()

from authoritative import REGISTRY, create_version
from database import db_session, init_db
from models import (Certification, CertificationEnrollment, Event, Skill, Talent,
                    TalentSkill, TokenLedger)

SKILLS = [
    ('Cinematography', 'craft'), ('Editing', 'craft'), ('Colour Grading', 'craft'),
    ('Sound Design', 'craft'), ('Motion Graphics', 'craft'), ('Art Direction', 'craft'),
    ('Producing', 'production'), ('Line Producing', 'production'), ('Scheduling', 'production'),
    ('Drone Operation', 'craft'), ('Set Safety', 'safety'), ('Lighting', 'craft'),
    ('Scriptwriting', 'creative'), ('Photography', 'craft'), ('Adobe Premiere', 'software'),
    ('DaVinci Resolve', 'software'), ('After Effects', 'software'),
]

CERT_CATALOG = {
    "certifications": [
        {"key": "set_safety_l1", "name": "On-Set Safety Level 1", "provider": "GDF Academy",
         "category": "safety", "token_award": 15, "validity_months": 24,
         "grants_skill": "Set Safety", "pass_mark": 0.8, "cooldown_hours": 24,
         "questions": [
             {"q": "A crew member reports a frayed power cable on set. What is the correct first action?",
              "options": ["Tape over it and continue", "Isolate the circuit and tag the cable out of service",
                          "Finish the current take, then report it", "Swap it with a spare mid-take"],
              "answer": 1},
             {"q": "Who is responsible for calling a halt when a set becomes unsafe?",
              "options": ["Only the director", "Only the safety officer",
                          "Anyone on the crew", "Only the producer"],
              "answer": 2},
             {"q": "Before a night shoot in a public area, what must be confirmed?",
              "options": ["Catering numbers", "Permits, lighting plan and traffic management",
                          "Social media coverage", "Wardrobe continuity"],
              "answer": 1},
             {"q": "What is the minimum safe distance for a drone from uninvolved people in Kenya?",
              "options": ["It does not matter outdoors", "Whatever the pilot judges safe",
                          "The distance set by KCAA regulations for the operating category",
                          "Five metres in all cases"],
              "answer": 2},
             {"q": "When does a risk assessment need updating?",
              "options": ["Only at the start of production", "Whenever the location, cast or activity changes",
                          "Once a year", "Only after an incident"],
              "answer": 1},
         ]},
        {"key": "colour_craft", "name": "Colour Grading Craft", "provider": "GDF Academy",
         "category": "craft", "token_award": 30, "validity_months": 36,
         "grants_skill": "Colour Grading", "pass_mark": 0.8, "cooldown_hours": 24,
         "questions": [
             {"q": "What does a scope's waveform primarily show?",
              "options": ["Colour saturation", "Luminance distribution", "Audio levels", "Frame rate"],
              "answer": 1},
             {"q": "Rec.709 is a standard for:",
              "options": ["Audio mastering", "HD television colour space", "File compression", "Lens mounts"],
              "answer": 1},
             {"q": "Which correction should generally come first?",
              "options": ["Secondary skin-tone work", "Creative look", "Primary balance and exposure", "Vignette"],
              "answer": 2},
             {"q": "Log footage is captured to:",
              "options": ["Reduce file size", "Preserve dynamic range for grading",
                          "Improve autofocus", "Increase frame rate"],
              "answer": 1},
             {"q": "What is a LUT?",
              "options": ["A lens type", "A lookup table mapping input colour values to output",
                          "A lighting unit", "A codec"],
              "answer": 1},
         ]},
        {"key": "premiere_pro", "name": "Adobe Premiere Pro Proficiency", "provider": "GDF Academy",
         "category": "software", "token_award": 20, "validity_months": 24,
         "grants_skill": "Adobe Premiere", "pass_mark": 0.8, "cooldown_hours": 24,
         "questions": [
             {"q": "What does a proxy workflow solve?",
              "options": ["Colour accuracy", "Editing performance on heavy source media",
                          "Audio sync", "Export quality"],
              "answer": 1},
             {"q": "Nested sequences are used to:",
              "options": ["Group and treat a set of clips as one", "Reduce file size",
                          "Change frame rate", "Add subtitles"],
              "answer": 0},
             {"q": "Which panel manages media relinking?",
              "options": ["Effects", "Project", "Lumetri", "Essential Sound"],
              "answer": 1},
             {"q": "A J-cut is:",
              "options": ["A transition wipe", "Audio leading the incoming video",
                          "A colour effect", "An export preset"],
              "answer": 1},
             {"q": "What is the safest way to hand a project to another editor?",
              "options": ["Send the sequence file only", "Project Manager consolidate and transcode",
                          "Screen-record the timeline", "Export a flat MP4"],
              "answer": 1},
         ]},
    ]
}


def main():
    init_db()

    skills = {}
    for name, category in SKILLS:
        row = db_session.query(Skill).filter_by(name=name).first()
        if not row:
            row = Skill(name=name, category=category)
            db_session.add(row)
        skills[name] = row
    db_session.commit()

    for entry in CERT_CATALOG['certifications']:
        cert = db_session.query(Certification).filter_by(key=entry['key']).first()
        if not cert:
            cert = Certification(key=entry['key'])
            db_session.add(cert)
        cert.name = entry['name']
        cert.provider = entry['provider']
        cert.category = entry['category']
        cert.token_award = entry['token_award']
        cert.validity_months = entry['validity_months']
        cert.is_mock = True
        grant = entry.get('grants_skill')
        cert.grants_skill_id = skills[grant].id if grant in skills else None
    db_session.commit()

    existing = db_session.query(Certification).count()
    doc = db_session.query(__import__('models').AuthoritativeDoc).filter_by(
        key='certification_catalog', scope_type='global', is_active=True).first()
    if not doc:
        create_version('certification_catalog', 'global', None,
                       REGISTRY['certification_catalog']['title'], 'json',
                       json.dumps(CERT_CATALOG, indent=2),
                       note='Seeded from seed_talent_domain.py, including the mock quiz questions.')
        db_session.commit()

    now = datetime.datetime.utcnow()
    for name, kind, days, award, code in [
        ('Nairobi Production Meetup', 'meetup', -14, 10, 'MEETUP24'),
        ('Safety Refresher Workshop', 'workshop', -3, 10, 'SAFE2026'),
        ('GDF Crew Day', 'social', 21, 10, 'CREWDAY'),
    ]:
        event = db_session.query(Event).filter_by(checkin_code=code).first()
        if not event:
            db_session.add(Event(
                name=name, kind=kind, token_award=award, checkin_code=code,
                location='Nairobi',
                starts_at=now + datetime.timedelta(days=days),
                ends_at=now + datetime.timedelta(days=days, hours=4),
            ))
    db_session.commit()

    # Enrich existing talents: emails, engagement type, and — importantly —
    # varied last_assigned_at so idle accrual differs across the bench.
    rng = random.Random(42)          # deterministic seed data
    talents = db_session.query(Talent).order_by(Talent.id).all()
    for i, t in enumerate(talents):
        if not t.email:
            slug = ''.join(c for c in (t.name or f'talent{t.id}').lower() if c.isalnum() or c == ' ')
            t.email = f"{slug.replace(' ', '.')}@example.com"
        t.engagement_type = t.engagement_type or ('inhouse' if i % 4 == 0 else 'contract')
        t.status = t.status or 'active'
        t.seniority = t.seniority or rng.choice(['junior', 'mid', 'senior', 'lead'])
        t.created_at = t.created_at or (now - datetime.timedelta(days=400))
        if t.last_assigned_at is None:
            t.last_assigned_at = now - datetime.timedelta(days=rng.choice([0, 2, 5, 12, 30, 45, 90]))
        if t.avg_rating is None and rng.random() > 0.35:
            t.avg_rating = round(rng.uniform(3.5, 5.0), 1)

        for phrase in (t.skills or [])[:4]:
            match = next((s for s in skills if s.lower() in str(phrase).lower()
                          or str(phrase).lower() in s.lower()), None)
            if match:
                link = db_session.query(TalentSkill).filter_by(
                    talent_id=t.id, skill_id=skills[match].id).first()
                if not link:
                    db_session.add(TalentSkill(talent_id=t.id, skill_id=skills[match].id,
                                               level=rng.randint(3, 5)))
    db_session.commit()

    # A little ledger history so balances differ and the "why" page has content.
    for t in talents:
        if db_session.query(TokenLedger).filter_by(talent_id=t.id).count():
            continue
        for reason, delta, ref in [('event_attendance', 10, 1), ('assignment_completed_on_time', 15, 1)]:
            if rng.random() > 0.4:
                db_session.add(TokenLedger(
                    talent_id=t.id, delta=delta, reason=reason, ref_type='seed', ref_id=ref,
                    note='Seeded history', created_at=now - datetime.timedelta(days=rng.randint(10, 200)),
                ))
    db_session.commit()

    print(f"Seeded {len(skills)} skills, {existing} certifications, "
          f"{db_session.query(Event).count()} events; enriched {len(talents)} talents.")


if __name__ == '__main__':
    main()
