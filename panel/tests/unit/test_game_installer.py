"""Installer orchestration through authenticated HTTP, including activation and concurrency."""
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from l4d2panel.context import build_context
from l4d2panel.main import create_app
from l4d2panel.settings import Settings


class FakeInstaller:
    def __init__(self, root):
        self.compose_file = root / 'docker-compose.yaml'
        self.options = None
        self.ready = True
        self.complete = False
        self.fail = False
        self.gate = threading.Event()
        self.gate.set()

    def readiness(self):
        return self.ready, '' if self.ready else 'Docker daemon 不可用'

    def available(self):
        return self.ready

    def installed(self):
        return self.complete

    def metadata(self):
        return {'game_port': self.options.game_port, 'tick': self.options.tick, 'vac': self.options.vac,
                'mirror_url': self.options.mirror_url}

    def run(self, options, job):
        self.options = options
        self.gate.wait(3)
        if self.fail: raise RuntimeError('download failed')
        if job.cancel: raise RuntimeError('安装已取消')
        self.complete = True
        job.done = job.total = 1
        job.msg = '容器已启动'


@pytest.fixture
def install_app(tmp_path, fake_game, fake_steam):
    s = Settings(password='owner-pass', db=str(tmp_path / 'db.sqlite'), game_dir=str(tmp_path / 'empty-game'),
                 install_dir=str(tmp_path / 'install'), rcon_host='127.0.0.1', rcon_port=fake_game.port,
                 rcon_password='old-password', steam_api_base=fake_steam.base, steam_community_base=fake_steam.base,
                 lgsm_script='')
    ctx = build_context(s, tmp_path)
    fake = FakeInstaller(tmp_path)
    ctx.game_install.installer = fake
    client = TestClient(create_app(ctx))
    assert client.post('/api/login', json={'username': 'admin', 'password': 'owner-pass'}).status_code == 200
    yield ctx, client, fake
    fake.gate.set()


def finished(c):
    for _ in range(200):
        j = c.get('/api/install').json()['job']
        if j and j['state'] != 'running': return j
        time.sleep(.01)
    raise AssertionError('installer did not finish')


def test_install_activates_same_panel_and_audits_without_secrets(install_app):
    ctx, c, fake = install_app
    response = c.post('/api/install', json={'game_port': 27999, 'mirror_url': ''})
    assert response.status_code == 200, response.text
    assert finished(c)['state'] == 'done'
    assert ctx.settings.server_backend == 'docker'
    assert ctx.game.rcon.host == '127.0.0.1' and ctx.game.rcon.port == 27999
    assert ctx.settings.rcon_password == ''
    assert ctx.status.a2s.port == 27999
    assert fake.options.mirror_url == ''
    assert len(fake.options.rcon_password) >= 16
    status = c.get('/api/install').json()
    assert status['installed'] and status['defaults']['game_port'] == 27999
    assert fake.options.rcon_password not in str(status) + str(ctx.audit.recent())
    assert {'game.install', 'game.install.result'} <= {x['action'] for x in ctx.audit.recent()}
    assert c.post('/api/install', json={}).status_code == 409


def test_failure_does_not_activate_or_hold_lock(install_app):
    ctx, c, fake = install_app
    fake.fail = True
    assert c.post('/api/install', json={}).status_code == 200
    assert finished(c)['state'] == 'error'
    assert ctx.settings.server_backend == 'lgsm'
    assert ctx.server.operation_lock.acquire(blocking=False)
    ctx.server.operation_lock.release()


def test_install_and_server_actions_are_mutually_exclusive(install_app):
    ctx, c, fake = install_app
    fake.gate.clear()
    assert c.post('/api/install', json={}).status_code == 200
    assert c.post('/api/install', json={}).status_code == 409
    assert ctx.server.operation_lock.acquire(blocking=False) is False
    assert c.post('/api/install/cancel', json={}).status_code == 200
    fake.gate.set()
    assert finished(c)['state'] == 'error'
    assert 'game.install.cancel' in [x['action'] for x in ctx.audit.recent()]
    ctx.server.operation_lock.acquire()
    try: assert c.post('/api/install', json={}).status_code == 409
    finally: ctx.server.operation_lock.release()


def test_install_errors_and_auth(install_app):
    ctx, c, fake = install_app
    anon = TestClient(c.app)
    for path in ('/api/install', '/api/install/cancel'):
        assert anon.post(path, json={}).status_code == 401
    for body in ({'game_port': 0}, {'tick': 99}, {'mirror_url': 'bad/$(id)'}, {'game_port': ctx.settings.port},
                 {'manager_port': 27020}):
        assert c.post('/api/install', json=body).status_code == 400
    fake.ready = False
    assert c.get('/api/install').json()['reason'] == 'Docker daemon 不可用'
    assert c.post('/api/install', json={}).status_code == 400
