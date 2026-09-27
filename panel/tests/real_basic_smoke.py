"""Opt-in HTTP/basic-settings acceptance on a stopped real_game_smoke fixture.

Reuses only the named fixture's owned Docker game. No external client claims.
Never prints or puts join/owner/RCON passwords in the evidence document.
"""
import argparse
import http.cookiejar
import json
import os
import re
from pathlib import Path
import secrets
import socket
import threading
import time
import urllib.error
import urllib.request

import uvicorn

from l4d2panel.context import build_context
from l4d2panel import __version__
from l4d2panel.integrations.hostname_file import parse_name_receipt
from l4d2panel.main import create_app
from l4d2panel.settings import Settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', type=Path, required=True)
    parser.add_argument('--upgrade-packs', action='store_true')
    args = parser.parse_args()
    if os.geteuid() == 0: raise SystemExit('Use the dedicated non-root test identity')
    base = args.base.resolve(); config = base / 'panel.json'
    settings = Settings.model_validate_json(config.read_text())
    previous = json.loads((base / 'real-game-results.json').read_text())
    if (settings.game_dir != str(base / 'game') or settings.install_dir != str(base / 'docker')
            or not settings.docker_project.startswith('l4d2-beginner-')
            or settings.docker_project != previous['project'] or settings.bind != '127.0.0.1'):
        raise SystemExit('Not an isolated fixture configuration')
    ctx = build_context(settings, base, config)
    if not ctx.game_install.installer.installed() or ctx.server.running():
        raise SystemExit('The owned fixture must be installed and stopped')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    web = uvicorn.Server(uvicorn.Config(create_app(ctx), host='127.0.0.1', port=port, log_level='warning'))
    worker = threading.Thread(target=web.run, daemon=True); worker.start()
    client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    checks, outputs = [], {}

    def request(path, body=None):
        req = urllib.request.Request(f'http://127.0.0.1:{port}' + path,
            json.dumps(body).encode() if body is not None else None, {'Content-Type': 'application/json'})
        try:
            with client.open(req, timeout=30) as response: return json.load(response)
        except urllib.error.HTTPError as error:
            # Never include arbitrary error body which might quote submitted secrets.
            raise RuntimeError(f'{path}: HTTP {error.code}') from None

    def wait(fn, seconds=120):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            try:
                value = fn()
                if value: return value
            except Exception: pass
            time.sleep(1)
        raise AssertionError('Timed out waiting for real game check')

    def check(name, condition):
        assert condition, name
        checks.append(name); print('PASS ' + name, flush=True)

    def document(): return request('/api/basic-settings')
    def save(values, mode='save_apply'):
        return request('/api/basic-settings', {'revision': document()['fields']['revision'], 'mode': mode, **values})
    def runtime(names): return request('/api/basic-settings/runtime', {'names': names})['fields']
    def command(value): return ctx.game.rcon.run(value)
    def start():
        request('/api/action', {'name': 'start'})
        wait(lambda: parse_name_receipt(command('sm_panel_hostname_status')), 240)
    def restart():
        request('/api/action', {'name': 'stop'})
        wait(lambda: not ctx.server.running(), 30)
        start()

    try:
        wait(lambda: web.started, 30)
        request('/api/login', {'username': settings.bootstrap_user, 'password': settings.password})
        check('managed full package capability available', document()['multiplayer_available'])
        if args.upgrade_packs:
            config_path = base / 'game/cfg/sourcemod/l4d2_points_system.cfg'
            content = config_path.read_text()
            content, count = re.subn(r'(?m)^l4d2_points_start .*$', 'l4d2_points_start "43"', content)
            assert count == 1
            config_path.write_text(content)
            request('/api/plugin-packs/install', {'packs': ['minimal', 'multiplayer', 'infected', 'points'], 'stop_game': False})
            end = time.monotonic() + 180
            while time.monotonic() < end:
                job = request('/api/plugin-packs')['job']
                if job['state'] == 'error': raise AssertionError('Package upgrade failed: ' + job['msg'])
                if job['state'] == 'done': break
                time.sleep(1)
            else: raise AssertionError('Package upgrade timed out')
            check('candidate package upgrade preserves edited Points seed', config_path.read_text() == content)
        start()
        if args.upgrade_packs:
            check('saved Points cfg is automatically loaded', wait(lambda: ctx.basic_settings._cvar('l4d2_points_start') == '43', 30))
        name = '基础设置实机验收 · 合作开黑'
        join_password = secrets.token_urlsafe(16)
        result = save({'server_name': name, 'ascii_fallback': 'Basic acceptance', 'region': 4, 'password': join_password})
        check('HTTP save and live exact Chinese hostname', result['fields']['server_name']['state'] == 'applied')
        check('HTTP region reads back actual engine value', result['fields']['region']['state'] == 'applied')
        check('password outcome remains unverified and redacted', result['fields']['password']['state'] == 'unverified'
              and join_password not in json.dumps(result) + json.dumps(document()))
        check('password omission preserves saved secret', save({'region': 255}, 'save')['saved']
              and document()['fields']['password_set'])
        check('password explicit empty clears saved secret', save({'password': ''})['fields']['password']['state'] == 'unverified'
              and not document()['fields']['password_set'])
        for count in (4, 8, 12):
            result = save({'coop_players': count}, 'save')
            check(f'{count} players saved as pending full restart', result['restart_required'])
            restart()
            expected = ctx.basic_settings._expected_count(count)
            probe = wait(lambda: (value if (value := runtime(['coop_players'])['coop_players']).get('values') == expected else None), 60)
            outputs[f'players_{count}'] = probe
            check(f'{count} players actual six engine cvars after restart', probe['values'] == expected)
            check(f'{count} players clears restart only after readback', not document()['restart_required'])
            check(f'{count} players retains Chinese name after restart', runtime(['server_name'])['server_name']['value'] == name)
        # The bounded hook must stop fighting another plugin after eight corrections.
        command('sm_panel_hostname_reload')
        for index in range(10): command(f'hostname "conflicting plugin {index}"')
        limited = parse_name_receipt(command('sm_panel_hostname_status'))
        outputs['bounded_hostname'] = limited
        check('hostname stops at bounded correction limit', limited['state'] == 'limit')
        check('explicit name reload recovers from bounded limit', save({'server_name': name}, 'apply')['fields']['server_name']['state'] == 'applied')
        try: command('changelevel c2m1_highway')
        except Exception: pass  # Receive close is expected on some map changes; check both outcomes below.
        wait(lambda: 'c2m1_highway' in command('status') and runtime(['server_name'])['server_name']['value'] == name)
        check('HTTP-saved name survives real map change', True)
        probe = runtime(['coop_players'])['coop_players']; outputs['after_map_change'] = probe
        check('12-player limits survive real map change', probe['values'] == ctx.basic_settings._expected_count(12))
        if args.upgrade_packs:
            check('Points saved cfg survives restart and map change', ctx.basic_settings._cvar('l4d2_points_start') == '43')
        onboarding = request('/api/onboarding')
        check('real installed fixture satisfies every wizard prerequisite', not onboarding['missing'])
        finished = request('/api/onboarding', {'step': 'join', 'complete': True})
        check('wizard completion is persisted after real runtime checks', finished['complete'] and request('/api/onboarding')['complete'])
        reopened = request('/api/onboarding', {'step': 'settings', 'reopen': True, 'draft': {'server_name': name, 'region': 4}})
        check('wizard can reopen without losing saved setup', not reopened['complete'] and reopened['draft']['server_name'] == name)
        request('/api/onboarding', {'step': 'join', 'complete': True})
        logs = sorted((base / 'game/addons/sourcemod/logs').glob('errors_*.log'))
        outputs['plugin_errors'] = '\n'.join(path.read_text(errors='replace') for path in logs)
        check('no plugin runtime errors', not outputs['plugin_errors'].strip())
    finally:
        (base / 'real-basic-results.json').write_text(json.dumps({'checks': checks, 'passed': len(checks), 'outputs': outputs,
            'project': settings.docker_project, 'version': __version__, 'kind': 'real engine HTTP and RCON; external clients and fifth human not tested'},
            ensure_ascii=False, indent=2), encoding='utf-8')
        try: ctx.server.backend.run('stop')
        except Exception: pass
        web.should_exit = True; worker.join(timeout=20)


if __name__ == '__main__': main()
