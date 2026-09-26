"""Opt-in isolated real-engine installation test (non-root, independent Compose project).

Run this beside a candidate's panel.py with that candidate on PYTHONPATH. It binds
both HTTP and game ports to localhost and never references an existing game tree.
Keeps evidence/data; finally stops the test container unless --keep was requested.
"""
import argparse
import http.cookiejar
import json
import os
from pathlib import Path
import secrets
import socket
import sys
import threading
import time
import urllib.error
import urllib.request

import uvicorn

from l4d2panel.context import build_context
from l4d2panel.integrations import game_installer
from l4d2panel.main import create_app
from l4d2panel.settings import Settings


def free_port():
    with socket.socket() as tcp, socket.socket(type=socket.SOCK_DGRAM) as udp:
        tcp.bind(('127.0.0.1', 0)); port = tcp.getsockname()[1]
        udp.bind(('127.0.0.1', port)); return port


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', type=Path, required=True)
    parser.add_argument('--image', required=True)
    parser.add_argument('--keep', action='store_true')
    parser.add_argument('--resume', action='store_true', help='Reuse only this fixture\'s owned game after an installation failure')
    parser.add_argument('--official-cache', type=Path)
    args = parser.parse_args()
    if os.geteuid() == 0: raise SystemExit('Run under the dedicated non-root test identity')
    base = args.base.resolve()
    base.mkdir(parents=True, exist_ok=True)
    config = base / 'panel.json'
    if not args.resume and (config.exists() or (base / 'game').exists()): raise SystemExit('Use a fresh, empty test base')
    port, game_port = free_port(), free_port()
    password = secrets.token_urlsafe(24)
    settings = Settings(password=password, port=port, bind='127.0.0.1', game_dir=str(base / 'game'),
                        install_dir=str(base / 'docker'), db=str(base / 'panel.db'), lgsm_script='',
                        rcon_port=game_port, console_log='', perf_csv='', depotdownloader='',
                        docker_project='l4d2-beginner-' + secrets.token_hex(4), display_host=f'127.0.0.1:{game_port}')
    if args.resume:
        settings = Settings.model_validate_json(config.read_text())
        if (settings.game_dir != str(base / 'game') or settings.install_dir != str(base / 'docker')
                or not settings.docker_project.startswith('l4d2-beginner-') or settings.bind != '127.0.0.1'):
            raise SystemExit('Not an isolated fixture configuration')
        password, game_port = settings.password, settings.rcon_port
    else:
        config.write_text(settings.model_dump_json()); config.chmod(0o600)
    # Only the isolated fixture changes publish addresses; the production renderer
    # and generated command, ownership, volumes and installation flow stay intact.
    render_compose = game_installer.render_compose
    def local_compose(*a, **kw):
        value = json.loads(render_compose(*a, **kw))
        service = value['services']['l4d2']
        service['ports'] = ['127.0.0.1:' + p for p in service['ports']]
        return json.dumps(value, indent=2) + '\n'
    game_installer.render_compose = local_compose
    ctx = build_context(settings, base, config)
    ctx.game_install.installer.image_override = args.image
    if args.resume:
        installer = ctx.game_install.installer
        if not installer.installed(): raise SystemExit('No complete, owned test installation to resume')
        ctx.server.backend.run('stop')
        (base / 'game/.l4d2-panel-start.sh').write_text(game_installer.START_SCRIPT)
        installer.write_compose(game_installer.InstallOptions(game_port=game_port, tick=30, mirror_url=''))
    web = uvicorn.Server(uvicorn.Config(create_app(ctx), host='127.0.0.1', port=port, log_level='warning'))
    worker = threading.Thread(target=web.run, daemon=True); worker.start()
    client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def request(path, body=None):
        req = urllib.request.Request(f'http://127.0.0.1:{port}' + path,
                                     json.dumps(body).encode() if body is not None else None,
                                     {'Content-Type': 'application/json'})
        try:
            with client.open(req, timeout=25) as response: return json.load(response)
        except urllib.error.HTTPError as error:
            raise RuntimeError(f'{path}: {error.code} ' + error.read().decode()[:500]) from None
    def wait(fn, seconds=180):
        end = time.monotonic() + seconds; last = None
        while time.monotonic() < end:
            try:
                value = fn()
                if value: return value
            except Exception as error: last = error
            time.sleep(1)
        raise AssertionError('Timed out waiting for real engine: ' + str(last))
    def job(path, seconds=1800):
        last = ''
        def done():
            nonlocal last
            value = request(path)['job']
            if value['msg'] != last:
                last = value['msg']; print(last, flush=True)
            if value['state'] == 'error': raise RuntimeError(value['msg'])
            return value if value['state'] == 'done' else None
        # Job errors are terminal, not a liveness retry.
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            value = done()
            if value: return value
            time.sleep(1)
        raise AssertionError('Job timed out')
    checks = []; outputs = {}
    def check(name, condition):
        assert condition, name
        checks.append(name); print('PASS ' + name, flush=True)
    def command(value): return request('/api/rcon', {'cmd': value})['out']
    def start():
        request('/api/action', {'name': 'start'})
        return wait(lambda: request('/api/status').get('online'), 240)
    try:
        wait(lambda: web.started, 30)
        request('/api/login', {'username': 'admin', 'password': password})
        if args.resume:
            outputs['resumed_owned_installation'] = True
            start()
        else:
            check('fresh reads do not create game target', not (base / 'game').exists() and request('/api/plugin-packs')['game_installed'] is False)
            request('/api/install', {'game_port': game_port, 'tick': 30, 'vac': False, 'mirror_url': ''})
            job('/api/install')
        wait(lambda: request('/api/status').get('online'), 240)
        check('real Docker game install responds via RCON and A2S', request('/api/install')['installed'])
        outputs['vanilla_status'] = command('status')
        request('/api/plugin-packs/install', {'packs': ['minimal'], 'stop_game': True})
        job('/api/plugin-packs')
        check('minimal installation stops the real game', not ctx.server.running())
        start()
        wait(lambda: request('/api/status')['features']['sourcemod'], 60)
        outputs['minimal_plugins'] = command('sm plugins list')
        check('minimal framework whitelist and hostname load', request('/api/plugin-packs?probe=true')['packs'][0]['state'] == 'active')
        check('minimal preset tool does not claim unavailable infected stack', request('/api/status')['features']['preset'] is False)
        hostname = '中文开服验收 · 朋友合作'
        name_file = base / 'game/addons/sourcemod/data/panel_hostname.txt'
        name_file.write_text(hostname + '\n', encoding='utf-8')
        expected = hostname.encode().hex()
        receipt = command('sm_panel_hostname_reload'); outputs['hostname_initial'] = receipt
        check('real hostname exact UTF-8 hex receipt', f'expected={expected} actual={expected} state=ok' in receipt)
        command('hostname "ASCII fallback"')
        check('hostname survives later engine cfg overwrite while idle', f'actual={expected} state=ok' in command('sm_panel_hostname_status'))
        try:
            command('changelevel c2m1_highway')
        except RuntimeError as error:
            if 'RCON connection closed' not in str(error) and 'timed out' not in str(error): raise
            outputs['map_command_disconnect'] = str(error)
        # A map change can close its RCON connection before the reply. Verify the
        # new map and exact hostname, rather than treating send/close as success.
        wait(lambda: 'c2m1_highway' in command('status') and
             f'actual={expected} state=ok' in command('sm_panel_hostname_status'), 120)
        check('hostname survives real map change', True)
        request('/api/action', {'name': 'stop'})
        wait(lambda: not ctx.server.running(), 30); start()
        wait(lambda: f'actual={expected} state=ok' in command('sm_panel_hostname_status'), 60)
        check('hostname survives complete game restart', True)
        # Optional trusted cache comes from the same pinned official download fetched
        # on the operator's computer. It is not part of the public release archive.
        if args.official_cache:
            target = base / 'pack_state/downloads/l4dtoolz/official.zip'; target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(args.official_cache.read_bytes()); target.chmod(0o600)
            outputs['official_download_source'] = 'operator cache, pinned hash checked by actual installer'
        else: outputs['official_download_source'] = 'server direct official HTTPS request'
        request('/api/plugin-packs/install', {'packs': ['minimal', 'multiplayer', 'infected', 'points'], 'stop_game': True})
        job('/api/plugin-packs')
        check('full expansion retains Chinese hostname file', name_file.read_text(encoding='utf-8') == hostname + '\n')
        start(); time.sleep(3)
        outputs['full_plugins'] = command('sm plugins list'); outputs['extensions'] = command('sm exts list')
        outputs['metamod'] = command('meta version'); outputs['server_plugins'] = command('plugin_print')
        rows = request('/api/plugin-packs?probe=true')['packs']
        check('all selected package dependencies actively load', all(p['state'] == 'active' for p in rows))
        error_files = sorted((base / 'game/addons/sourcemod/logs').glob('errors_*.log'))
        outputs['plugin_errors'] = '\n'.join(p.read_text(errors='replace') for p in error_files)
        check('no signature native or patch failures in fresh plugin logs', not outputs['plugin_errors'].strip())
        print('Test HTTP on localhost:' + str(port), flush=True)
        if args.keep:
            print('Preview retained; read the private test config for its generated credential.', flush=True)
            while True: time.sleep(30)
    finally:
        (base / 'real-game-results.json').write_text(json.dumps({'passed': len(checks), 'checks': checks,
            'outputs': outputs, 'project': settings.docker_project, 'http_port': port, 'game_port': game_port,
            'kind': 'actual game engine in isolated Docker; no external client or fifth-human validation'}, ensure_ascii=False, indent=2), encoding='utf-8')
        if not args.keep:
            try: ctx.server.backend.run('stop')
            except Exception: pass
        web.should_exit = True; worker.join(timeout=20)


if __name__ == '__main__': main()
