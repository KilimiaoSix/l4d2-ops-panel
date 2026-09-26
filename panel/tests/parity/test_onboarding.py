import json


def test_seeded_owner_does_not_skip_wizard_and_progress_survives_restart(panel, api):
    initial = api.get('/api/onboarding').json()
    assert initial['complete'] is False and initial['step'] == 'panel'
    draft = {'server_name': '朋友联机服', 'packs': ['minimal'], 'coop_players': 4}
    response = api.post('/api/onboarding', json={'step': 'game', 'draft': draft})
    assert response.status_code == 200 and response.json()['draft'] == draft
    panel.stop(); panel.start()
    restored = panel.login().get('/api/onboarding').json()
    assert restored['complete'] is False and restored['step'] == 'game' and restored['draft'] == draft
    assert restored['public_access'] == 'unverified'
    assert ('admin', 'panel.setup') in panel.audit_actions()


def test_draft_only_save_does_not_rewind_wizard_navigation(panel, api):
    assert api.post('/api/onboarding', json={'step': 'settings'}).status_code == 200
    response = api.post('/api/onboarding', json={'draft': {'packs': ['minimal', 'multiplayer']}})
    assert response.status_code == 200 and response.json()['step'] == 'settings'
    panel.stop(); panel.start()
    result = panel.login().get('/api/onboarding').json()
    assert result['step'] == 'settings' and result['draft']['packs'] == ['minimal', 'multiplayer']


def test_onboarding_permissions_secret_rejection_and_completion_checks(panel, api):
    assert panel.client().get('/api/onboarding').status_code == 401
    assert panel.client().post('/api/onboarding', json={}).status_code == 401
    api.post('/api/accounts', json={'op': 'create', 'username': 'helper', 'password': 'helper-pass'})
    admin = panel.login('helper', 'helper-pass')
    assert admin.get('/api/onboarding').status_code == 200
    assert admin.post('/api/onboarding', json={'step': 'game'}).status_code == 403
    for key in ('password', 'rcon_password', 'steam_api_key', 'secret'):
        r = api.post('/api/onboarding', json={'step': 'game', 'draft': {key: 'do-not-persist'}})
        assert r.status_code == 400 and 'do-not-persist' not in r.text
    r = api.post('/api/onboarding', json={'step': 'join', 'complete': True})
    assert r.status_code == 409
    assert api.get('/api/onboarding').json()['complete'] is False
    assert 'do-not-persist' not in json.dumps(panel.audit())


def test_uninstalled_pages_and_admin_binding_preserve_empty_game_target(panel_factory, tmp_path):
    target = tmp_path / 'uncreated-game'
    panel = panel_factory({'game_dir': str(target), 'rcon_port': 1, 'lgsm_script': ''})
    api = panel.login()
    for route in ('/api/status', '/api/players', '/api/addons', '/api/plugins', '/api/whitelist', '/api/me', '/api/accounts',
                  '/api/logs?console', '/api/logs?perfjson', '/api/game-mode', '/api/install', '/api/onboarding'):
        response = api.get(route)
        assert response.status_code == 200, (route, response.text)
        assert not target.exists(), route
    assert api.get('/api/addons').json()['addons'] == []
    assert api.post('/api/upload?name=map.vpk', content=b'payload').status_code == 409
    assert api.post('/api/plugin_upload?name=example.smx', content=b'payload').status_code == 409
    assert api.post('/api/addons', json={'op': 'workshop', 'id': '100200300'}).status_code == 409
    response = api.post('/api/me', json={'op': 'steamid', 'steamid': 'STEAM_1:0:5'})
    assert response.status_code == 200 and '账号已保存' in response.json()['out']
    assert api.post('/api/onboarding', json={'step': 'game', 'draft': {'server_name': '保存草稿'}}).status_code == 200
    assert not target.exists()
