"""Opt-in real systemd restart/recovery checks in an isolated Linux development host.

Run as root in a disposable VM/WSL or systemd container. Refuses any existing
l4d2panel.service. The tested panel runs as nobody, uses private temporary data,
and touches no game directory. Evidence is retained, the temporary unit is removed.
"""
import json
import os
from pathlib import Path
import pwd
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time

import httpx


def cmd(*args, **kw):
    return subprocess.run(args, check=True, capture_output=True, text=True, **kw).stdout.strip()


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0)); return s.getsockname()[1]


def wait_for(fn, seconds=30):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            result = fn()
            if result: return result
        except (httpx.HTTPError, OSError): pass
        time.sleep(.15)
    raise AssertionError('timed out waiting for supervised process')


def main():
    if os.geteuid() != 0: raise SystemExit('Run as root inside an isolated Linux test host')
    state = cmd('systemctl', 'show', 'l4d2panel.service', '-p', 'LoadState', '--value')
    if state != 'not-found': raise SystemExit('Refusing to replace an existing l4d2panel.service')
    unit = Path('/run/systemd/system/l4d2panel.service')
    if unit.exists(): raise SystemExit('Temporary service path already exists')
    root = Path(tempfile.mkdtemp(prefix='l4d2-systemd-smoke-', dir='/var/tmp'))
    base = root / 'app'; base.mkdir()
    outside = root / 'config'; outside.mkdir()
    owner = pwd.getpwnam('nobody')
    for path in (root, base, outside): os.chown(path, owner.pw_uid, owner.pw_gid)
    source = Path(__file__).resolve().parents[1]
    entry = base / 'panel.py'; shutil.copy(source / 'panel.py', entry)
    conf = outside / 'actual.json'
    port = free_port(); password = secrets.token_urlsafe(18)
    raw = dict(port=port, password=password, bind='127.0.0.1', game_dir=str(root / 'never-create-game'),
               lgsm_script='', rcon_port=free_port(), db=str(base / 'panel.db'), console_log='', perf_csv='')
    conf.write_text(json.dumps(raw)); conf.chmod(0o600); os.chown(conf, owner.pw_uid, owner.pw_gid)
    checks = []
    def check(name, condition):
        assert condition, name
        checks.append(name); print('PASS ' + name, flush=True)
    def login(port, tls=False):
        c = httpx.Client(base_url=f'{"https" if tls else "http"}://127.0.0.1:{port}', timeout=5, verify=False)
        try:
            r = c.post('/api/login', json={'username': 'admin', 'password': password})
            if r.status_code == 200: return c
            c.close(); return None
        except Exception:
            c.close(); raise
    def config(c):
        response = c.get('/api/panel-config'); response.raise_for_status(); return response.json()
    def save(c, updates):
        before = config(c)
        response = c.post('/api/panel-config', json={'revision': before['revision'], 'updates': updates, 'restart': True})
        assert response.status_code == 200, response.text
        assert response.json()['restart_scheduled']
        return before
    unit.write_text(f'''[Unit]
Description=Disposable L4D2 panel restart verification
StartLimitIntervalSec=30
StartLimitBurst=6
[Service]
User={owner.pw_uid}
Group={owner.pw_gid}
WorkingDirectory={base}
Environment=PYTHONPATH={source}
Environment=PYTHONUNBUFFERED=1
ExecStart={sys.executable} {entry} --config {conf}
Restart=always
RestartSec=0.3
RestartPreventExitStatus=78
''')
    try:
        cmd('systemctl', 'daemon-reload'); cmd('systemctl', 'start', 'l4d2panel.service')
        c = wait_for(lambda: login(port))
        initial = config(c)
        check('real systemd ownership detected', initial['supervised'])
        check('external configuration path', initial['config_path'] == str(conf))
        check('service runs as nobody', int(cmd('systemctl', 'show', 'l4d2panel.service', '-p', 'User', '--value')) == owner.pw_uid)
        old = save(c, {'session_days': 8})
        wait_for(lambda: config(c)['boot'] != old['boot'])
        check('same-listener restart preserves session and changes boot', config(c)['boot'] != old['boot'])
        check('new process reports applied config revision', config(c)['revision'] == config(c)['applied_revision'])
        port2 = free_port()
        old = save(c, {'port': port2})
        new = wait_for(lambda: login(port2))
        check('new port is served by a new process', config(new)['boot'] != old['boot'])
        with httpx.Client(base_url=f'http://127.0.0.1:{port2}', cookies=c.cookies, timeout=5) as existing:
            check('database sessions survive port change', existing.get('/api/me').status_code == 200)
        c.close(); c = new; port = port2
        cert, key = base / 'cert.pem', base / 'key.pem'
        cmd('openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-subj', '/CN=localhost',
            '-addext', 'subjectAltName=IP:127.0.0.1,DNS:localhost', '-days', '1', '-keyout', str(key), '-out', str(cert))
        for path in (cert, key): path.chmod(0o600); os.chown(path, owner.pw_uid, owner.pw_gid)
        old = save(c, {'tls': True})
        secure = wait_for(lambda: login(port, True))
        check('TLS restart and Secure cookie', config(secure)['boot'] != old['boot'] and any(cookie.secure for cookie in secure.cookies.jar))
        c.close(); c = secure
        old = save(c, {'tls': False})
        plain = wait_for(lambda: login(port))
        check('return from TLS requires and permits a new login', config(plain)['boot'] != old['boot'])
        c.close(); c = plain
        # Force a failure after the candidate passes validation: occupied listener at boot.
        cmd('systemctl', 'stop', 'l4d2panel.service')
        sys.path.insert(0, str(source))
        from l4d2panel.integrations.panel_config import PanelConfigFile
        from l4d2panel.services.panel_restart import RestartJournal
        from l4d2panel.settings import load_settings
        file = PanelConfigFile(conf, base); journal = RestartJournal(file)
        before = file.read()
        with socket.socket() as busy:
            busy.bind(('127.0.0.1', 0)); busy.listen()
            # Write the valid candidate before occupying its port; no mocked exit or restart.
            raw = dict(before.raw, port=busy.getsockname()[1])
            backup = file._backup(before.data)
            from l4d2panel.integrations.panel_config import revision
            candidate = json.dumps(raw).encode()
            journal.prepare(backup, before.revision, revision(candidate))
            file.atomic_write(conf, candidate)
            for path in [conf, journal.path, file.backups, file.backups.parent, file.backups / backup,
                         conf.parent / ('.' + conf.name + '.lock')]:
                if path.exists(): os.chown(path, owner.pw_uid, owner.pw_gid)
            cmd('systemctl', 'start', 'l4d2panel.service')
            recovered = wait_for(lambda: login(port), seconds=45)
        check('failed candidate boot automatically restores exact previous bytes', conf.read_bytes() == before.data)
        wait_for(lambda: not journal.path.exists())
        check('successful rollback clears recovery journal', not journal.path.exists())
        check('game target remains absent throughout', not (root / 'never-create-game').exists())
        recovered.close(); c.close()
        if '--keep' in sys.argv:
            print(f'Browser preview: http://127.0.0.1:{port} user=admin password={password}', flush=True)
            try:
                while True: time.sleep(30)
            except KeyboardInterrupt: pass
    finally:
        logs = cmd('journalctl', '-u', 'l4d2panel.service', '-n', '250', '--no-pager')
        (root / 'service.log').write_text(logs)
        subprocess.run(['systemctl', 'stop', 'l4d2panel.service'], check=False, capture_output=True)
        unit.unlink(); cmd('systemctl', 'daemon-reload')
        (root / 'results.json').write_text(json.dumps({'checks': checks, 'passed': len(checks), 'kind': 'real systemd, non-root process'}, indent=2))
        print('Evidence: ' + str(root), flush=True)


if __name__ == '__main__': main()
