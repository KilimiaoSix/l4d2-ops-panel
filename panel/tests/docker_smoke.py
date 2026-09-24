"""Explicit local Docker end-to-end check, outside the default pytest suite.

Run from panel/: python3 -m tests.docker_smoke
Uses actual Docker, HTTP, RCON and A2S against a protocol fixture (not a real game
engine). Creates a unique project in a temporary directory and cleans its own
containers afterwards. Docker/Python base image must be available.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path

import httpx
import uvicorn

from l4d2panel.context import build_context
from l4d2panel.integrations.game_installer import DockerGameInstaller
from l4d2panel.main import create_app
from l4d2panel.settings import Settings
from tests.conftest import GameDir, free_port
from tests.fakes.vpk import build_vpk


def wait_for(fn, seconds=90):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        value = fn()
        if value: return value
        time.sleep(.2)
    raise AssertionError('timed out')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--keep', action='store_true', help='keep the local panel open for browser checks until Ctrl-C')
    args = parser.parse_args()
    root = Path(tempfile.mkdtemp(prefix='l4d2-docker-smoke-')).resolve()
    project = 'panel-smoke-' + uuid.uuid4().hex[:10]
    image = project + ':local'
    build = root / 'image'; build.mkdir()
    data = GameDir(build / 'left4dead2')
    (data.root / 'steam.inf').write_text('fixture=true\n')
    (data.root / 'gameinfo.txt').write_text('fixture\n')
    (data.root / 'bin').mkdir(); (data.root / 'bin/server_srv.so').write_text('fixture\n')
    fake = Path(__file__).parent / 'fakes/game.py'
    (build / 'game.py').write_text(fake.read_text().replace("('127.0.0.1',", "('0.0.0.0',"))
    shutil.copy(Path(__file__).parent / 'docker/game_server.py', build / 'game_server.py')
    (build / 'srcds_run').write_text('#!/bin/sh\nexec python3 /fixture/game_server.py "$@"\n')
    (build / 'Dockerfile').write_text('FROM python:3.12-slim\nCOPY game.py game_server.py /fixture/\n'
                                    'COPY left4dead2 /l4d2/left4dead2\nCOPY srcds_run /l4d2/srcds_run\n'
                                    'RUN chmod 755 /l4d2/srcds_run\nCMD ["sleep", "infinity"]\n')
    with open(root / 'build.log', 'w') as log:
        subprocess.run(['docker', 'build', '--platform', 'linux/amd64', '-t', image, str(build)], check=True,
                       stdout=log, stderr=subprocess.STDOUT)
    port = free_port()
    config = dict(password='docker-smoke-password', port=free_port(), game_dir=str(root / 'game'),
                  install_dir=str(root / 'install'), docker_project=project, rcon_port=port,
                  lgsm_script='', console_log='', perf_csv='', rcon_password='stale-password')
    settings = Settings(**config)
    ctx = build_context(settings, root)
    ctx.game_install.installer = DockerGameInstaller(ctx.paths.install_dir, ctx.paths.game, project, image_override=image)
    app = create_app(ctx)
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=settings.port, log_level='error'))
    thread = threading.Thread(target=server.run, daemon=True); thread.start()
    wait_for(lambda: server.started)
    c = httpx.Client(base_url=f'http://127.0.0.1:{settings.port}', timeout=45)
    checks = []
    def check(name, condition):
        assert condition, name
        checks.append(name); print('PASS ' + name, flush=True)
    def post(path, body):
        response = c.post(path, json=body)
        assert response.status_code == 200, (path, response.text)
        return response.json()
    def get(path):
        response = c.get(path)
        assert response.status_code == 200, (path, response.text)
        return response.json()
    def action(name):
        assert post('/api/action', {'name': name})['ok']
        wait_for(lambda: ctx.server.state['running'] is None)
        assert '失败' not in ctx.server.state['last'], ctx.server.state
    try:
        post('/api/login', {'username': 'admin', 'password': config['password']})
        post('/api/install', {'game_port': port, 'mirror_url': '', 'tick': 30})
        done = wait_for(lambda: (j if (j := get('/api/install')['job'])['state'] != 'running' else None))
        check('installation via real HTTP + Docker', done['state'] == 'done')
        wait_for(lambda: get('/api/status')['online'])
        status = get('/api/status')
        check('Docker backend, RCON/A2S activation', status['srcds'] and status['features']['docker'] and settings.rcon_password == '')
        check('player list over RCON', len(get('/api/players')['players']) == 2)
        post('/api/difficulty', {'level': 'hard'})
        check('difficulty write/read', get('/api/status')['difficulty'] == 'hard')
        post('/api/preset', {'name': 'te8'})
        check('preset write/read', get('/api/status')['preset'] == 'te8')
        post('/api/damage', {'ff': .25, 'burn': .4})
        check('configuration persisted in shared directory', 'survivor_friendly_fire_factor_expert 0.25' in ctx.paths.server_cfg.read_text())
        post('/api/map', {'map': 'c1m1_hotel'})
        post('/api/points', {'amount': 10, 'target': '@all'})
        post('/api/kick', {'userid': 26})
        check('map, points and kick commands', 'c1m1_hotel' in post('/api/rcon', {'cmd': 'status'})['out'])
        post('/api/whitelist', {'op': 'add', 'steamid': 'STEAM_1:0:123', 'note': 'docker'})
        check('whitelist shared-file write', 'STEAM_1:0:123' in ctx.paths.whitelist.read_text())
        campaign = build_vpk(['maps/docker_smoke.bsp'])
        response = c.post('/api/upload?name=docker_smoke.vpk', content=campaign)
        check('campaign upload to bind mount', response.status_code == 200 and (ctx.paths.addons / 'docker_smoke.vpk').is_file())
        post('/api/addons', {'op': 'delete', 'name': 'docker_smoke.vpk'})
        check('campaign deletion', not (ctx.paths.addons / 'docker_smoke.vpk').exists())
        for op in ['disable', 'enable', 'reload']:
            post('/api/plugins', {'op': op, 'file': 'myplugin'})
        check('plugin lifecycle', (ctx.paths.sm_plugins / 'myplugin.smx').is_file())
        check('Docker log integration', any('Docker protocol fixture ready' in x for x in get('/api/logs?console')['lines']))
        check('performance sampling', get('/api/logs?perfjson')['rows'][-1]['fps'] == 30)
        before = ctx.paths.server_cfg.read_bytes()
        action('monitor')
        check('monitor preserves running container', ctx.server.running())
        action('stop')
        check('stop targets Docker game', not ctx.server.running())
        action('monitor')
        check('monitor does not start stopped game', not ctx.server.running())
        action('start')
        wait_for(lambda: get('/api/status')['online'])
        action('restart')
        wait_for(lambda: get('/api/status')['online'])
        check('restart preserves server.cfg bytes', ctx.paths.server_cfg.read_bytes() == before)
        restored = build_context(Settings(**config), root)
        check('panel restart recovers Docker backend and RCON port', restored.settings.server_backend == 'docker' and restored.game.rcon.port == port)
        check('panel restart reads correct RCON secret', 'hostname' in restored.game.rcon.run('status'))
        result = {'passed': len(checks), 'checks': checks, 'kind': 'real Docker with protocol fixture', 'project': project}
        (root / 'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(f'Evidence: {root / "results.json"}', flush=True)
        if args.keep:
            print(f'LOCAL_PANEL=http://127.0.0.1:{settings.port}/#/server', flush=True)
            try:
                while True: time.sleep(1)
            except KeyboardInterrupt:
                pass
    finally:
        c.close(); server.should_exit = True; thread.join(timeout=10)
        if (root / 'install/docker-compose.yaml').exists():
            subprocess.run(['docker', 'compose', '-p', project, '-f', str(root / 'install/docker-compose.yaml'), 'down'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
        subprocess.run(['docker', 'image', 'rm', image], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)


if __name__ == '__main__': main()
