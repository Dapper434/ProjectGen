"""Authoritative Data Layer — versioned, scoped system knowledge (prompts today;
protocols, policies, and catalogs in later WPs) that agents and humans both read
from one place instead of code constants. See
docs/THE_EXODUS_Master_Implementation_Blueprint.md WP-1.

Resolution is most-specific-active-wins: an engagement-scoped document replaces
the client-scoped one, which replaces the global one — no merging between
scopes. Documents are immutable: editing creates version N+1 and deactivates
version N, so AgentEvent.authoritative_refs can answer "which prompt did this
brief actually use?" months later.

Deliberately NOT registered here yet: `rate_card` / `past_projects`. Both
already exist as real relational tables (RateCardItem, PastProject) consumed
directly by generate_proposal. Folding agency pricing data into a versioned
JSON blob is a real product decision that touches money — this WP builds the
mechanism and proves it against the five prompt keys, but does not make that
call silently. See the note added to the blueprint's WP-1 section.
"""
import datetime
import json

from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import func

from database import db_session
from models import AuthoritativeDoc


class AuthoritativeError(ValueError):
    """A save/resolve was rejected — unknown key, bad scope, or schema validation failure."""


class CastingPolicySchema(BaseModel):
    """Weights must sum to 1.0 — a policy edit must not silently break scoring
    by making one component dominate through arithmetic rather than intent."""
    weights: dict
    shortlist_size: int = Field(default=3, ge=1, le=20)
    inhouse_first: bool = True
    require_human_approval: bool = True
    offer_expiry_hours: int = Field(default=48, ge=1, le=720)
    max_concurrent_assignments_per_talent: int = Field(default=2, ge=1, le=10)

    @field_validator('weights')
    @classmethod
    def _weights_sum_to_one(cls, v):
        total = sum(float(x) for x in v.values())
        if abs(total - 1.0) > 0.001:
            raise ValueError(f"weights must sum to 1.0 (got {total:.3f})")
        return v


class FathomMatchingSchema(BaseModel):
    """Tuning for how aggressively an inbound Fathom meeting auto-attaches (WP-8).
    Bounded deliberately: a threshold near 0 would auto-attach a transcript to an
    arbitrary client, which is the one failure mode worse than a human clicking
    Attach. The floor of 0.5 makes that unreachable without a code change."""
    fuzzy_threshold: float = Field(default=0.75, ge=0.5, le=1.0)
    min_client_name_length: int = Field(default=3, ge=3, le=50)


