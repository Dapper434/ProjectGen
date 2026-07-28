"""Priority-2 pure-function coverage for the Authoritative Data Layer (WP-1):
scope resolution order and schema rejection, per AGENTS.md's test priority table.
"""
import pytest
from pydantic import BaseModel

from database import db_session
import authoritative
from authoritative import (
    REGISTRY, AuthoritativeError, activate_version, create_version, list_versions, resolve,
)


def test_resolve_rejects_unknown_key():
    with pytest.raises(AuthoritativeError):
        resolve('not_a_real_key')


def test_resolve_returns_none_when_nothing_seeded(engagement):
    body, provenance = resolve('brief_generation_prompt', engagement=engagement)
    assert body is None
    assert provenance is None


def test_resolve_precedence_engagement_over_client_over_global(monkeypatch, engagement):
    monkeypatch.setitem(REGISTRY, '_test_key', {
        'fmt': 'markdown', 'scopes': ('global', 'client', 'engagement'), 'consumers': [],
    })

    create_version('_test_key', 'global', None, 'Test', 'markdown', 'GLOBAL')
    db_session.commit()
    body, provenance = resolve('_test_key', engagement=engagement)
    assert (body, provenance['scope']) == ('GLOBAL', 'global')

    create_version('_test_key', 'client', engagement.client_id, 'Test', 'markdown', 'CLIENT')
    db_session.commit()
    body, provenance = resolve('_test_key', engagement=engagement)
    assert (body, provenance['scope']) == ('CLIENT', 'client')

    create_version('_test_key', 'engagement', engagement.id, 'Test', 'markdown', 'ENGAGEMENT')
    db_session.commit()
    body, provenance = resolve('_test_key', engagement=engagement)
    assert (body, provenance['scope']) == ('ENGAGEMENT', 'engagement')

    # An engagement in a *different* client falls through to global, skipping
    # the first client's override entirely — no cross-client leakage.
    from models import Client, Engagement
    other_client = Client(name='Other Co', industry='Media')
    db_session.add(other_client)
    db_session.flush()
    other_eng = Engagement(client_id=other_client.id, status='awaiting_transcript')
    db_session.add(other_eng)
    db_session.flush()
    body, provenance = resolve('_test_key', engagement=other_eng)
    assert (body, provenance['scope']) == ('GLOBAL', 'global')


def test_create_version_increments_and_deactivates_prior():
    v1 = create_version('brand_voice', 'global', None, 'Brand Voice', 'markdown', 'v1 text')
    db_session.commit()
    assert v1.version == 1 and v1.is_active is True

    v2 = create_version('brand_voice', 'global', None, 'Brand Voice', 'markdown', 'v2 text')
    db_session.commit()
    assert v2.version == 2 and v2.is_active is True

    db_session.refresh(v1)
    assert v1.is_active is False
    assert v1.body == 'v1 text'  # the old row is untouched, not mutated


def test_rollback_creates_new_version_not_a_mutation():
    v1 = create_version('brand_voice', 'global', None, 'Brand Voice', 'markdown', 'original')
    db_session.commit()
    create_version('brand_voice', 'global', None, 'Brand Voice', 'markdown', 'oops typo')
    db_session.commit()

    rolled_back = activate_version(v1.id)
    db_session.commit()

    assert rolled_back.id != v1.id          # a new row, not the old one reactivated
    assert rolled_back.version == 3          # next in sequence, not a re-use of v1
    assert rolled_back.body == 'original'
    assert rolled_back.is_active is True

    db_session.refresh(v1)
    assert v1.is_active is False             # history is untouched
    assert v1.version == 1


def test_variant_labels_keep_independent_active_pointers_but_share_version_sequence(monkeypatch):
    monkeypatch.setitem(REGISTRY, '_test_variant_key', {
        'fmt': 'markdown', 'scopes': ('global',), 'variants': True, 'consumers': [],
    })
    default_v1 = create_version('_test_variant_key', 'global', None, 'Test', 'markdown', 'default text')
    db_session.commit()
    concise_v2 = create_version('_test_variant_key', 'global', None, 'Test', 'markdown', 'concise text', label='concise')
    db_session.commit()

    # Version numbers are unique per (key, scope) across all labels...
    assert (default_v1.version, concise_v2.version) == (1, 2)

    # ...but each label keeps its own independently-active pointer.
    db_session.refresh(default_v1)
    assert default_v1.is_active is True
    assert concise_v2.is_active is True

    # A plain resolve() (no label) must return the unlabelled default — never
    # the labelled experiment, even though it has the higher version number.
    # An active A/B variant silently outranking production would be a real bug.
    body, provenance = resolve('_test_variant_key', engagement=None, client=None)
    assert (body, provenance['version'], provenance['label']) == ('default text', 1, None)

    # Asking for the label explicitly reaches the variant.
    body, provenance = resolve('_test_variant_key', engagement=None, client=None, label='concise')
    assert (body, provenance['version']) == ('concise text', 2)

    default_active = [d for d in list_versions('_test_variant_key') if d.is_active]
    assert {d.label for d in default_active} == {None, 'concise'}


def test_json_schema_rejects_invalid_body_and_persists_nothing(monkeypatch):
    class _TestSchema(BaseModel):
        weight: float
        label: str

    monkeypatch.setitem(REGISTRY, '_test_json_key', {
        'fmt': 'json', 'scopes': ('global',), 'consumers': [], 'schema': _TestSchema,
    })

    with pytest.raises(AuthoritativeError):
        create_version('_test_json_key', 'global', None, 'Test', 'json', '{"weight": "not-a-number"}')

    assert list_versions('_test_json_key') == []

    ok = create_version('_test_json_key', 'global', None, 'Test', 'json', '{"weight": 1.5, "label": "x"}')
    db_session.commit()
    assert ok.version == 1
    body, provenance = resolve('_test_json_key', engagement=None)
    assert body == {"weight": 1.5, "label": "x"}


def test_create_version_rejects_wrong_fmt():
    with pytest.raises(AuthoritativeError):
        create_version('brand_voice', 'global', None, 'Brand Voice', 'json', '{}')


def test_create_version_rejects_unsupported_scope():
    with pytest.raises(AuthoritativeError):
        # brief_generation_prompt only supports scope_type='global'
        create_version('brief_generation_prompt', 'client', 1, 'Test', 'markdown', 'x')


def test_build_refs_skips_none_and_serialises_the_rest():
    ref = {"key": "k", "scope": "global", "scope_id": None, "version": 1, "label": None}
    assert authoritative.build_refs(None) is None
    assert authoritative.build_refs(ref, None) == '[{"key": "k", "scope": "global", "scope_id": null, "version": 1, "label": null}]'
