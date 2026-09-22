"""/api/status: A2S + RCON-derived fields, feature detection, cached game flags, degraded and offline paths."""
import subprocess

import pytest

from tests.fakes.game import A2S_INFO

ALL_FEATURES = {'lgsm': True, 'workshop': True, 'console_log': True, 'perf': True, 'sourcemod': True, 'whitelist': True, 'preset': True, 'points': True}


def test_status_online(api, fake_game):
    st = api.get('/api/status').json()
    assert {k: st[k] for k in ('online', 'name', 'map', 'players', 'max', 'bots')} == {'online': True, 'name': A2S_INFO['name'], 'map': 'c2m1_highway', 'players': 2, 'max': 12, 'bots': 5}
    assert st['srcds'] is False and 'degraded' not in st
    assert isinstance(st['sys'], dict) and st['action'] == {'running': None, 'last': ''}
    assert st['account'] == {'user': 'admin', 'role': 'owner'}
    assert st['features'] == ALL_FEATURES
    assert st['title'] == 'Test Panel' and st['display_host'] == 'test.example'
    assert st['perf'] == {'t': '12:00:30', 'fps': '30.0', 'out_kb': 12.3}
    assert {k: st[k] for k in ('preset', 'whitelist', 'difficulty', 'ff', 'burn')} == {'preset': 'te12', 'whitelist': True, 'difficulty': 'normal', 'ff': 0.1, 'burn': 0.5}
    for cmd in ('sm plugins list', 'sm_preset', 'sm_cvar sm_whitelist_enable', 'z_difficulty', 'survivor_friendly_fire_factor_expert', 'survivor_burn_factor_expert'):
        assert cmd in fake_game.commands, cmd
    assert fake_game.auth_failures == 0          # the RCON password came from server.cfg (rcon_password is '' in panel.json)


def test_status_uses_cached_flags_between_polls(api, fake_game):
    api.get('/api/status'); n = len(fake_game.commands)
    api.get('/api/status')
    assert len(fake_game.commands) == n          # features (120 s) and game flags (15 s) are cached; no RCON traffic for a second poll


@pytest.mark.game(a2s_challenge=True)
def test_status_handles_a2s_challenge(api):
    st = api.get('/api/status').json()
    assert st['online'] is True and st['players'] == 2 and st['map'] == 'c2m1_highway'


def test_status_offline_when_game_does_not_answer(api, fake_game):
    fake_game.a2s_on = False
    st = api.get('/api/status').json()
    assert st['online'] is False and st['srcds'] is False and 'degraded' not in st
    assert st['features'] == dict(ALL_FEATURES, sourcemod=False, whitelist=False, preset=False, points=False)
    assert {k: st[k] for k in ('preset', 'whitelist', 'difficulty', 'ff', 'burn')} == {'preset': '', 'whitelist': None, 'difficulty': '', 'ff': None, 'burn': None}
    assert st['account'] == {'user': 'admin', 'role': 'owner'} and st['perf']['fps'] == '30.0'


def test_status_falls_back_to_rcon_when_a2s_is_throttled(api, fake_game):
    fake_game.a2s_on = False
    srcds = subprocess.Popen(['bash', '-c', 'exec -a srcds_linux sleep 120'])   # makes `pgrep -f srcds_linux` succeed off the game host
    try:
        st = api.get('/api/status').json()
    finally:
        srcds.terminate(); srcds.wait(timeout=10)
    assert {k: st.get(k) for k in ('online', 'degraded', 'srcds', 'players', 'bots', 'max', 'map')} == {'online': True, 'degraded': True, 'srcds': True, 'players': 2, 'bots': 5, 'max': 12, 'map': 'c2m1_highway'}
    assert st['name'] == 'Test Panel'              # nothing cached from A2S yet: the panel title stands in for the hostname
    assert st['features'] == ALL_FEATURES and st['preset'] == 'te12'


@pytest.mark.panel(lgsm_script='', console_log='', perf_csv='')
def test_status_hides_features_that_are_not_configured(api):
    st = api.get('/api/status').json()
    assert st['features'] == dict(ALL_FEATURES, lgsm=False, console_log=False, perf=False)
    assert st['perf'] is None