# --- the key registry --------------------------------------------------------
# Declared in code (not the database) so the admin UI is self-documenting: what
# a key is for, who reads it, which scopes it supports. `fmt='json'` entries may
# carry a `schema` (a pydantic BaseModel subclass, or a pydantic TypeAdapter for
# list/scalar shapes) validated on every save — a doc that fails validation is
# never persisted. `variants: True` allows multiple active, differently-labelled
# versions to coexist so the WP-2 Lab can A/B them.
#
# The blueprint's WP-1 sketch groups "generate" and "refine/revise" under one
# key each (brief_prompt, proposal_prompt). This repo's agents.py has five
# genuinely different system prompts (each with its own careful behavioural
# constraints — e.g. revise_proposal's "copy verbatim unless changed" rules
# would be lost if forced to share a document with generate_proposal's merge
# instructions), so this registry uses five keys instead of two. Noted in the
# blueprint doc; the code wins per AGENTS.md §8.
REGISTRY = {
    'brief_generation_prompt': {
        'fmt': 'markdown', 'scopes': ('global',), 'variants': True,
        'consumers': ['generate_brief'],
        'title': 'Brief Generation — system prompt',
    },
    'brief_refinement_prompt': {
        'fmt': 'markdown', 'scopes': ('global',), 'variants': True,
        'consumers': ['refine_brief'],
        'title': 'Brief Refinement — system prompt',
    },
    'signal_extraction_prompt': {
        'fmt': 'markdown', 'scopes': ('global',), 'variants': True,
        'consumers': ['extract_meeting_signals'],
        'title': 'Meeting Signal Extraction — system prompt',
    },
    'proposal_generation_prompt': {
        'fmt': 'markdown', 'scopes': ('global',), 'variants': True,
        'consumers': ['generate_proposal'],
        'title': 'Proposal Generation — system prompt',
    },
    'proposal_revision_prompt': {
        'fmt': 'markdown', 'scopes': ('global',), 'variants': True,
        'consumers': ['revise_proposal'],
        'title': 'Proposal Revision — system prompt',
    },
    'brand_voice': {
        'fmt': 'markdown', 'scopes': ('global', 'client'),
        'consumers': [],
        'title': 'Brand Voice',
    },
    'polish_prompt': {
        'fmt': 'markdown', 'scopes': ('global',), 'variants': True,
        'consumers': ['polish'],
        'title': 'Transcript Cleanup — system prompt',
    },
    'email_cover_note': {
        'fmt': 'markdown', 'scopes': ('global', 'client'),
        'consumers': [],
        'title': 'Email Cover Note Template',
    },
    'boardroom_protocol': {
        'fmt': 'json', 'scopes': ('global', 'client', 'engagement'),
        'consumers': ['analyze_coverage', 'Boardroom.jsx'],
        'title': 'Boardroom Meeting Protocol',
    },
    'coverage_prompt': {
        'fmt': 'markdown', 'scopes': ('global',), 'variants': True,
        'consumers': ['analyze_coverage'],
        'title': 'Coverage Agent — system prompt',
    },
    'talent_token_policy': {
        'fmt': 'json', 'scopes': ('global',),
        'consumers': ['tokens.balance', 'HowIGetPicked.jsx'],
        'title': 'Talent Token Policy',
    },
    'casting_policy': {
        'fmt': 'json', 'scopes': ('global', 'engagement'), 'schema': CastingPolicySchema,
        'consumers': ['run_casting', 'HowIGetPicked.jsx'],
        'title': 'Casting Policy',
    },
    'certification_catalog': {
        'fmt': 'json', 'scopes': ('global',),
        'consumers': ['TalentCertifications.jsx'],
        'title': 'Certification Catalog',
    },
    'fathom_matching': {
        'fmt': 'json', 'scopes': ('global',), 'schema': FathomMatchingSchema,
        'consumers': ['_auto_match_client'],
        'title': 'Fathom Auto-Attach Matching',
    },
    # WP-7/9/10/11 add their own json-format keys (boardroom_protocol,
    # talent_token_policy, casting_policy, certification_catalog) here when
    # those WPs land — the schema-validation mechanism below already supports
    # them, nothing else needs to change.
}


def _validate_body(key, fmt, body):
    """Returns the body ready to store (json bodies are normalised through a
    parse/dump round-trip). Raises AuthoritativeError, never persists, on any
    validation failure — an agent must never crash at 2am because someone
    typo'd a weight."""
    if fmt != 'json':
        return body
    entry = REGISTRY[key]
    try:
        parsed = json.loads(body) if isinstance(body, str) else body
    except (json.JSONDecodeError, TypeError) as e:
        raise AuthoritativeError(f"Invalid JSON: {e}") from e

    schema = entry.get('schema')
    if schema is not None:
        try:
            validate_python = getattr(schema, 'validate_python', None)
            if validate_python:  # pydantic TypeAdapter — list/scalar shapes
                validate_python(parsed)
            else:                # pydantic BaseModel subclass
                schema.model_validate(parsed)
        except ValidationError as e:
            raise AuthoritativeError(f"Schema validation failed: {e}") from e
    return json.dumps(parsed)


def resolve(key, engagement=None, client=None, version=None, label=None):
    """Engagement override beats client override beats global default. No
    merging between scopes — an engagement-level document replaces the global
    one rather than patching it.

    Returns (parsed_body, provenance_dict) or (None, None) if nothing is set
    at any scope this key supports. `parsed_body` is the raw string for
    fmt='markdown' keys, or the decoded value for fmt='json' keys."""
    if key not in REGISTRY:
        raise AuthoritativeError(f"Unknown authoritative key: {key!r}")

    entry = REGISTRY[key]
    client = client or (engagement.client if engagement else None)
    candidates = [
        ('engagement', engagement.id if engagement else None),
        ('client', client.id if client else None),
        ('global', None),
    ]

    for scope_type, scope_id in candidates:
        if scope_type not in entry['scopes']:
            continue
        if scope_type != 'global' and scope_id is None:
            continue
        q = db_session.query(AuthoritativeDoc).filter_by(key=key, scope_type=scope_type, scope_id=scope_id)
        # Always pin to a label — explicit, or the canonical (unlabelled) row.
        # Without this, an active Lab experiment (label='concise', a higher
        # version number than the default) would silently outrank the
        # production document any time no label is requested.
        q = q.filter_by(label=label) if label else q.filter(AuthoritativeDoc.label.is_(None))
        q = q.filter_by(version=version) if version else q.filter_by(is_active=True)
        doc = q.order_by(AuthoritativeDoc.version.desc()).first()
        if doc:
            body = json.loads(doc.body) if doc.fmt == 'json' else doc.body
            return body, {"key": key, "scope": scope_type, "scope_id": scope_id,
                          "version": doc.version, "label": doc.label}
    return None, None


