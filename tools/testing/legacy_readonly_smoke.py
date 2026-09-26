#!/usr/bin/env python3
"""Read-only game/LGSM acceptance using copied panel data and an isolated HTTP app."""
import argparse
import hashlib
import http.cookiejar
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import threading
import time
import urllib.request

import uvicorn
from l4d2panel import __version__
from l4d2panel.context import build_context
from l4d2panel.main import create_app
from l4d2panel.settings import load_settings
from l4d2panel.services.auth import hash_pw


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--base', type=Path, required=True); args = parser.parse_args()
    base = args.base.resolve()
    if os.geteuid() == 0 or not base.name.startswith('panel-acceptance-'):
        raise SystemExit('Use the service user and a separate acceptance directory')
    settings = load_settings(base / 'panel.json')
    if Path(settings.db).parent != base or settings.bind != '127.0.0.1' or settings.server_backend != 'lgsm':
        raise SystemExit('Only isolated DB and localhost LinuxGSM configuration is accepted')
    game = Path(settings.game_dir)
    def game_snapshot():
        files = list((game / 'cfg').rglob('*.cfg')) + list((game / 'addons/sourcemod/plugins').rglob('*.smx'))
        files += [p for p in (game / 'addons/sourcemod/configs').glob('*') if p.is_file()]
        return {str(p.relative_to(game)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    before = game_snapshot()
    production_pid = subprocess.check_output(['systemctl', 'show', 'l4d2panel', '-p', 'MainPID', '--value'])
    ctx = build_context(settings, base, base / 'panel.json')
    password = secrets.token_urlsafe(24)
    # Seed only the copied database; no existing production credential is needed.
    from l4d2panel.store.accounts import AccountStore
    accounts = AccountStore(ctx.db); username = 'isolated_' + secrets.token_hex(5)
    aid = accounts.create(username, hash_pw(password), 'owner')
    with socket.socket() as sock: sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    web = uvicorn.Server(uvicorn.Config(create_app(ctx), host='127.0.0.1', port=port, log_level='warning'))
    thread = threading.Thread(target=web.run, daemon=True); thread.start()
    client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def request(path, body=None):
        req = urllib.request.Request(f'http://127.0.0.1:{port}' + path,
            json.dumps(body).encode() if body is not None else None, headers={'Content-Type': 'application/json'})
        with client.open(req, timeout=30) as response: return json.load(response)
    checks, outputs = [], {}
    try:
        end = time.monotonic() + 15
        while not web.started and time.monotonic() < end: time.sleep(0.1)
        assert web.started
        request('/api/login', {'username': username, 'password': password})
        checks.append('isolated copied database supports existing-account migration and local owner login')
        health = request('/api/health'); assert health['version'] == __version__
        checks.append('candidate HTTP process serves its own version')
        for path in ('/api/status', '/api/plugins', '/api/basic-settings', '/api/panel-config', '/api/onboarding',
                     '/api/game-mode', '/api/addons', '/api/install', '/api/plugin-packs', '/api/accounts'):
            value = request(path)
            checks.append('GET ' + path + ' succeeds against existing LinuxGSM files')
            if path == '/api/status':
                assert value.get('backend', 'lgsm') == 'lgsm' and value['online']
                outputs['online'] = True; outputs['humans'] = value.get('players'); outputs['backend'] = value.get('backend', 'lgsm')
            if path == '/api/onboarding':
                assert value['complete']; outputs['legacy_onboarding_complete'] = True
            if path == '/api/basic-settings': outputs['basic_config_error'] = value['config_error']
        assert game_snapshot() == before
        checks.append('all game CFG, SourceMod plugins and admin/config files remain byte-identical')
        assert subprocess.check_output(['systemctl', 'show', 'l4d2panel', '-p', 'MainPID', '--value']) == production_pid
        checks.append('production panel process was not replaced or restarted')
        outputs['compared_game_files'] = len(before)
    finally:
        web.should_exit = True; thread.join(timeout=20)
        accounts.delete(aid)
        (base / 'legacy-readonly-results.json').write_text(json.dumps({'checks': checks, 'passed': len(checks),
            'version': __version__, 'outputs': outputs, 'scope': 'isolated HTTP and DB; production game read-only; no deployment'}, indent=2))
    print(json.dumps({'passed': len(checks), 'version': __version__, 'outputs': outputs}, indent=2))


if __name__ == '__main__': main()
