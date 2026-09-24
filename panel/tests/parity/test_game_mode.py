"""Native modes through real HTTP, config files and RCON; no live server is touched."""
import re

import pytest


@pytest.fixture
def mode_game(fake_game):
    return fake_game


def test_mode_catalog_and_fresh_state(api, mode_game):
    result = api.get('/api/game-mode')
    assert result.status_code == 200
    assert result.headers['cache-control'] == 'no-store'
    data = result.json()
    assert len(data['modes']) == 24
    assert {mode['id'] for mode in data['modes'] if mode['group'] == '基础模式'} == {'coop', 'realism', 'versus', 'survival', 'scavenge'}
    assert len({mode['id'] for mode in data['modes']}) == 24
    assert data['mode'] == 'coop' and data['map'] == 'c2m1_highway' and data['read_error'] is None
    mode_game.state['cvars']['mp_gamemode'] = 'mutation19'
    assert api.get('/api/game-mode').json()['mode'] == 'mutation19'


@pytest.mark.parametrize('mode,map_name', [('coop', 'c1m1_hotel'), ('realism', 'c1m1_hotel'), ('versus', 'c1m1_hotel'),
                                          ('survival', 'c1m4_atrium'), ('scavenge', 'c1m4_atrium')])
def test_switch_sends_mode_then_reload_and_reports_request_only(api, mode_game, game_dir, panel, mode, map_name):
    before = game_dir.cfg.read_bytes()
    response = api.post('/api/game-mode', json={'mode': mode})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['state'] == 'switching' and data['mode'] == mode and data['map'] == map_name
    commands = mode_game.commands
    write = commands.index('sm_cvar mp_gamemode ' + mode)
    assert commands[write:write + 3] == ['sm_cvar mp_gamemode ' + mode, 'sm_cvar mp_gamemode', 'changelevel ' + map_name]
    assert data['persisted'] is True
    assert f'sm_cvar mp_gamemode "{mode}"' in game_dir.cfg.read_text()
    assert game_dir.cfg.with_name(data['backup']).read_bytes() == before
    current = api.get('/api/game-mode').json()
    assert current['mode'] == mode and current['map'] == map_name
    assert current['saved_mode'] == mode and current['config_error'] is None
    assert ('admin', 'game.mode') in panel.audit_actions()
    repeated = api.post('/api/game-mode', json={'mode': mode})
    assert repeated.status_code == 409
    assert commands.count('changelevel ' + map_name) == 1


def test_saved_mode_survives_realistic_server_cfg_reload(api, mode_game, game_dir):
    original_bytes = game_dir.cfg.read_bytes() + b'sm_cvar mp_gamemode "coop" // fixed default\nmp_gamemode coop\n'
    game_dir.cfg.write_bytes(original_bytes)
    original_reply = mode_game.reply

    def reply(command):
        output = original_reply(command)
        if command.startswith('changelevel '):
            # The real server runs server.cfg again at every map load.
            values = re.findall(r'(?m)^(?:sm_cvar\s+)?mp_gamemode\s+"?([a-z]+)', game_dir.cfg.read_text())
            mode_game.state['cvars']['mp_gamemode'] = values[-1]
        return output

    mode_game.reply = reply
    response = api.post('/api/game-mode', json={'mode': 'realism'})
    assert response.status_code == 200, response.text
    assert api.get('/api/game-mode').json()['mode'] == 'realism'
    assert api.get('/api/game-mode').json()['saved_mode'] == 'realism'
    assert game_dir.cfg.with_name(response.json()['backup']).read_bytes() == original_bytes


def test_unwritable_or_unsafe_config_stops_before_game_write(api, mode_game, game_dir):
    # Symlinks are intentionally refused even when their target is writable.
    real = game_dir.cfg.with_name('original.cfg')
    game_dir.cfg.rename(real)
    game_dir.cfg.symlink_to(real)
    before = real.read_bytes()
    response = api.post('/api/game-mode', json={'mode': 'versus'})
    assert response.status_code == 500
    assert real.read_bytes() == before
    assert not any(command.startswith(('sm_cvar mp_gamemode ', 'changelevel ')) for command in mode_game.commands)
    state = api.get('/api/game-mode').json()
    assert state['mode'] == 'coop' and state['config_error']


