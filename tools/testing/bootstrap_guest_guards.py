#!/usr/bin/env python3
"""Negative checks on a clean disposable guest, before a legitimate first install."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('assets', type=Path); args = parser.parse_args()
    if os.geteuid() != 0 or not Path('/etc/hostname').read_text().startswith('l4d2-bootstrap-'):
        raise SystemExit('Only run inside the disposable bootstrap fixture')
    record = Path('/var/lib/l4d2panel-bootstrap/owner.json')
    if record.exists(): raise SystemExit('Requires a clean fixture')
    assets = args.assets.resolve()
    command = ['bash', str(assets / 'get.sh'), '--offline-dir', str(assets), '--host', '127.0.0.1']
    checks = []
    def rejected(name, expected, cmd=command):
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        assert result.returncode != 0 and expected in result.stdout + result.stderr, (name, result.stdout[-500:], result.stderr[-500:])
        assert not record.exists() and not Path('/home/l4d2panel').exists()
        checks.append({'check': name, 'exit': result.returncode})
    rejected('nonroot rejected before any write', 'sudo bash get.sh', ['runuser', '-u', 'ubuntu', '--', *command])
    with open('/run/l4d2panel-bootstrap.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        rejected('concurrent installer refused', '另一个安装或修复')
    signature = assets / 'SHA256SUMS.sig'; before = signature.read_bytes()
    try:
        signature.write_bytes(before + b'bad')
        rejected('appended signature rejected before ownership', 'Invalid release signature length')
    finally: signature.write_bytes(before)
    version = assets / 'VERSION'; before = version.read_bytes()
    try:
        version.write_bytes(before + b'bad')
        rejected('changed authenticated file rejected before ownership', 'Release checksum mismatch')
    finally: version.write_bytes(before)
    occupied = Path('/opt/l4d2panel'); assert not occupied.exists()
    try:
        occupied.mkdir(); (occupied / 'unmanaged.txt').write_bytes(b'untouched directory fixture')
        rejected('occupied code directory preserved', 'not owned by this installer')
        assert (occupied / 'unmanaged.txt').read_bytes() == b'untouched directory fixture'
    finally:
        (occupied / 'unmanaged.txt').unlink(); occupied.rmdir()
    apt_key = Path('/etc/apt/keyrings/l4d2panel-docker.asc'); assert not apt_key.exists()
    try:
        apt_key.parent.mkdir(exist_ok=True); apt_key.write_bytes(b'unmanaged key fixture')
        rejected('unmanaged same-name apt key preserved', 'not owned by this installer')
        assert apt_key.read_bytes() == b'unmanaged key fixture'
    finally: apt_key.unlink()
    unit = Path('/etc/systemd/system/l4d2panel.service')
    foreign = b'[Unit]\nDescription=Disposable foreign-unit fixture\n[Service]\nExecStart=/bin/sleep infinity\n'
    assert not unit.exists()
    try:
        unit.write_bytes(foreign); subprocess.run(['systemctl', 'daemon-reload'], check=True)
        rejected('foreign systemd unit preserved', 'not owned by this installer')
        assert unit.read_bytes() == foreign
    finally:
        if unit.read_bytes() == foreign: unit.unlink()
        subprocess.run(['systemctl', 'daemon-reload'], check=True)
    subprocess.run(['useradd', '--system', '--no-create-home', '--comment', 'bootstrap-guard-fixture', 'l4d2panel'], check=True)
    try: rejected('foreign username preserved', 'unmanaged installation')
    finally:
        assert pwd.getpwnam('l4d2panel').pw_gecos == 'bootstrap-guard-fixture'
        subprocess.run(['userdel', 'l4d2panel'], check=True)
    print(json.dumps({'checks': checks, 'ownership_absent': not record.exists()}, indent=2))


if __name__ == '__main__': main()
