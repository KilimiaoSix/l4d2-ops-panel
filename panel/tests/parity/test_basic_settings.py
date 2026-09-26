import json

import pytest

from l4d2panel.integrations.basic_config import HOSTNAME


@pytest.fixture
def basic_game(game_dir):
    for name in ('steam.inf', 'gameinfo.txt', 'bin/server_srv.so'):
        path = game_dir.root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b'fixture')
    return game_dir


def document(api):
    response = api.get('/api/basic-settings'); assert response.status_code == 200, response.text
    assert response.headers['cache-control'] == 'no-store'
    return response.json()['fields']


def save(api, values, mode='save_apply'):
    return api.post('/api/basic-settings', json={'revision': document(api)['revision'], 'mode': mode, **values})


def test_basic_auth_and_uninstalled_reads_do_not_create_game(panel, api, fake_game):
    for route in ('/api/basic-settings', '/api/basic-settings/runtime', '/api/basic-settings/recover'):
        assert panel.client().post(route, json={}).status_code == 401
    assert panel.client().get('/api/basic-settings').status_code == 401
    result = api.get('/api/basic-settings').json()
    assert not result['game_installed'] and result['fields'] is None
    assert not (panel.dir / 'basic_state').exists()
    assert api.post('/api/basic-settings', json={'revision': 'old', 'region': 4}).status_code == 409


def test_exact_chinese_name_password_redaction_and_clear(api, panel, basic_game, fake_game):
    result = save(api, {'server_name': '中文房间 · 一起玩', 'password': 'friends only', 'region': 4})
    assert result.status_code == 200, result.text
    data = result.json()
    assert data['fields']['server_name']['state'] == data['fields']['region']['state'] == 'applied'
    assert data['fields']['password']['state'] == 'unverified'
    read = document(api)
    assert read['server_name'] == '中文房间 · 一起玩' and read['password_set'] and read['region'] == 4
    assert 'friends only' not in str(read) + str(data) + str(panel.audit())
    assert fake_game.state['cvars']['sv_password'] == 'friends only'
    assert basic_game.cfg.read_bytes().isascii()
    assert (basic_game.root / HOSTNAME).read_bytes() == '中文房间 · 一起玩\n'.encode()
    assert save(api, {'region': 255}, 'save').status_code == 200
    assert 'sv_password "friends only"' in basic_game.cfg.read_text()
    assert save(api, {'password': ''}).status_code == 200
    assert not document(api)['password_set'] and fake_game.state['cvars']['sv_password'] == ''
    assert save(api, {'password': 'new secret'}, 'save').status_code == 200
    assert document(api)['password_set']
    assert api.get('/api/onboarding').json()['checks']['settings']['ready']


@pytest.mark.parametrize('values', [{'password': None}, {'password': 'fakerc0n'}, {'password': 'x;quit'},
    {'region': 8}, {'region': True}, {'coop_players': 3}, {'coop_players': 13}, {'coop_players': 8.5},
    {'server_name': '中' * 33}, {'server_name': 'name\nquit'}, {'unknown': 1}])
def test_invalid_inputs_do_not_write_or_change_game(api, basic_game, fake_game, values):
    before = basic_game.cfg.read_bytes(); fake_game.commands.clear()
    response = save(api, values)
    assert response.status_code == 400, response.text
    assert basic_game.cfg.read_bytes() == before and fake_game.commands == []


def test_stale_revision_and_missing_multiplayer_reject_whole_request(api, basic_game, fake_game):
    revision = document(api)['revision']
    basic_game.cfg.write_bytes(basic_game.cfg.read_bytes() + b'// external edit\n')
    original = basic_game.cfg.read_bytes(); fake_game.commands.clear()
    assert api.post('/api/basic-settings', json={'revision': revision, 'region': 4}).status_code == 409
    assert save(api, {'region': 4, 'coop_players': 8}).status_code == 409
    assert basic_game.cfg.read_bytes() == original and fake_game.commands == []


def test_partial_runtime_results_and_apply_only_preserve_saved_files(api, basic_game, fake_game):
    fake_game.hostname_mismatch = True; fake_game.cvar_overrides['sv_region'] = '2'
    result = save(api, {'server_name': '请求的中文', 'region': 4}).json()
    assert result['saved'] and result['fields']['server_name']['state'] == 'unverified'
    assert result['fields']['region']['state'] == 'unverified' and result['fields']['region']['actual'] == '2'
    assert document(api)['region'] == 4
    before = basic_game.cfg.read_bytes()
    fake_game.cvar_overrides.clear()
    result = save(api, {'region': 7}, 'apply').json()
    assert result['fields']['region']['state'] == 'applied' and result['saved'] is False
    assert basic_game.cfg.read_bytes() == before
    assert save(api, {'server_name': '未保存的新名称'}, 'apply').status_code == 400
    fake_game.missing_cvars.add('sv_region')
    assert api.post('/api/basic-settings/runtime', json={'names': ['region']}).json()['fields']['region']['state'] == 'unverified'


def test_managed_multiplayer_saves_restart_profile_and_checks_capacity(api, panel, basic_game, fake_game):
    from l4d2panel.services.basic_settings import MULTIPLAYER_FILES
    for name in MULTIPLAYER_FILES:
        path = basic_game.root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b'fixture')
    state = panel.dir / 'pack_state'; state.mkdir()
    receipt = {'schema': 1, 'game_dir': str(basic_game.root), 'packs': {'multiplayer': {'version': '1'}}, 'files': {}}
    (state / 'receipt.json').write_text(json.dumps(receipt))
    result = save(api, {'coop_players': 12}).json()
    assert result['saved'] and result['fields']['coop_players']['state'] == 'restart_required'
    assert result['restart_required'] and document(api)['coop_players'] == 12
    assert fake_game.state['cvars']['sv_maxplayers'] == '4'
    assert '+sv_setmax' not in '\n'.join(fake_game.commands)
    for key in ('sv_maxplayers', 'l4d_multislots_max_survivors'): fake_game.state['cvars'][key] = '12'
    assert save(api, {'coop_players': 12}, 'apply').json()['fields']['coop_players']['state'] == 'applied'
    assert save(api, {'coop_players': 8}, 'apply').status_code == 400
    receipt['packs']['infected'] = {'version': '1'}
    (state / 'receipt.json').write_text(json.dumps(receipt))
    ib = basic_game.sm / 'data/l4dinfectedbots'
    for name in ('coop', 'te8', 'te12', 'te16'):
        (ib / (name + '.cfg')).write_text('"Settings" { "default" { "max_specials" "16" "tank_limit" "1" } }')
    assert save(api, {'coop_players': 12}, 'save').status_code == 200
    (ib / 'te16.cfg').write_text('"Settings" { "default" { "max_specials" "20" "tank_limit" "1" } }')
    before = basic_game.cfg.read_bytes(); fake_game.commands.clear()
    assert save(api, {'coop_players': 12}).status_code == 409
    assert basic_game.cfg.read_bytes() == before and fake_game.commands == []
