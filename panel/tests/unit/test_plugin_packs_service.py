import shutil
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from l4d2panel.context import build_context
from l4d2panel.integrations.pack_files import digest, json_bytes
from l4d2panel.integrations.pack_registry import PackRegistry
from l4d2panel.main import create_app
from l4d2panel.settings import Settings


@pytest.fixture
def pack_app(tmp_path, fake_game):
    s = Settings(password='owner-pass', game_dir=str(tmp_path / 'game'), rcon_port=fake_game.port, rcon_password=fake_game.password)
    conf = tmp_path / 'panel.json'; conf.write_text(s.model_dump_json())
    ctx = build_context(s, tmp_path, conf)
    for name in ('steam.inf', 'gameinfo.txt', 'bin/server_srv.so'):
        path = ctx.paths.game / name; path.parent.mkdir(parents=True, exist_ok=True); path.touch()
    root = tmp_path / 'packs'; root.mkdir()
    shutil.copy(ctx.plugin_packs.registry.root / 'manifest.json', root / 'manifest.json')
    name = 'addons/sourcemod/plugins/test.smx'; source = root / 'payloads/minimal' / name
    source.parent.mkdir(parents=True); source.write_bytes(b'FFPS-test')
    (root / 'payload-manifest.json').write_bytes(json_bytes({'schema': 1, 'payloads': {'minimal': {'version': '1', 'files': [
        {'path': name, 'sha256': digest(source.read_bytes()), 'policy': 'managed'}]}}}))
    ctx.plugin_packs.registry = PackRegistry(root)
    ctx.server.running = lambda: False
    client = TestClient(create_app(ctx)); client.post('/api/login', json={'username': 'admin', 'password': 'owner-pass'})
    return ctx, client


def finish(client):
    for _ in range(300):
        job = client.get('/api/plugin-packs').json()['job']
        if job and job['state'] != 'running': return job
        time.sleep(.01)
    raise AssertionError('plugin job did not finish')


def test_success_receipt_onboarding_status_and_audit(pack_app):
    ctx, client = pack_app
    assert client.get('/api/plugin-packs').headers['cache-control'] == 'no-store'
    assert not ctx.plugin_packs.files.state.exists()
    response = client.post('/api/plugin-packs/install', json={'packs': ['minimal']})
    assert response.status_code == 200 and response.json()['resolved'] == ['minimal']
    job = finish(client); assert job['state'] == 'done' and job['done'] == job['total'] == 1
    assert ctx.panel_state.get('minimal_pack_committed') is True
    assert client.get('/api/onboarding').json()['checks']['packs']['ready']
    minimal = client.get('/api/plugin-packs').json()['packs'][0]
    assert minimal['installed'] and minimal['state'] == 'restart_required' and minimal['runtime'] == 'unknown'
    assert ctx.server.operation_lock.acquire(False); ctx.server.operation_lock.release()
    assert 'packs.install.result' in [r['action'] for r in ctx.audit.recent()]


def test_stop_confirmation_failure_and_no_recursive_lock(pack_app):
    ctx, client = pack_app; running = True
    ctx.server.running = lambda: running
    assert client.post('/api/plugin-packs/install', json={}).status_code == 409
    class Backend:
        def available(self): return True
        def run(self, action):
            assert action == 'stop'
            assert not ctx.server.operation_lock.acquire(False)
    ctx.server.lgsm = Backend()
    assert client.post('/api/plugin-packs/install', json={'stop_game': True}).status_code == 200
    assert finish(client)['state'] == 'error'
    assert not (ctx.paths.sm_plugins / 'test.smx').exists()
    def stop(action):
        nonlocal running
        running = False
    ctx.server.lgsm.run = stop
    assert client.post('/api/plugin-packs/install', json={'stop_game': True}).status_code == 200
    assert finish(client)['state'] == 'done'


def test_shared_lock_blocks_manual_upload_and_configuration_restart(pack_app):
    ctx, client = pack_app; entered = threading.Event(); release = threading.Event()
    original = ctx.plugin_packs.registry.files
    def slow(*args):
        entered.set(); release.wait(3); return original(*args)
    ctx.plugin_packs.registry.files = slow
    try:
        assert client.post('/api/plugin-packs/install', json={}).status_code == 200 and entered.wait(2)
        assert client.post('/api/plugin-packs/install', json={}).status_code == 409
        assert client.post('/api/plugin_upload?name=another.smx', content=b'FFPS').status_code == 409
        assert client.post('/api/plugins', json={'op': 'disable', 'file': 'test'}).status_code == 409
        assert not ctx.server.run('start', 'admin')
        assert client.post('/api/plugin-packs/cancel', json={}).status_code == 200
    finally: release.set()
    assert finish(client)['state'] == 'error'
    assert not (ctx.paths.sm_plugins / 'test.smx').exists()


def test_pending_prevents_start_and_recovery_is_explicit(pack_app):
    ctx, client = pack_app
    ctx.plugin_packs.files.state.mkdir()
    ctx.plugin_packs.files.journal_path.write_bytes(json_bytes({'schema': 1, 'game_dir': str(ctx.paths.game), 'id': 'a' * 32,
        'phase': 'applying', 'entries': [], 'receipt_before': None, 'receipt_after': '{}'}))
    before = ctx.plugin_packs.files.journal_path.read_bytes()
    assert client.get('/api/plugin-packs').json()['pending']['phase'] == 'applying'
    assert ctx.plugin_packs.files.journal_path.read_bytes() == before
    assert client.post('/api/action', json={'name': 'start'}).status_code == 409
    assert client.post('/api/plugin-packs/install', json={}).status_code == 409
    assert client.post('/api/plugin-packs/recover', json={}).status_code == 200
    assert finish(client)['state'] == 'done' and ctx.plugin_packs.files.pending() is None


def test_actual_source_plugin_titles_satisfy_runtime_probes(pack_app):
    # Titles captured from build 10097 in the isolated real-game Docker test.
    ctx, client = pack_app
    names = ['Private Whitelist', 'Panel Hostname', 'SI Preset',
             '[L4D1 & L4D2] CreateSurvivorBot', '[L4D(2)] MultiSlots Improved',
             '[L4D1/2] Manual-Spawn Special Infected', '[L4D2]Zombie Spawn Fix',
             '[L4D & 2] Unrestrict Panic Battlefield', '[L4D & L4D2] Left 4 DHooks Direct',
             '[L4D/L4D2] Infected Bots (Coop/Versus/Realism/Scavenge/Survival/Mutation)',
             'Points System', '[PS] Map Reset']
    plugins = '[SM] Listing 12 plugins:\n' + '\n'.join(f' {i:02d} "{name}" (1.0)' for i, name in enumerate(names, 1))
    ctx.plugin_packs.rcon.run = lambda cmd: '0: "L4DToolZ v2.5.1"' if cmd == 'plugin_print' else plugins
    assert all(p['runtime'] == 'active' for p in client.get('/api/plugin-packs?probe=true').json()['packs'])
