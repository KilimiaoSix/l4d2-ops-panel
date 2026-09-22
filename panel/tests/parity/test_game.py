"""Game settings and quick actions: preset, difficulty, damage factors, map change, points, kick, raw RCON, LinuxGSM."""
import glob

import pytest


def test_preset_switch_and_status_refresh(api, fake_game):
    r = api.post('/api/preset', json={'name': 'te8'})
    assert r.status_code == 200 and 'te8' in r.json()['out'] and fake_game.commands[-1] == 'sm_preset te8'
    assert api.get('/api/status').json()['preset'] == 'te8'
    assert api.post('/api/preset', json={'name': 'te99'}).status_code == 400
    assert api.post('/api/preset', json={}).status_code == 400


def test_difficulty_locks_then_sets(api, fake_game):
    r = api.post('/api/difficulty', json={'level': 'hard'})
    assert r.status_code == 200 and 'out' in r.json()
    assert fake_game.commands[-2:] == ['l4d2_force_difficulty Hard', 'z_difficulty Hard']
    assert api.get('/api/status').json()['difficulty'] == 'hard'
    assert api.post('/api/difficulty', json={'level': 'nightmare'}).status_code == 400


def test_damage_factors_apply_live_and_persist_to_server_cfg(api, fake_game, game_dir):
    before = game_dir.cfg.read_text(encoding='latin-1')
    r = api.post('/api/damage', json={'ff': 0.3, 'burn': 2})          # burn is clamped to 1
    assert r.status_code == 200 and r.json()['persisted'] is True
    sent = fake_game.commands[-8:]
    assert sent == [f'sm_cvar survivor_friendly_fire_factor_{d} 0.3' for d in ('easy', 'normal', 'hard', 'expert')] + [f'sm_cvar survivor_burn_factor_{d} 1' for d in ('easy', 'normal', 'hard', 'expert')]
    after = game_dir.cfg.read_text(encoding='latin-1')
    assert 'sm_cvar survivor_friendly_fire_factor_expert 0.3' in after and 'survivor_friendly_fire_factor_expert 0.1' not in after   # existing line replaced in place
    assert 'sm_cvar survivor_burn_factor_easy 1' in after and 'survivor_burn_factor_easy 0.5' not in after                          # even one without the sm_cvar prefix
    assert after.count('sm_cvar survivor_burn_factor_hard 1') == 1 and 'rcon_password' in after and 'sv_gametypes "coop,versus"' in after
    backups = glob.glob(str(game_dir.cfg) + '.bak-panel-*')
    assert len(backups) == 1 and open(backups[0], encoding='latin-1').read() == before
    st = api.get('/api/status').json()
    assert st['ff'] == 0.3 and st['burn'] == 1.0
    assert api.post('/api/damage', json={}).status_code == 400


def test_damage_single_factor(api, fake_game):
    r = api.post('/api/damage', json={'ff': -1})                          # clamped to 0
    assert r.status_code == 200 and fake_game.commands[-4:] == [f'sm_cvar survivor_friendly_fire_factor_{d} 0' for d in ('easy', 'normal', 'hard', 'expert')]


def test_change_map(api, fake_game):
    r = api.post('/api/map', json={'map': 'c1m1_hotel'})
    assert r.status_code == 200 and 'out' in r.json() and fake_game.commands[-1] == 'changelevel c1m1_hotel'
    assert api.post('/api/map', json={'map': 'c1m1_hotel; quit'}).status_code == 400
    assert api.post('/api/map', json={}).status_code == 400


def test_give_points_targets(api, fake_game):
    for body, cmd in [({'amount': 200, 'target': '@all'}, 'sm_givepoints @all 200'),
                      ({'amount': 50, 'target': '#26'}, 'sm_givepoints #26 50'),
                      ({'amount': 5, 'target': 'Bob "the" Builder'}, 'sm_givepoints "Bob the Builder" 5'),
                      ({'amount': 7}, 'sm_givepoints @all 7'),
                      ({'amount': 7, 'target': '  '}, 'sm_givepoints @all 7')]:
        r = api.post('/api/points', json=body)
        assert r.status_code == 200 and 'out' in r.json() and fake_game.commands[-1] == cmd, body


def test_kick(api, fake_game):
    r = api.post('/api/kick', json={'userid': 26, 'reason': 'bye "now"'})
    assert r.status_code == 200 and fake_game.commands[-1] == 'kickid 26 "bye now"'
    api.post('/api/kick', json={'userid': '116'})
    assert fake_game.commands[-1] == 'kickid 116 "由管理面板踢出"'
    assert api.post('/api/kick', json={'userid': 'bob'}).status_code == 400


def test_raw_rcon(api, fake_game):
    r = api.post('/api/rcon', json={'cmd': 'sm version'})
    assert r.status_code == 200 and r.json() == {'out': 'echo: sm version'}
    assert api.post('/api/rcon', json={'cmd': '   '}).status_code == 400


def test_rcon_noise_lines_are_dropped(api, fake_game):
    fake_game.state['preset'] = 'auto'
    fake_game.status_text = 'L 09/22/2026 - 12:00:00: "x" say "hi"\n[SM] Changed cvar "z_difficulty" to "Normal".\nserver_cvar: "mp_gamemode" "coop"\nreal line 1\n\nreal line 2'
    assert api.post('/api/rcon', json={'cmd': 'status'}).json()['out'] == 'real line 1\nreal line 2'


def test_lgsm_actions(api, panel, fake_game):
    r = api.post('/api/action', json={'name': 'start'})
    assert r.status_code == 200 and r.json()['ok'] is True and 'running' in r.json()
    panel.wait_for(lambda: 'start' in api.get('/api/status').json()['action']['last'] and api.get('/api/status').json()['action']['running'] is None)
    last = api.get('/api/status').json()['action']['last']
    assert 'start: [  OK  ] Fake LinuxGSM: start done' in last
    assert (panel.tmp / 'lgsm.log').read_text().split() == ['start']
    assert api.post('/api/action', json={'name': 'format'}).status_code == 400
    assert api.post('/api/action', json={'name': 'monitor'}).json()['ok'] is True
    panel.wait_for(lambda: (panel.tmp / 'lgsm.log').read_text().split() == ['start', 'monitor'])


@pytest.mark.panel(lgsm_script='')
def test_lgsm_actions_refused_without_a_script(api):
    r = api.post('/api/action', json={'name': 'start'})
    assert r.status_code == 400 and 'LinuxGSM' in r.json()['error']