@pytest.mark.parametrize('body', [{}, {'mode': 'mutation999'}, {'mode': 'coop; quit'}, {'mode': 'coop\nquit'}])
def test_invalid_mode_never_sends_commands(api, mode_game, body):
    before = list(mode_game.commands)
    assert api.post('/api/game-mode', json=body).status_code == 400
    assert mode_game.commands == before


def test_mode_routes_require_login(panel, mode_game):
    with panel.client() as anonymous:
        assert anonymous.get('/api/game-mode').status_code == 401
        assert anonymous.post('/api/game-mode', json={'mode': 'versus'}).status_code == 401
    assert not mode_game.commands


def test_failed_read_is_unknown_and_does_not_reload(api, mode_game):
    original = mode_game.reply
    mode_game.reply = lambda cmd: 'Unknown command "sm_cvar"' if cmd.startswith('sm_cvar mp_gamemode') else original(cmd)
    data = api.get('/api/game-mode').json()
    assert data['mode'] is None and data['read_error']
    assert len(data['modes']) == 24
    response = api.post('/api/game-mode', json={'mode': 'versus'})
    assert response.status_code == 502
    assert not any(c.startswith('changelevel ') for c in mode_game.commands)


def test_mode_write_not_accepted_never_reloads(api, mode_game, game_dir):
    before = game_dir.cfg.read_bytes()
    original = mode_game.reply
    mode_game.reply = lambda cmd: '' if cmd == 'sm_cvar mp_gamemode versus' else original(cmd)
    response = api.post('/api/game-mode', json={'mode': 'versus'})
    assert response.status_code == 409
    assert not any(c.startswith('changelevel ') for c in mode_game.commands)
    assert game_dir.cfg.read_bytes() == before


def test_reload_rejection_is_not_success(api, mode_game, panel, game_dir):
    before = game_dir.cfg.read_bytes()
    original = mode_game.reply
    mode_game.reply = lambda cmd: 'changelevel failed: map not found' if cmd.startswith('changelevel ') else original(cmd)
    response = api.post('/api/game-mode', json={'mode': 'versus'})
    assert response.status_code == 502 and '重载' in response.json()['error']
    assert ('admin', 'game.mode') in panel.audit_actions()
    assert game_dir.cfg.read_bytes() == before
    assert mode_game.state['cvars']['mp_gamemode'] == 'coop'


def test_mode_after_external_override_is_not_cached(api, mode_game):
    assert api.post('/api/game-mode', json={'mode': 'versus'}).status_code == 200
    assert api.get('/api/game-mode').json()['mode'] == 'versus'
    mode_game.state['cvars']['mp_gamemode'] = 'coop'
    assert api.get('/api/game-mode').json()['mode'] == 'coop'


@pytest.mark.parametrize('mode,map_name', [(f'mutation{i}', 'c1m4_atrium' if i in (10, 13, 15) else 'c1m1_hotel')
                                          for i in range(1, 21) if i != 6])
def test_builtin_mutations_share_save_switch_and_map_rules(api, mode_game, game_dir, panel, mode, map_name):
    before = game_dir.cfg.read_bytes()
    response = api.post('/api/game-mode', json={'mode': mode})
    assert response.status_code == 200, response.text
    assert response.json()['persisted'] is True and response.json()['map'] == map_name
    assert mode_game.commands[-1] == 'changelevel ' + map_name
    assert game_dir.cfg.with_name(response.json()['backup']).read_bytes() == before
    current = api.get('/api/game-mode').json()
    assert current['mode'] == current['saved_mode'] == mode
    assert current['map'] == map_name
    assert ('admin', 'game.mode') in panel.audit_actions()


@pytest.mark.parametrize('mode', ['mutation6', 'mutation21', 'teamversus', 'realismversus', 'custommode'])
def test_modes_without_verified_catalog_entry_are_rejected(api, mode_game, game_dir, mode):
    before = game_dir.cfg.read_bytes()
    commands = list(mode_game.commands)
    assert api.post('/api/game-mode', json={'mode': mode}).status_code == 400
    assert mode_game.commands == commands and game_dir.cfg.read_bytes() == before
