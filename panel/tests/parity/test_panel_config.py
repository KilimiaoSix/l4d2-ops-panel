import json

import pytest

from tests.conftest import OWNER_USER


def test_panel_config_permissions_and_write_only_secrets(panel, api):
    anon = panel.client()
    assert anon.get('/api/panel-config').status_code == 401
    assert anon.post('/api/panel-config', json={}).status_code == 401
    api.post('/api/accounts', json={'op': 'create', 'username': 'helper', 'password': 'helper-pass', 'role': 'admin'})
    admin = panel.login('helper', 'helper-pass')
    assert admin.get('/api/panel-config').status_code == 403
    assert admin.post('/api/panel-config', json={}).status_code == 403
    result = api.get('/api/panel-config')
    assert result.headers['cache-control'] == 'no-store'
    data = result.json()
    assert data['config_path'] == str(panel.conf_path.resolve())
    assert 'password' not in data['fields'] and 'db' not in data['fields']
    assert data['fields']['steam_api_key'] == {'set': False, 'effect': 'live', 'editable': True, 'locked_reason': ''}
    assert data['fields']['game_dir']['editable'] is False
    assert not data['supervised']


def test_live_configuration_updates_all_consumers_and_audit_without_secrets(panel, api):
    before = api.get('/api/panel-config').json()
    # Prime features before changing Steam API availability.
    assert api.get('/api/status').json()['features']['workshop_search'] is False
    updates = {'panel_title': '测试面板', 'display_host': 'join.example:27020', 'max_upload_mb': 2, 'steam_api_key': 'new-private-key'}
    response = api.post('/api/panel-config', json={'revision': before['revision'], 'updates': updates})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['saved'] and not result['restart_scheduled'] and result['boot'] == before['boot']
    after = api.get('/api/panel-config').json()
    assert after['revision'] != before['revision'] and after['applied_revision'] == after['revision']
    assert 'new-private-key' not in json.dumps(after)
    st = api.get('/api/status').json()
    assert st['title'] == '测试面板' and st['display_host'] == 'join.example:27020'
    assert st['features']['workshop_search'] is True and st['config_revision'] == after['revision']
    assert json.loads(panel.conf_path.read_text())['steam_api_key'] == 'new-private-key'
    assert (OWNER_USER, 'panel.config') in panel.audit_actions()
    assert 'new-private-key' not in json.dumps(panel.audit())
    assert api.post('/api/panel-config', json={'revision': before['revision'], 'updates': {'panel_title': 'stale'}}).status_code == 409
    noop = api.post('/api/panel-config', json={'revision': after['revision'], 'updates': updates}).json()
    assert not noop['saved'] and noop['backup'] is None


@pytest.mark.parametrize('updates,confirmed,code', [
    ({'port': 12000, 'panel_title': 'partial'}, False, 409),
    ({'port': 12000}, True, 409),  # A standalone process is never allowed to exit itself.
    ({'game_dir': '/tmp/new-game'}, True, 409),
    ({'server_backend': 'docker'}, False, 400),
    ({'steam_api_key': False}, False, 400),
])
def test_rejected_changes_preserve_entire_file_and_listener(panel, api, updates, confirmed, code):
    before = panel.conf_path.read_bytes()
    config = api.get('/api/panel-config').json()
    result = api.post('/api/panel-config', json={'revision': config['revision'], 'updates': updates, 'restart': confirmed})
    assert result.status_code == code, result.text
    assert panel.conf_path.read_bytes() == before
    assert api.get('/api/status').json()['boot'] == config['boot']


def test_external_config_is_the_actual_edited_file(panel, api, tmp_path):
    panel.stop()
    external = tmp_path / 'external-config.json'
    external.write_bytes(panel.conf_path.read_bytes())
    original = panel.conf_path
    original_before = original.read_bytes()
    panel.conf_path = external
    panel.start()
    c = panel.login()
    config = c.get('/api/panel-config').json()
    r = c.post('/api/panel-config', json={'revision': config['revision'], 'updates': {'panel_title': 'external'}})
    assert r.status_code == 200, r.text
    assert original.read_bytes() == original_before
    assert json.loads(external.read_bytes())['panel_title'] == 'external'
    assert c.get('/api/status').json()['title'] == 'external'


def test_live_key_reaches_existing_steam_vanity_client(panel, api, fake_steam):
    fake_steam.vanity['new-friend'] = '76561198100202943'
    before = api.get('/api/panel-config').json()
    response = api.post('/api/panel-config', json={'revision': before['revision'], 'updates': {'steam_api_key': fake_steam.api_key}})
    assert response.status_code == 200
    response = api.post('/api/me', json={'op': 'steamid', 'steamid': 'https://steamcommunity.com/id/new-friend'})
    assert response.status_code == 200, response.text
    assert any('/ISteamUser/ResolveVanityURL/' in path and 'key=testkey' in path for _, path, _ in fake_steam.requests)
    assert not any('/id/new-friend' in path for _, path, _ in fake_steam.requests)


def test_external_restart_fields_cannot_be_reported_as_applied_by_a_live_save(panel, api):
    changed = json.loads(panel.conf_path.read_bytes()); changed['session_days'] = 14
    panel.conf_path.write_text(json.dumps(changed))
    latest = api.get('/api/panel-config').json()
    response = api.post('/api/panel-config', json={'revision': latest['revision'], 'updates': {'panel_title': 'hot'}})
    assert response.status_code == 409 and '外部' in response.json()['error']
    assert api.get('/api/status').json()['config_revision'] != latest['revision']
