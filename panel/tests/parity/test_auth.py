"""First-run setup, login, sessions, rate limiting and the auth gate on every API route."""
import http.client

import pytest

from tests.conftest import OWNER_PW, OWNER_USER

GET_ROUTES = ['/api/status', '/api/players', '/api/whitelist', '/api/addons', '/api/plugins', '/api/me', '/api/accounts',
              '/api/download?token=x', '/api/logs?console', '/api/logs?perfjson']
POST_ROUTES = ['/api/logout', '/api/rcon', '/api/action', '/api/preset', '/api/difficulty', '/api/damage', '/api/map', '/api/points',
               '/api/kick', '/api/whitelist', '/api/upload?name=a.vpk', '/api/addons', '/api/whitelist_enable', '/api/plugins',
               '/api/plugin_upload?name=a.smx', '/api/me', '/api/accounts']


@pytest.mark.panel(password='')
def test_first_run_setup_creates_the_owner(panel):
    c = panel.client()
    assert c.get('/api/setup').json() == {'needed': True, 'username': OWNER_USER}
    assert c.get('/api/status').status_code == 401
    r = c.post('/api/login', json={'username': OWNER_USER, 'password': 'whatever'})
    assert r.status_code == 403 and '初始化' in r.json()['error']
    assert c.post('/api/setup', json={'password': '123'}).status_code == 400
    r = c.post('/api/setup', json={'password': 'newpass1'})
    assert r.status_code == 200 and r.json() == {'ok': True}
    cookie = r.headers['set-cookie']
    assert cookie.startswith('l4d2panel=') and 'HttpOnly' in cookie and 'SameSite=Lax' in cookie and 'Path=/' in cookie and f'Max-Age={7 * 86400}' in cookie and 'Secure' not in cookie
    assert c.get('/api/setup').json()['needed'] is False
    assert c.post('/api/setup', json={'password': 'again123'}).status_code == 409
    me = c.get('/api/me').json()
    assert me['username'] == OWNER_USER and me['role'] == 'owner'
    assert (OWNER_USER, 'setup') in panel.audit_actions()
    # the password in panel.json is only a seed: the setup password is what logs in
    assert panel.login(password='newpass1').get('/api/status').status_code == 200


def test_login_logout_and_session_cookie(panel):
    c = panel.client()
    r = c.post('/api/login', json={'username': OWNER_USER, 'password': 'wrong'})
    assert r.status_code == 403 and r.json()['error']
    r = c.post('/api/login', json={'username': OWNER_USER, 'password': OWNER_PW})
    assert r.status_code == 200 and r.json() == {'ok': True} and 'Secure' not in r.headers['set-cookie']
    assert c.get('/api/status').status_code == 200
    assert c.post('/api/logout', json={}).json() == {'ok': True}
    assert c.get('/api/status').status_code == 401
    assert (OWNER_USER, 'login') in panel.audit_actions()


def test_secure_cookie_behind_https_proxy(panel):
    c = panel.client()
    r = c.post('/api/login', json={'username': OWNER_USER, 'password': OWNER_PW}, headers={'X-Forwarded-Proto': 'https'})
    assert r.status_code == 200 and 'Secure' in r.headers['set-cookie']


def test_login_rate_limit_is_per_client_ip(panel):
    c = panel.client()
    for _ in range(6):
        assert c.post('/api/login', json={'username': OWNER_USER, 'password': 'bad'}, headers={'X-Real-IP': '203.0.113.9'}).status_code == 403
    r = c.post('/api/login', json={'username': OWNER_USER, 'password': OWNER_PW}, headers={'X-Real-IP': '203.0.113.9'})
    assert r.status_code == 429
    # another source IP (as reported by the reverse proxy) is not locked out
    assert c.post('/api/login', json={'username': OWNER_USER, 'password': OWNER_PW}, headers={'X-Real-IP': '198.51.100.7'}).status_code == 200


def test_every_api_route_requires_a_session(panel):
    c = panel.client()
    for path in GET_ROUTES:
        r = c.get(path); assert r.status_code == 401 and 'error' in r.json(), path
    for path in POST_ROUTES:
        r = c.post(path, json={}); assert r.status_code == 401 and 'error' in r.json(), path
    r = c.get('/')
    assert r.status_code == 200 and r.headers['content-type'].startswith('text/html')
    assert c.get('/api/setup').status_code == 200


def test_unknown_api_route_is_404_when_logged_in(api):
    r = api.get('/api/nope')
    assert r.status_code == 404 and 'error' in r.json()


def test_two_sessions_are_independent(panel):
    a = panel.login(); b = panel.login()
    assert a.post('/api/logout', json={}).json() == {'ok': True}
    assert a.get('/api/me').status_code == 401
    assert b.get('/api/me').status_code == 200
