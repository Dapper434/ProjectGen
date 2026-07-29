"""Open sign-up: a talent creates their own account, no invite needed.

The case worth protecting is the third one — an email that is *already on the
agency's bench* must not be claimable by whoever types it into the sign-up form,
or knowing a crew member's email address is enough to take over their profile.
"""
import pytest
from werkzeug.security import generate_password_hash

from database import db_session
from models import Talent

PASSWORD = 'a-long-enough-password'


@pytest.fixture
def app_client(monkeypatch):
    import app as app_module
    app_module.app.config['TESTING'] = True
    monkeypatch.setitem(app_module.Config.FLAGS, 'talent_portal', True)
    monkeypatch.setitem(app_module.Config.FLAGS, 'talent', True)
    # Deterministic, offline: the claim path emails a link, and the console
    # driver both prints it and returns it for assertions.
    monkeypatch.setitem(app_module.Config.DEFAULT_DRIVERS, 'email', 'console')
    return app_module.app.test_client()


def test_signup_creates_a_live_self_registered_account(app_client):
    res = app_client.post('/api/talent/signup', json={
        'name': 'Wanjiru Kamau', 'email': 'Wanjiru@Example.com',
        'password': PASSWORD, 'title': 'Editor', 'location': 'Nairobi',
    })
    assert res.status_code == 201

    talent = db_session.query(Talent).filter_by(email='wanjiru@example.com').one()
    assert talent.signup_source == 'self'
    assert talent.status == 'active' and talent.is_active
    assert talent.portal_password_hash                      # usable immediately
    # Signed in on the spot — no second round trip through the login form.
    assert app_client.get('/api/talent/me').get_json()['name'] == 'Wanjiru Kamau'


def test_signup_then_signin(app_client):
    app_client.post('/api/talent/signup',
                    json={'name': 'Otieno', 'email': 'otieno@example.com', 'password': PASSWORD})
    app_client.post('/api/talent/logout')
    res = app_client.post('/api/talent/login',
                          json={'email': 'otieno@example.com', 'password': PASSWORD})
    assert res.status_code == 200


def test_signup_cannot_take_over_an_existing_bench_profile(app_client):
    """Already on the bench, no password set: sign-up must fall through to an
    emailed claim link rather than handing the profile straight over."""
    bench = Talent(name='Grace Njeri', email='grace@example.com', is_active=True,
                   status='active', notes='INTERNAL: negotiates hard')
    db_session.add(bench)
    db_session.commit()
    # An id, not the instance: the request's teardown calls db_session.remove().
    bench_id = bench.id

    res = app_client.post('/api/talent/signup', json={
        'name': 'Not Grace', 'email': 'grace@example.com', 'password': PASSWORD,
    })
    assert res.status_code == 202
    assert res.get_json()['claim_sent'] is True

    bench = db_session.query(Talent).get(bench_id)
    assert bench.portal_password_hash is None       # nothing handed over
    assert bench.name == 'Grace Njeri'              # and nothing overwritten
    # No session was established either.
    assert app_client.get('/api/talent/me').status_code == 401


def test_signup_rejects_an_email_that_already_has_a_login(app_client):
    db_session.add(Talent(name='Existing', email='existing@example.com', is_active=True,
                          status='active', portal_password_hash=generate_password_hash(PASSWORD)))
    db_session.commit()

    res = app_client.post('/api/talent/signup', json={
        'name': 'Impostor', 'email': 'existing@example.com', 'password': PASSWORD,
    })
    assert res.status_code == 400
    assert 'Sign in instead' in res.get_json()['error']


@pytest.mark.parametrize('payload, expected', [
    ({'name': '', 'email': 'x@example.com', 'password': PASSWORD}, 'name'),
    ({'name': 'X', 'email': 'not-an-email', 'password': PASSWORD}, 'email'),
    ({'name': 'X', 'email': 'x@example.com', 'password': 'short'}, 'password'),
])
def test_signup_validation(app_client, payload, expected):
    res = app_client.post('/api/talent/signup', json=payload)
    assert res.status_code == 400
    assert expected in res.get_json()['error'].lower()
    assert db_session.query(Talent).count() == 0


def test_signup_is_404_when_the_portal_flag_is_off(app_client, monkeypatch):
    import app as app_module
    monkeypatch.setitem(app_module.Config.FLAGS, 'talent_portal', False)
    res = app_client.post('/api/talent/signup',
                          json={'name': 'X', 'email': 'x@example.com', 'password': PASSWORD})
    assert res.status_code == 404
