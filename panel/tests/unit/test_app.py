"""In-process checks through FastAPI's TestClient: things the black-box suite cannot reach (the srcds process check,
audit coverage of every write, error shapes)."""
import pytest
from fastapi.testclient import TestClient

from l4d2panel.context import build_context
from l4d2panel.main import create_app
from l4d2panel.settings import Settings
from tests.conftest import OWNER_PW, OWNER_USER, RCON_PASSWORD


@pytest.fixture
def app_ctx(tmp_path, game_dir, fake_game, fake_steam):
    lgsm = tmp_path / 'lgsm'; lgsm.write_text('#!/bin/bash\necho ok\n'); lgsm.chmod(0o755)
    s = Settings(password=OWNER_PW, db=str(tmp_path / 'panel.db'), rcon_host='127.0.0.1', rcon_port=fake_game.port, rcon_password=RCON_PASSWORD,
                 game_dir=str(game_dir.root), lgsm_script=str(lgsm), console_log='', perf_csv='', depotdownloader='',
                 steam_api_base=fake_steam.base, steam_community_base=fake_steam.base)
    ctx = build_context(s, tmp_path)
    client = TestClient(create_app(ctx))
    assert client.post('/api/login', json={'username': OWNER_USER, 'password': OWNER_PW}).status_code == 200
    return ctx, client


def test_degraded_status_when_a2s_is_silent_but_the_process_lives(app_ctx, fake_game):
    ctx, c = app_ctx
    fake_game.a2s_on = False; ctx.status.process_check = lambda: True
    st = c.get('/api/status').json()
    assert st['online'] is True and st['degraded'] is True and st['srcds'] is True and st['players'] == 2 and st['bots'] == 5 and st['map'] == 'c2m1_highway'
    ctx.status.process_check = lambda: False
    assert c.get('/api/status').json()['online'] is False


def test_every_write_is_audited(app_ctx, fake_game, fake_steam):
    ctx, c = app_ctx
    fake_steam.add_item('100000777', b'x' * 10, file_type=2)
    calls = [('/api/rcon', {'cmd': 'sm version'}), ('/api/preset', {'name': 'te8'}), ('/api/difficulty', {'level': 'hard'}),
             ('/api/damage', {'ff': 0.5}), ('/api/map', {'map': 'c1m1_hotel'}), ('/api/points', {'amount': 1, 'target': '@all'}),
             ('/api/kick', {'userid': 26}), ('/api/whitelist', {'op': 'add', 'steamid': 'STEAM_1:0:5', 'note': 'n'}),
             ('/api/whitelist', {'op': 'del', 'steamid': 'STEAM_1:0:5'}), ('/api/whitelist_enable', {'enable': False}),
             ('/api/addons', {'op': 'delete', 'name': 'custom_campaign.vpk'}), ('/api/addons', {'op': 'workshop', 'id': '100000777'}),
             ('/api/addons', {'op': 'zip', 'name': 'admin_system.vpk'}), ('/api/action', {'name': 'monitor'}),
             ('/api/plugins', {'op': 'reload', 'file': 'myplugin'})]
    for path, body in calls:
        r = c.post(path, json=body); assert r.status_code == 200, (path, r.text)
    actions = [a['action'] for a in ctx.audit.recent()]
    for a in ('login', 'rcon', 'game.preset', 'game.difficulty', 'game.damage', 'game.map', 'game.points', 'game.kick', 'whitelist.add', 'whitelist.del',
              'whitelist.enable', 'addon.delete', 'addon.workshop', 'addon.zip', 'server.monitor', 'plugin.reload'):
        assert a in actions, a
    who = {a['who'] for a in ctx.audit.recent()}
    assert who == {OWNER_USER}


def test_error_shapes(app_ctx):
    ctx, c = app_ctx
    r = c.post('/api/preset', json={'name': 'te99'}); assert r.status_code == 400 and r.json()['error'].startswith('参数无效')
    r = c.post('/api/kick', json={'userid': 'bob'}); assert r.status_code == 400 and 'error' in r.json()
    r = c.post('/api/kick', content=b'not json', headers={'content-type': 'application/json'}); assert r.status_code == 400 and 'error' in r.json()
    r = c.delete('/api/status'); assert r.status_code == 405 and 'error' in r.json()
    r = c.get('/api/nothing/here'); assert r.status_code == 404 and r.json() == {'error': 'not found'}
    anon = TestClient(c.app)
    assert anon.get('/api/nothing/here').status_code == 401
    assert anon.get('/api/docs').status_code == 200                     # the OpenAPI page is public, it holds no data


def test_rcon_failure_is_reported_not_swallowed(app_ctx, fake_game):
    ctx, c = app_ctx
    fake_game.stop()
    r = c.post('/api/rcon', json={'cmd': 'status'})
    assert r.status_code == 500 and 'RCON' in r.json()['error']
