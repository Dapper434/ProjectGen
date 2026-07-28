"""Seed the five agent system prompts, currently hardcoded as DEFAULT_* constants
in agents.py, into the Authoritative Data Layer as scope_type='global' version=1
rows. Idempotent — safe to re-run; does nothing once a key already has an active
global version.

Every agent function still falls back to its own DEFAULT_* constant (and logs an
"INFO: no authoritative ... found" line) when no authoritative row exists, per
the blueprint's WP-1 §1.7 migration pattern. Once this script has run in an
environment and logs confirm the fallback never fires there, that constant
becomes dead weight — but it stays in agents.py for one release as a safety net
rather than being deleted here.

Usage: python3 seed_authoritative.py
"""
from dotenv import load_dotenv

load_dotenv()

import json

import agents
import app as app_module
import boardroom as boardroom_mod
import casting as casting_mod
import tokens as tokens_mod
import polish as polish_mod
from authoritative import REGISTRY, create_version
from database import db_session, init_db

PROMPT_SEEDS = [
    ('brief_generation_prompt', agents.DEFAULT_BRIEF_GENERATION_PROMPT),
    ('brief_refinement_prompt', agents.DEFAULT_BRIEF_REFINEMENT_PROMPT),
    ('signal_extraction_prompt', agents.DEFAULT_SIGNAL_EXTRACTION_PROMPT),
    ('proposal_generation_prompt', agents.DEFAULT_PROPOSAL_GENERATION_PROMPT),
    ('proposal_revision_prompt', agents.DEFAULT_PROPOSAL_REVISION_PROMPT),
    ('polish_prompt', polish_mod.DEFAULT_POLISH_PROMPT),
    ('coverage_prompt', boardroom_mod.DEFAULT_COVERAGE_PROMPT),
]

# Non-prompt config seeded from whatever the code already treats as its default,
# so seeding never silently changes behaviour (WP-8).
JSON_SEEDS = [
    ('fathom_matching', json.dumps(app_module.LEGACY_FATHOM_MATCHING),
     'Seeded from the LEGACY_FATHOM_MATCHING default in app.py.'),
    ('boardroom_protocol', json.dumps(boardroom_mod.DEFAULT_PROTOCOL, indent=2),
     'Seeded from the DEFAULT_PROTOCOL constant in boardroom.py.'),
    ('talent_token_policy', json.dumps(tokens_mod.DEFAULT_TOKEN_POLICY, indent=2),
     'Seeded from the DEFAULT_TOKEN_POLICY constant in tokens.py.'),
    ('casting_policy', json.dumps(casting_mod.DEFAULT_CASTING_POLICY, indent=2),
     'Seeded from the DEFAULT_CASTING_POLICY constant in casting.py.'),
]


def main():
    init_db()
    from models import AuthoritativeDoc

    created = []
    seeds = (
        [(key, 'markdown', body, 'Seeded from the pre-WP-1 hardcoded constant in agents.py.')
         for key, body in PROMPT_SEEDS]
        + [(key, 'json', body, note) for key, body, note in JSON_SEEDS]
    )
    for key, fmt, body, note in seeds:
        existing = db_session.query(AuthoritativeDoc).filter_by(
            key=key, scope_type='global', scope_id=None, is_active=True
        ).first()
        if existing:
            continue
        doc = create_version(
            key=key, scope_type='global', scope_id=None,
            title=REGISTRY[key]['title'], fmt=fmt, body=body,
            updated_by=None, note=note,
        )
        created.append(f"{key} v{doc.version}")

    db_session.commit()
    if created:
        print("Seeded:", ", ".join(created))
    else:
        print("Already up to date — no new versions created.")


if __name__ == '__main__':
    main()
