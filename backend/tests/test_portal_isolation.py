"""The talent portal is the first genuinely public surface in this system, so
its isolation invariant gets a test rather than a code review.

**Invariant:** every talent-portal query is filtered by `session['talent_id']`
at the query level, and no talent route accepts a `talent_id` parameter.
"""
import pytest
from werkzeug.security import generate_password_hash

from database import db_session
from models import PortfolioItem, Talent, TokenLedger


@pytest.fixture
def app_client(monkeypatch):
    import app as app_module
    app_module.app.config['TESTING'] = True
    monkeypatch.setitem(app_module.Config.FLAGS, 'talent_portal', True)
    monkeypatch.setitem(app_module.Config.FLAGS, 'talent', True)
    return app_module.app.test_client()


@pytest.fixture
def two_talents():
    a = Talent(name='Talent A', email='a@example.com', is_active=True, status='active',
               portal_password_hash=generate_password_hash('passwordpassword'))
    b = Talent(name='Talent B', email='b@example.com', is_active=True, status='active',
               portal_password_hash=generate_password_hash('passwordpassword'))
    db_session.add_all([a, b])
    db_session.flush()

    db_session.add(PortfolioItem(talent_id=a.id, title="A's private reel", is_public=True))
    db_session.add(TokenLedger(talent_id=a.id, delta=99, reason='manual', ref_type='test', ref_id=1))
    db_session.commit()
    # Plain ids, not ORM instances: each request's teardown calls
    # db_session.remove(), which would detach them.
    return a.id, b.id


def _login_as(client, talent_id):
    with client.session_transaction() as sess:
        sess['role'] = 'Talent'
        sess['talent_id'] = talent_id


def test_b_cannot_read_as_portfolio(app_client, two_talents):
    a, b = two_talents
    item_id = db_session.query(PortfolioItem).filter_by(talent_id=a).first().id

    _login_as(app_client, b)
    assert app_client.get('/api/talent/portfolio').get_json() == []
    assert app_client.patch(f'/api/talent/portfolio/{item_id}',
                            json={'title': 'hijacked'}).status_code == 404
    assert app_client.delete(f'/api/talent/portfolio/{item_id}').status_code == 404

    assert db_session.query(PortfolioItem).get(item_id).title == "A's private reel"


def test_b_cannot_read_as_ledger(app_client, two_talents):
    a, b = two_talents
    _login_as(app_client, b)
    assert app_client.get('/api/talent/tokens').get_json()['ledger'] == []

    _login_as(app_client, a)
    assert len(app_client.get('/api/talent/tokens').get_json()['ledger']) == 1


def test_b_cannot_respond_to_as_offer(app_client, two_talents):
    from models import Assignment
    a, b = two_talents
    offer = Assignment(engagement_id=None, talent_id=a, role='Editor', status='offered')
    db_session.add(offer)
    db_session.commit()
    offer_id = offer.id

    _login_as(app_client, b)
    assert app_client.post(f'/api/talent/offers/{offer_id}/respond',
                           json={'action': 'accept'}).status_code == 404
    assert db_session.query(Assignment).get(offer_id).status == 'offered'


def test_b_cannot_delete_as_availability(app_client, two_talents):
    import datetime
    from models import AvailabilityBlock
    a, b = two_talents
    block = AvailabilityBlock(talent_id=a, kind='busy', source='manual',
                              start_at=datetime.datetime(2026, 1, 1),
                              end_at=datetime.datetime(2026, 1, 5))
    db_session.add(block)
    db_session.commit()
    block_id = block.id

    _login_as(app_client, b)
    assert app_client.delete(f'/api/talent/availability/{block_id}').status_code == 404
    assert app_client.get('/api/talent/availability').get_json() == []


def test_talent_routes_reject_internal_and_anonymous_sessions(app_client, two_talents):
    assert app_client.get('/api/talent/me').status_code == 401

    with app_client.session_transaction() as sess:
        sess['role'] = 'Producer'
        sess['user_id'] = 1
    assert app_client.get('/api/talent/me').status_code == 401


def test_internal_notes_are_never_exposed_to_the_talent(app_client, two_talents):
    a, _b = two_talents
    db_session.query(Talent).get(a).notes = 'Internal: slow to invoice.'
    db_session.commit()

    _login_as(app_client, a)
    assert 'notes' not in app_client.get('/api/talent/me').get_json()


def test_portal_routes_404_when_the_flag_is_off(monkeypatch, two_talents):
    import app as app_module
    app_module.app.config['TESTING'] = True
    monkeypatch.setitem(app_module.Config.FLAGS, 'talent_portal', False)
    client = app_module.app.test_client()
    _login_as(client, two_talents[0])
    assert client.get('/api/talent/me').status_code == 404
