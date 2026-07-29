"""Requirement documents became editable in place from the Playbook.

The subtle part is the cache: a completeness result is stored on the Brief that
was graded, keyed by a fingerprint of the corpus. Rewording a document changes
neither the row count nor the highest id, so without `updated_at` in that
fingerprint an edit would leave every previous verdict looking current.
"""
import pytest

from database import db_session
from models import RequirementDocument, User


@pytest.fixture
def app_client():
    import app as app_module
    app_module.app.config['TESTING'] = True
    return app_module.app.test_client()


@pytest.fixture
def am_user():
    user = User(username='am', password_hash='x', role='Account Manager')
    db_session.add(user)
    db_session.commit()
    return user.id


def _login(client, user_id, role):
    with client.session_transaction() as sess:
        sess['user_id'] = user_id
        sess['role'] = role


def _doc():
    doc = RequirementDocument(title='Brief checklist', doc_type='brief',
                              raw_text='Every brief states the deliverables.', is_active=True)
    db_session.add(doc)
    db_session.commit()
    return doc.id


def test_get_returns_the_full_text(app_client, am_user):
    doc_id = _doc()
    _login(app_client, am_user, 'Account Manager')
    body = app_client.get(f'/api/requirements/{doc_id}').get_json()
    assert body['raw_text'] == 'Every brief states the deliverables.'
    assert body['title'] == 'Brief checklist'


def test_patch_edits_in_place_and_records_the_editor(app_client, am_user):
    doc_id = _doc()
    _login(app_client, am_user, 'Account Manager')
    res = app_client.patch(f'/api/requirements/{doc_id}', json={
        'raw_text': 'Every brief states the deliverables and the shoot dates.',
        'title': 'Brief checklist v2',
    })
    assert res.status_code == 200

    doc = db_session.query(RequirementDocument).get(doc_id)
    assert doc.raw_text.endswith('shoot dates.')
    assert doc.title == 'Brief checklist v2'
    assert doc.doc_type == 'brief'          # untouched fields stay put
    assert doc.updated_at is not None
    assert doc.updated_by == am_user


def test_editing_the_text_invalidates_cached_completeness(app_client, am_user):
    """The regression this guards: count and max_id both survive a reword."""
    import app as app_module
    doc_id = _doc()
    before = app_module._requirement_fingerprint('brief')

    _login(app_client, am_user, 'Account Manager')
    app_client.patch(f'/api/requirements/{doc_id}', json={'raw_text': 'Something different.'})

    after = app_module._requirement_fingerprint('brief')
    assert (before['count'], before['max_id']) == (after['count'], after['max_id'])
    assert before != after


def test_producers_cannot_edit(app_client, am_user):
    doc_id = _doc()
    producer = User(username='prod', password_hash='x', role='Producer')
    db_session.add(producer)
    db_session.commit()

    _login(app_client, producer.id, 'Producer')
    assert app_client.patch(f'/api/requirements/{doc_id}', json={'title': 'nope'}).status_code == 403
    # Reading it is fine — the Playbook is visible to everyone, editable by two roles.
    assert app_client.get(f'/api/requirements/{doc_id}').status_code == 200
    assert db_session.query(RequirementDocument).get(doc_id).title == 'Brief checklist'


def test_patch_rejects_an_empty_body_and_a_bad_doc_type(app_client, am_user):
    doc_id = _doc()
    _login(app_client, am_user, 'Account Manager')
    assert app_client.patch(f'/api/requirements/{doc_id}', json={'raw_text': '   '}).status_code == 400
    assert app_client.patch(f'/api/requirements/{doc_id}', json={'doc_type': 'invoice'}).status_code == 400
    assert db_session.query(RequirementDocument).get(doc_id).updated_at is None


def test_a_deactivated_document_is_gone(app_client, am_user):
    doc_id = _doc()
    _login(app_client, am_user, 'Account Manager')
    app_client.post(f'/api/requirements/{doc_id}/deactivate')
    assert app_client.get(f'/api/requirements/{doc_id}').status_code == 404
