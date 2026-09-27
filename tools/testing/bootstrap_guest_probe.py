#!/usr/bin/env python3
"""Run as root only inside a disposable bootstrap VM; output contains no secrets."""
import hashlib
import http.cookiejar
import json
import os
from pathlib import Path
import pwd
import sqlite3
import ssl
import subprocess
import urllib.request


def run(command): return subprocess.run(command, check=True, capture_output=True, text=True).stdout.strip()
def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    base = Path('/home/l4d2panel/panel')
    owner = json.loads(Path('/var/lib/l4d2panel-bootstrap/owner.json').read_text())
    config = json.loads((base / 'panel.json').read_text())
    tls = ssl.create_default_context(cafile=str(base / config['cert']))
    jar = http.cookiejar.CookieJar()
    client = urllib.request.build_opener(urllib.request.HTTPSHandler(context=tls), urllib.request.HTTPCookieProcessor(jar))
    def request(path, body=None):
        req = urllib.request.Request(f'https://localhost:{config["port"]}' + path,
            data=json.dumps(body).encode() if body is not None else None, headers={'Content-Type': 'application/json'})
        with client.open(req, timeout=10) as response: return json.load(response)
    health = request('/api/health')
    pid = int(run(['systemctl', 'show', 'l4d2panel.service', '-p', 'MainPID', '--value']))
    uid = int(Path(f'/proc/{pid}/status').read_text().split('Uid:\t')[1].split()[0])
    gid = int(Path(f'/proc/{pid}/status').read_text().split('Gid:\t')[1].split()[0])
    request('/api/login', {'username': config['bootstrap_user'], 'password': config['password']})
    me, onboarding = request('/api/me'), request('/api/onboarding')
    with sqlite3.connect(base / config['db']) as connection:
        accounts = connection.execute('select id,username,pass,role,created from accounts order by id').fetchall()
        state = connection.execute("select value from panel_state where key='onboarding'").fetchone()[0]
        integrity = connection.execute('pragma integrity_check').fetchone()[0]
        try: sentinel = connection.execute('select value from bootstrap_fixture').fetchone()[0]
        except sqlite3.OperationalError: sentinel = None
    assert uid == owner['uid'] == pwd.getpwnam('l4d2panel').pw_uid and uid != 0
    assert gid == owner['gid'] == pwd.getpwnam('l4d2panel').pw_gid
    assert health['pid'] == pid and health['ready'] is True and health['version'] == owner['version']
    assert len(accounts) == 1 and accounts[0][3] == 'owner' and integrity == 'ok'
    assert not Path(config['game_dir']).exists(), 'The install must not create a game directory'
    assert os.stat(base / 'panel.json').st_mode & 0o777 == 0o600
    assert os.stat(base / config['key']).st_mode & 0o777 == 0o600
    print(json.dumps({'version': health['version'], 'boot': health['boot'], 'pid': pid, 'uid': uid, 'gid': gid,
        'network_ports': json.loads(Path('/var/lib/l4d2panel-bootstrap/network.json').read_text()),
        'owner_count': len(accounts), 'accounts_sha256': hashlib.sha256(json.dumps(accounts).encode()).hexdigest(),
        'config_sha256': digest(base / 'panel.json'), 'cert_sha256': digest(base / config['cert']),
        'key_sha256': digest(base / config['key']), 'onboarding': json.loads(state),
        'game_dir_absent': True, 'database_integrity': integrity,
        'database_inode': (base / config['db']).stat().st_ino, 'database_sentinel': sentinel,
        'markers': {name: digest(base / name / 'bootstrap-fixture.txt') for name in ('downloads', 'pack_state', 'basic_state', 'docker')
                    if (base / name / 'bootstrap-fixture.txt').exists()},
        'docker': run(['runuser', '-u', 'l4d2panel', '--', 'docker', 'version', '--format', '{{.Server.Version}}']),
        'compose': run(['runuser', '-u', 'l4d2panel', '--', 'docker', 'compose', 'version', '--short']),
        'helpers': all(Path('/usr/local/bin/l4d2panel-' + name).is_file() for name in ('network', 'recover'))}, indent=2))


if __name__ == '__main__': main()
