#!/usr/bin/env python3
"""Disposable local QEMU/KVM fixtures for complete Ubuntu/systemd bootstrap tests.

Uses previously downloaded, SHA-256 checked official cloud images. Guests have
independent disks and localhost-only forwarded SSH/HTTPS, no shared host mounts.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import time
import uuid


def run(args, **kwargs): return subprocess.run([str(x) for x in args], check=True, **kwargs)
def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); return sock.getsockname()[1]


def running(state):
    try:
        cmd = Path(f'/proc/{state["pid"]}/cmdline').read_bytes().split(b'\0')
        return b'qemu-system-x86_64' in cmd[0] and any(str(state['disk']).encode() in x for x in cmd)
    except (OSError, KeyError, IndexError): return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('start', 'status', 'stop'))
    parser.add_argument('--codename', choices=('jammy', 'noble'), required=True)
    parser.add_argument('--root', type=Path, default=Path('/var/tmp/l4d2-bootstrap-vms'))
    args = parser.parse_args()
    root = args.root.resolve()
    if not root.is_dir() or root.is_symlink(): raise SystemExit('Create a private fixture root and download verified images first')
    directory = root / args.codename
    state_file = directory / 'fixture.json'
    if state_file.exists():
        state = json.loads(state_file.read_text())
        if args.action == 'stop':
            if running(state): os.kill(state['pid'], signal.SIGTERM)
            print('Stopped only the owned fixture process; disks retained'); return
        if running(state): print(json.dumps(state, indent=2)); return
        if args.action == 'status': print('Fixture is stopped'); return
    elif args.action != 'start': raise SystemExit('Fixture does not exist')
    image = root / f'{args.codename}-server-cloudimg-amd64.img'
    metadata = json.loads((root / f'{args.codename}-image.json').read_text())
    digest = hashlib.sha256()
    with image.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''): digest.update(chunk)
    if digest.hexdigest() != metadata['sha256']: raise SystemExit('Cloud image changed since verification')
    directory.mkdir(mode=0o700, exist_ok=True)
    key = root / 'fixture-ssh'
    with (root / 'ssh-key.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not key.exists(): run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', key])
    disk = directory / 'disk.qcow2'
    if not disk.exists():
        run(['qemu-img', 'create', '-q', '-f', 'qcow2', '-F', 'qcow2', '-b', image, disk, '10G'])
        user = {'users': [{'name': 'ubuntu', 'groups': ['adm', 'sudo'], 'shell': '/bin/bash', 'lock_passwd': True,
            'sudo': ['ALL=(ALL) NOPASSWD:ALL'], 'ssh_authorized_keys': [key.with_suffix('.pub').read_text().strip()]}],
            'ssh_pwauth': False, 'package_update': False, 'package_upgrade': False}
        (directory / 'user-data').write_text('#cloud-config\n' + json.dumps(user, indent=2) + '\n')
        (directory / 'meta-data').write_text(json.dumps({'instance-id': 'l4d2-bootstrap-' + uuid.uuid4().hex,
                                                       'local-hostname': 'l4d2-bootstrap-' + args.codename}))
        run(['cloud-localds', directory / 'seed.img', directory / 'user-data', directory / 'meta-data'])
        shutil.copy('/usr/share/OVMF/OVMF_VARS.fd', directory / 'efi-vars.fd')
    ssh_port, https_port = port(), port()
    command = ['qemu-system-x86_64', '-accel', 'kvm', '-cpu', 'host', '-smp', '2', '-m', '1536',
        '-display', 'none', '-monitor', 'none', '-serial', 'file:' + str(directory / 'serial.log'),
        '-drive', 'if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE.fd',
        '-drive', 'if=pflash,format=raw,file=' + str(directory / 'efi-vars.fd'),
        '-drive', 'if=virtio,format=qcow2,file=' + str(disk),
        '-drive', 'if=virtio,format=raw,file=' + str(directory / 'seed.img'),
        '-netdev', f'user,id=net0,hostfwd=tcp:127.0.0.1:{ssh_port}-:22,hostfwd=tcp:127.0.0.1:{https_port}-:8443',
        '-device', 'virtio-net-pci,netdev=net0']
    with (directory / 'qemu.log').open('ab') as log:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    state = {'purpose': 'l4d2-panel-bootstrap-isolated-vm', 'codename': args.codename, 'pid': process.pid,
             'disk': str(disk), 'ssh_port': ssh_port, 'https_port': https_port, 'key': str(key),
             'known_hosts': str(directory / 'known_hosts'), 'image': metadata}
    state_file.write_text(json.dumps(state, indent=2) + '\n')
    deadline = time.monotonic() + 180
    ssh = ['ssh', '-i', key, '-p', str(ssh_port), '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=accept-new',
           '-o', 'ConnectTimeout=3', '-o', 'UserKnownHostsFile=' + state['known_hosts'], 'ubuntu@127.0.0.1']
    while time.monotonic() < deadline:
        if process.poll() is not None: raise SystemExit('QEMU failed; inspect ' + str(directory / 'qemu.log'))
        try: check = subprocess.run([str(x) for x in [*ssh, 'cloud-init status --wait']], capture_output=True, timeout=30)
        except subprocess.TimeoutExpired: continue
        if check.returncode == 0: print(json.dumps(state, indent=2), flush=True); return
        time.sleep(2)
    raise SystemExit('Guest readiness timed out; fixture retained for inspection')


if __name__ == '__main__': main()
