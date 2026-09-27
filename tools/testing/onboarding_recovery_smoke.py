#!/usr/bin/env python3
"""Actual HTTP/process/Docker recovery with a protocol fixture, not a game engine.

Pass --release-panel from a verified extracted release and --official-cache from
the separately downloaded pinned L4DToolZ archive. No production paths are used.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import socketserver
import struct
import subprocess
import sys
import tempfile
import threading
import time
import uuid

import httpx


def free_port():
    with socket.socket() as stream:
        stream.bind(('127.0.0.1', 0))
        return stream.getsockname()[1]


def wait(fn, timeout=90):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = fn()
        if value: return value
        time.sleep(.2)
    raise AssertionError('timed out')


def serve(root):
    import uvicorn
    from l4d2panel.context import build_context
    from l4d2panel.main import create_app
    from l4d2panel.settings import Settings
    from l4d2panel.integrations import game_installer
    conf = root / 'panel.json'
    settings = Settings.model_validate_json(conf.read_text())
    original = game_installer.render_compose
    def local_compose(*args, **kwargs):
        value = json.loads(original(*args, **kwargs))
        service = value['services']['l4d2']
        service['ports'] = ['127.0.0.1:' + port for port in service['ports']]
        return json.dumps(value)
    game_installer.render_compose = local_compose
    ctx = build_context(settings, root, conf)
    if (root / 'retry-image').exists():
        ctx.game_install.installer.image_override = (root / 'retry-image').read_text().strip()
    uvicorn.run(create_app(ctx), host='127.0.0.1', port=settings.port, log_level='warning')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--release-panel', type=Path)
    parser.add_argument('--official-cache', type=Path)
    parser.add_argument('--serve', type=Path)
    args = parser.parse_args()
    if args.serve: return serve(args.serve)
    if not args.release_panel or not args.official_cache: parser.error('release and official cache required')
    release = args.release_panel.resolve()
    if not (release / 'packs/manifest.json').is_file(): parser.error('verified extracted release required')
    root = Path(tempfile.mkdtemp(prefix='l4d2-onboarding-recovery-', dir='/var/tmp'))
    root.chmod(0o700)
    repo = Path(__file__).resolve().parents[2]
    image = 'panel-recovery-' + uuid.uuid4().hex[:10] + ':local'
    build = root / 'image'; build.mkdir()
    game = build / 'left4dead2'; (game / 'bin').mkdir(parents=True)
    for name in ('steam.inf', 'gameinfo.txt', 'bin/server_srv.so'):
        (game / name).write_text('protocol fixture\n')
    (build / 'game.py').write_text((repo / 'panel/tests/fakes/game.py').read_text().replace("('127.0.0.1',", "('0.0.0.0',"))
    shutil.copy(repo / 'panel/tests/docker/game_server.py', build / 'game_server.py')
    (build / 'srcds_run').write_text('#!/bin/sh\nexec python3 /fixture/game_server.py "$@"\n')
    (build / 'Dockerfile').write_text('FROM python:3.12-slim\nCOPY game.py game_server.py /fixture/\n'
        'COPY left4dead2 /l4d2/left4dead2\nCOPY srcds_run /l4d2/srcds_run\n'
        'RUN chmod 755 /l4d2/srcds_run\nCMD ["sleep", "infinity"]\n')
    with (root / 'build.log').open('w') as log:
        subprocess.run(['docker', 'build', '--pull=false', '-t', image, str(build)], stdout=log, stderr=subprocess.STDOUT, check=True)
    gate, entered = threading.Event(), threading.Event()
    class BrokenRegistry(socketserver.BaseRequestHandler):
        def handle(self):
            entered.set(); gate.wait(30)
            self.request.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack('ii', 1, 0))
    registry = socketserver.ThreadingTCPServer(('127.0.0.1', 0), BrokenRegistry)
    registry.daemon_threads = True
    threading.Thread(target=registry.serve_forever, daemon=True).start()
    checks, fixtures = [], []
    def check(name, condition):
        assert condition, name
        checks.append(name); print('PASS ' + name, flush=True)
    try:
        for profile in ('minimal', 'full'):
            base = root / profile; base.mkdir()
            project = 'panel-recovery-' + uuid.uuid4().hex[:10]
            config = dict(password='recovery-fixture-password', bootstrap_user='admin', bind='127.0.0.1',
                port=free_port(), tls=False, db=str(base / 'panel.db'), game_dir=str(base / 'game'),
                install_dir=str(base / 'docker'), docker_project=project, rcon_port=free_port(),
                lgsm_script='', display_host='127.0.0.1')
            (base / 'panel.json').write_text(json.dumps(config)); (base / 'panel.json').chmod(0o600)
            fixture = {'base': base, 'project': project, 'process': None, 'log': None}; fixtures.append(fixture)
            env = dict(os.environ, PYTHONPATH=str(release), PYTHONUNBUFFERED='1')
            url = f'http://127.0.0.1:{config["port"]}'
            def start():
                fixture['log'] = (base / 'panel.log').open('a')
                fixture['process'] = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--serve', str(base)],
                    env=env, cwd=base, stdout=fixture['log'], stderr=subprocess.STDOUT)
                def ready():
                    if fixture['process'].poll() is not None: raise RuntimeError('panel failed; see ' + str(base / 'panel.log'))
                    try: return httpx.get(url + '/api/health', timeout=.5).status_code == 200
                    except httpx.TransportError: return False
                wait(ready, 30)
            def stop():
                process = fixture['process']
                process.terminate(); process.wait(15); fixture['log'].close()
            start()
            c = httpx.Client(base_url=url, timeout=45)
            def request(path, body=None):
                result = c.get(path) if body is None else c.post(path, json=body)
                assert result.status_code == 200, (path, result.status_code, result.text)
                return result.json()
            def login(): request('/api/login', {'username': 'admin', 'password': config['password']})
            def finished(path):
                def value():
                    row = request(path)['job']
                    return row if row and row['state'] != 'running' else None
                return wait(value, 180)
            login()
            selected = ['minimal'] if profile == 'minimal' else ['minimal', 'multiplayer', 'infected', 'points']
            draft = {'game_port': config['rcon_port'], 'tick': 30, 'vac': False, 'packs': selected, 'server_name': '断线恢复验收'}
            request('/api/onboarding', {'step': 'game', 'draft': draft})
            if profile == 'minimal':
                request('/api/install', {'game_port': config['rcon_port'], 'mirror_url': '127.0.0.1:' + str(registry.server_address[1])})
                check('actual Docker download reached fault registry', entered.wait(15))
                c.close(); c = httpx.Client(base_url=url, timeout=45); login()
                check('new HTTP client recovers running install and wizard draft', request('/api/install')['job']['state'] == 'running' and request('/api/onboarding')['draft'] == draft)
                gate.set()
                check('download connection reset is reported without adopting game', finished('/api/install')['state'] == 'error' and not (base / 'game').exists())
            old = request('/api/health')
            stop(); (base / 'retry-image').write_text(image); start()
            current = request('/api/health'); login()
            check(profile + ' new panel process preserves wizard and owner', old['pid'] != current['pid'] and old['boot'] != current['boot'] and request('/api/onboarding')['draft'] == draft)
            request('/api/install', {'game_port': config['rcon_port'], 'mirror_url': '', 'tick': 30})
            check(profile + ' retry installs with actual Docker and cached fixture image', finished('/api/install')['state'] == 'done')
            wait(lambda: request('/api/status')['online'])
            request('/api/onboarding', {'step': 'packs'})
            cached = base / 'pack_state/downloads/l4dtoolz/official.zip'; cached.parent.mkdir(parents=True)
            shutil.copyfile(args.official_cache, cached)
            request('/api/plugin-packs/install', {'packs': selected, 'stop_game': True})
            check(profile + ' real release payload installation completes', finished('/api/plugin-packs')['state'] == 'done')
            request('/api/onboarding', {'step': 'settings'})
            basic = request('/api/basic-settings')['fields']
            result = request('/api/basic-settings', {'revision': basic['revision'], 'mode': 'save', 'server_name': draft['server_name'], 'region': 4})
            check(profile + ' settings save completes without claiming runtime application', result['saved'])
            completed = request('/api/onboarding', {'step': 'join', 'complete': True})
            check(profile + ' wizard completion still leaves public access unverified', completed['complete'] and completed['public_access'] == 'unverified')
            stop(); start(); login()
            check(profile + ' final completion survives actual process restart', request('/api/onboarding')['complete'])
            reopened = request('/api/onboarding', {'step': 'panel', 'reopen': True})
            check(profile + ' reopen preserves draft and installed game', not reopened['complete'] and reopened['draft'] == draft and request('/api/install')['installed'])
            c.close(); stop()
    finally:
        gate.set(); registry.shutdown(); registry.server_close()
        for fixture in fixtures:
            process = fixture['process']
            if process and process.poll() is None:
                process.terminate(); process.wait(15)
            if fixture['log']: fixture['log'].close()
            compose = fixture['base'] / 'docker/docker-compose.yaml'
            if compose.exists():
                subprocess.run(['docker', 'compose', '-p', fixture['project'], '-f', str(compose), 'down'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60, check=True)
        subprocess.run(['docker', 'image', 'rm', image], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30, check=True)
        (root / 'results.json').write_text(json.dumps({'passed': len(checks), 'checks': checks,
            'kind': 'real HTTP, process restart, Docker and final payloads; protocol fixture, not real game engine',
            'download_retry': 'connection-reset registry followed by local cached fixture image; not an external mirror availability claim'}, ensure_ascii=False, indent=2))
        print('Evidence: ' + str(root / 'results.json'), flush=True)


if __name__ == '__main__': main()