def list_versions(key, scope_type='global', scope_id=None):
    if key not in REGISTRY:
        raise AuthoritativeError(f"Unknown authoritative key: {key!r}")
    return db_session.query(AuthoritativeDoc).filter_by(
        key=key, scope_type=scope_type, scope_id=scope_id
    ).order_by(AuthoritativeDoc.version.desc()).all()


def create_version(key, scope_type, scope_id, title, fmt, body, updated_by=None, label=None, note=None):
    """Create version N+1 and deactivate version N. Documents are immutable —
    there is no UPDATE path on `body`, only new versions. Version numbers are
    unique per (key, scope_type, scope_id) across every label — see the
    UniqueConstraint on AuthoritativeDoc — so two variant labels of the same
    key/scope never collide even though each keeps its own active pointer."""
    if key not in REGISTRY:
        raise AuthoritativeError(f"Unknown authoritative key: {key!r}")
    entry = REGISTRY[key]
    if scope_type not in entry['scopes']:
        raise AuthoritativeError(f"{key!r} does not support scope_type {scope_type!r}")
    if scope_type != 'global' and scope_id is None:
        raise AuthoritativeError(f"scope_id is required for scope_type={scope_type!r}")
    if fmt != entry['fmt']:
        raise AuthoritativeError(f"{key!r} must be saved as fmt={entry['fmt']!r}")
    if label and not entry.get('variants'):
        raise AuthoritativeError(f"{key!r} does not support labelled variants")

    body = _validate_body(key, fmt, body)

    max_version = db_session.query(func.max(AuthoritativeDoc.version)).filter_by(
        key=key, scope_type=scope_type, scope_id=scope_id
    ).scalar()
    next_version = (max_version or 0) + 1

    prior_q = db_session.query(AuthoritativeDoc).filter_by(
        key=key, scope_type=scope_type, scope_id=scope_id, is_active=True
    )
    prior_q = prior_q.filter_by(label=label) if label else prior_q.filter(AuthoritativeDoc.label.is_(None))
    for prior in prior_q.all():
        prior.is_active = False

    doc = AuthoritativeDoc(
        key=key, scope_type=scope_type, scope_id=scope_id, title=title,
        fmt=fmt, body=body, version=next_version, is_active=True,
        label=label, note=note, updated_by=updated_by,
        updated_at=datetime.datetime.utcnow(),
    )
    db_session.add(doc)
    db_session.flush()
    return doc


def activate_version(doc_id):
    """Rollback: reactivate an old version as a new active pointer rather than
    mutating history. Clones the target version's body forward as a brand new
    version number, so 'rolled back to v2' is itself a new, auditable version —
    never a rewrite of the past."""
    target = db_session.query(AuthoritativeDoc).get(doc_id)
    if not target:
        raise AuthoritativeError("Version not found")

    return create_version(
        key=target.key, scope_type=target.scope_type, scope_id=target.scope_id,
        title=target.title, fmt=target.fmt, body=target.body,
        updated_by=target.updated_by, label=target.label,
        note=f"Rolled back to v{target.version}",
    )


def build_refs(*provenance):
    """JSON-encode resolve() provenance dict(s) for AgentEvent.authoritative_refs.
    Skips any None (an unresolved/unseeded key) so a partially-seeded system
    still produces a valid, if shorter, provenance list rather than an error."""
    refs = [p for p in provenance if p]
    return json.dumps(refs) if refs else None
