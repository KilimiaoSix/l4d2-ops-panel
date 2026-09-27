#!/usr/bin/env python3
"""Transfer and exercise signed candidates only in owned local QEMU fixtures."""
import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess

from bootstrap_vm import running


ROOT = Path('/var/tmp/l4d2-bootstrap-vms')


def main():
    global ROOT
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('install', 'status', 'probe', 'run'))
    parser.add_argument('--codename', choices=('jammy', 'noble'), required=True)
    parser.add_argument('--version', default='2.1.0-candidate.7')
    parser.add_argument('--label', default='install')
    parser.add_argument('--command')
    parser.add_argument('--mirror')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    ROOT = args.root.resolve()
    state = json.loads((ROOT / args.codename / 'fixture.json').read_text())
    if state['purpose'] != 'l4d2-panel-bootstrap-isolated-vm' or not running(state): raise SystemExit('Owned fixture is not running')
    opts = ['-i', state['key'], '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=' + state['known_hosts']]
    ssh = ['ssh', *opts, '-p', str(state['ssh_port']), 'ubuntu@127.0.0.1']
    scp = ['scp', *opts, '-P', str(state['ssh_port'])]
    # Labels and versions become paths and must never be interpreted as shell syntax.
    import re
    if not all(re.fullmatch(r'[A-Za-z0-9._-]+', x) for x in (args.version, args.label)): raise SystemExit('Invalid fixture label/version')
    label = args.version + '-' + args.label
    directory = '/home/ubuntu/' + args.version
    log = '/home/ubuntu/' + label + '.private.log'
    result = '/home/ubuntu/' + label + '.exit'
    if args.action == 'install':
        assets = ROOT / 'releases' / args.version
        subprocess.run([*ssh, 'mkdir -p ' + directory + ' && chmod 700 ' + directory], check=True)
        files = [str(assets / name) for name in ('get.sh', 'VERSION', 'SHA256SUMS', 'SHA256SUMS.sig', 'l4d2-panel-linux-x86_64.tar.gz')]
        subprocess.run([*scp, *files, 'ubuntu@127.0.0.1:' + directory + '/'], check=True)
        command = ['sudo', 'bash', directory + '/get.sh', '--host', args.host]
        if args.mirror: command += ['--mirror', args.mirror]
        else: command += ['--offline-dir', directory]
        remote = 'umask 077; ' + shlex.join(command) + ' > ' + log + ' 2>&1; rc=$?; printf "%s\\n" "$rc" > ' + result + '; exit "$rc"'
        with (ROOT / args.codename / (label + '.ssh.log')).open('wb') as output:
            process = subprocess.Popen([*ssh, remote], stdin=subprocess.DEVNULL, stdout=output, stderr=output, start_new_session=True)
        print(json.dumps({'codename': args.codename, 'version': args.version, 'label': label, 'ssh_pid': process.pid}))
    elif args.action == 'status':
        remote = 'tail -n 12 ' + log + ' | sed "/初始密码/d"; test ! -f ' + result + ' || cat ' + result
        subprocess.run([*ssh, remote], check=True)
    elif args.action == 'probe':
        subprocess.run([*scp, str(Path(__file__).with_name('bootstrap_guest_probe.py')), 'ubuntu@127.0.0.1:/home/ubuntu/bootstrap_guest_probe.py'], check=True)
        value = subprocess.run([*ssh, 'sudo python3 /home/ubuntu/bootstrap_guest_probe.py'], capture_output=True, text=True)
        if value.returncode: raise SystemExit(value.stderr)
        data = json.loads(value.stdout)
        output = Path(__file__).resolve().parents[2] / 'docs/10-reports/2026-09-27' / (args.codename + '-' + label + '-probe.json')
        output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
        print(output); print(json.dumps(data, ensure_ascii=False, indent=2))
    elif args.action == 'run':
        if not args.command: raise SystemExit('--command required')
        subprocess.run([*ssh, args.command], check=True)


if __name__ == '__main__': main()
