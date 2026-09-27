#!/usr/bin/env python3
"""Exercise root helpers in an owned disposable VM, never against production."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main():
    if os.geteuid() != 0 or not Path('/etc/hostname').read_text().startswith('l4d2-bootstrap-'):
        raise SystemExit('Disposable bootstrap fixture required')
    sys.path.insert(0, '/usr/local/lib/l4d2panel-bootstrap')
    from install import BASE, RECORD, UNIT_NAME, as_user, health, run
    record = json.loads(RECORD.read_text()); config_path = BASE / 'panel.json'
    before = config_path.read_bytes(); config = json.loads(before)
    checks = []
    network = ['/usr/local/bin/l4d2panel-network']
    run([*network, '--game-port', '27025'], capture=True)
    rules = run(['iptables', '-S', 'DOCKER-USER'], capture=True).stdout
    assert '--ctorigdstport 27025' in rules and 'l4d2panel-managed' in rules
    run(network, capture=True)
    assert run(['iptables', '-S', 'DOCKER-USER'], capture=True).stdout == rules
    checks.append('repeated network helper does not duplicate Docker rules')
    saved = (RECORD.parent / 'network.json').read_bytes()
    invalid = run([*network, '--game-port', '27025;quit'], capture=True, check=False)
    assert invalid.returncode != 0 and (RECORD.parent / 'network.json').read_bytes() == saved
    checks.append('invalid port rejected before changing saved network configuration')
    started = run(['systemctl', 'show', 'l4d2panel-network.service', '-p', 'ExecMainStartTimestampMonotonic', '--value'], capture=True).stdout
    run(['systemctl', 'restart', 'docker'])
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        current = run(['systemctl', 'show', 'l4d2panel-network.service', '-p', 'ExecMainStartTimestampMonotonic', '--value'], capture=True).stdout
        if current != started and run(['systemctl', 'is-active', 'l4d2panel-network.service'], capture=True, check=False).returncode == 0: break
        time.sleep(0.25)
    else: raise AssertionError('Network helper did not run after Docker restart')
    assert '--ctorigdstport 27025' in run(['iptables', '-S', 'DOCKER-USER'], capture=True).stdout
    checks.append('Docker restart reapplies persisted tagged rules')
    run(['ufw', 'allow', '22/tcp', 'comment', 'fixture-ssh'], capture=True)
    run(['ufw', '--force', 'enable'], capture=True)
    run(network, capture=True)
    ufw = run(['ufw', 'status'], capture=True, env=dict(os.environ, LC_ALL='C')).stdout
    assert all(value in ufw for value in ('22/tcp', '8443/tcp', '27025/tcp', '27025/udp'))
    checks.append('active UFW keeps SSH and adds only selected panel/game protocols')
    old_boot = health(config)['boot']
    run(['systemctl', 'stop', UNIT_NAME])
    release = Path(record['release'])
    program = ('from pathlib import Path; from l4d2panel.integrations.panel_config import PanelConfigFile; '
        'from l4d2panel.services.panel_restart import RestartJournal; from l4d2panel.settings import load_settings; '
        f'p=Path({str(config_path)!r}); f=PanelConfigFile(p,p.parent); s=load_settings(p); '
        'f.save(f.read().revision,{"session_days":s.session_days+1},s,before_commit=RestartJournal(f).prepare)')
    as_user([release / 'venv/bin/python', '-c', program], env={'PYTHONPATH': str(release / 'panel')}, capture=True)
    assert config_path.read_bytes() != before
    run(['/usr/local/bin/l4d2panel-recover'], capture=True)
    assert config_path.read_bytes() == before
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            value = health(config)
            if value['ready'] and value['boot'] != old_boot: break
        except (OSError, ValueError): pass
        time.sleep(0.25)
    else: raise AssertionError('Recovered panel did not start')
    assert config_path.stat().st_mode & 0o777 == 0o600
    assert all(p.stat().st_uid == record['uid'] for p in (BASE / 'config_backups/panel').glob('*.json'))
    checks.append('root recovery restored exact configuration as service user and started a new process')
    print(json.dumps({'checks': checks, 'version': value['version'], 'config_sha256': hashlib.sha256(before).hexdigest()}, indent=2))


if __name__ == '__main__': main()
