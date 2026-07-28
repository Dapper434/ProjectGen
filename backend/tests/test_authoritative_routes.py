"""Route-level access control for /api/authoritative — WP-1 acceptance criteria:
write access is Account Manager/Admin only, read is any internal role, and an
unrecognised role (standing in for a future Talent-portal session, which has no
path to session['role'] today) is rejected same as an anonymous request."""
import pytest


@pytest.fixture
def app_client(monkeypatch):
    import app as app_module
    app_module.app.config['TESTING'] = True
    monkeypatch.setitem(app_module.Config.FLAGS, 'auth_data', True)
    return app_module.app.test_client()


def _login_as(client, role, user_id=1):
    with client.session_transaction() as sess:
        sess['user_id'] = user_id
        sess['role'] = role


def test_get_404s_when_feature_flag_disabled(monkeypatch):
    # Invariant (AGENTS.md §2.10): a disabled feature 404s, even for a
    # logged-in user who would otherwise be allowed through.
    import app as app_module
    app_module.app.config['TESTING'] = True
    monkeypatch.setitem(app_module.Config.FLAGS, 'auth_data', False)
    client = app_module.app.test_client()
    _login_as(client, 'Account Manager')
    resp = client.get('/api/authoritative')
    assert resp.status_code == 404


def test_get_requires_login(app_client):
    resp = app_client.get('/api/authoritative')
    assert resp.status_code == 401


def test_get_rejects_unrecognised_role(app_client):
    # Stands in for a future Talent-portal session: no code path sets
    # session['role'] to 'Talent' today, but require_role() already rejects
    # anything outside the internal roleset by construction.
    _login_as(app_client, 'Talent')
    resp = app_client.get('/api/authoritative')
    assert resp.status_code == 403


def test_get_allows_producer(app_client):
    _login_as(app_client, 'Producer')
    resp = app_client.get('/api/authoritative')
    assert resp.status_code == 200
    body = resp.get_json()
    assert any(entry['key'] == 'brand_voice' for entry in body)


def test_post_rejects_producer(app_client):
    _login_as(app_client, 'Producer')
    resp = app_client.post('/api/authoritative', json={
        "key": "brand_voice", "scope_type": "global", "title": "Brand Voice",
        "fmt": "markdown", "body": "Warm, direct, no jargon.",
    })
    assert resp.status_code == 403


def test_post_allows_account_manager_and_creates_a_version(app_client):
    _login_as(app_client, 'Account Manager', user_id=7)
    resp = app_client.post('/api/authoritative', json={
        "key": "brand_voice", "scope_type": "global", "title": "Brand Voice",
        "fmt": "markdown", "body": "Warm, direct, no jargon.",
    })
    assert resp.status_code == 201
    created = resp.get_json()
    assert created['version'] == 1
    assert created['updated_by'] == 7

    resolved = app_client.get('/api/authoritative/resolve/brand_voice')
    assert resolved.status_code == 200
    assert resolved.get_json()['body'] == "Warm, direct, no jargon."


def test_post_rejects_bad_key(app_client):
    _login_as(app_client, 'Admin')
    resp = app_client.post('/api/authoritative', json={"key": "not_a_real_key", "body": "x"})
    assert resp.status_code == 400
