#!/usr/bin/env python3
"""Verify an authenticated checksum list before extracting any release content.

Only stdlib and the OS OpenSSL executable are needed on the bootstrap host.
The public key is supplied by the trusted installer, never by the download mirror.
"""
import argparse
import hashlib
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tarfile

ASSET = 'l4d2-panel-linux-x86_64.tar.gz'
FILES = {ASSET, 'VERSION', 'get.sh'}
VERSION = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}')


def sha256(path):
    value = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''): value.update(chunk)
    return value.hexdigest()


def regular(path, limit):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > limit:
        raise ValueError('Expected bounded independent file: ' + path.name)


def verify(directory, public_key, expected_version):
    directory, public_key = Path(directory), Path(public_key)
    if not VERSION.fullmatch(expected_version): raise ValueError('Invalid requested release version')
    checksums, signature = directory / 'SHA256SUMS', directory / 'SHA256SUMS.sig'
    regular(checksums, 8192); regular(signature, 8192); regular(public_key, 8192)
    # Release signing is RSA-3072/SHA-256. OpenSSL can ignore bytes appended to
    # a signature, so enforce the complete fixed-size signature envelope too.
    if signature.stat().st_size != 384: raise ValueError('Invalid release signature length')
    result = subprocess.run(['openssl', 'dgst', '-sha256', '-verify', str(public_key),
        '-signature', str(signature), str(checksums)], capture_output=True)
    if result.returncode: raise ValueError('Release signature verification failed')
    rows = {}
    for line in checksums.read_text(encoding='ascii').splitlines():
        match = re.fullmatch(r'([0-9a-f]{64})  ([A-Za-z0-9._-]+)', line)
        if not match or match[2] in rows or match[2] not in FILES:
            raise ValueError('Invalid authenticated checksum list')
        rows[match[2]] = match[1]
    if rows.keys() != FILES: raise ValueError('Incomplete authenticated checksum list')
    for name, expected in rows.items():
        path = directory / name
        regular(path, 1024 ** 3 if name == ASSET else 1024 ** 2)
        if sha256(path) != expected: raise ValueError('Release checksum mismatch: ' + name)
    if (directory / 'VERSION').read_text(encoding='ascii') != expected_version + '\n':
        raise ValueError('Downloaded version does not match requested version')
    return directory / ASSET


def extract(archive_path, destination, expected_version):
    """Preflight the complete archive, then write regular files to a new directory."""
    destination = Path(destination)
    if destination.exists() or destination.is_symlink(): raise ValueError('Extraction target already exists')
    with tarfile.open(archive_path, 'r:gz') as archive:
        members, seen, total = [], set(), 0
        for member in archive:
            path = PurePosixPath(member.name)
            if (not member.isfile() or path.is_absolute() or not member.name or '\\' in member.name
                    or '..' in path.parts or '.' in member.name.split('/') or ':' in member.name
                    or str(path) != member.name or member.name in seen
                    or any(ord(c) < 32 or ord(c) == 127 for c in member.name)):
                raise ValueError('Unsafe release archive member: ' + member.name)
            total += member.size
            if member.size < 0 or total > 2 * 1024 ** 3 or len(members) >= 50000:
                raise ValueError('Release archive exceeds size/count bounds')
            seen.add(member.name); members.append(member)
        for member in members:
            if any(str(parent) in seen for parent in PurePosixPath(member.name).parents if str(parent) != '.'):
                raise ValueError('Release file is also a directory prefix')
        required = {'VERSION', 'panel/panel.py', 'panel/requirements.txt', 'panel/constraints.txt',
                    'panel/l4d2panel/static/index.html', 'panel/packs/manifest.json', 'tools/bootstrap/install.py'}
        if not required <= seen: raise ValueError('Release archive lacks required files')
        version_file = archive.extractfile('VERSION')
        if version_file.read(128) != (expected_version + '\n').encode('ascii'):
            raise ValueError('Archive version does not match authenticated release version')
        destination.mkdir(mode=0o700)
        for member in members:
            target = destination / member.name
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(member) as source, target.open('xb') as output:
                shutil.copyfileobj(source, output)
            target.chmod(0o755 if target.name in ('spcomp', 'spcomp64', 'get.sh') else 0o644)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--public-key', type=Path, required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--extract', type=Path)
    args = parser.parse_args()
    try:
        archive = verify(args.directory, args.public_key, args.version)
        if args.extract: extract(archive, args.extract, args.version)
    except (OSError, ValueError, tarfile.TarError) as error: raise SystemExit(str(error)) from None
    print('Verified release ' + args.version)


if __name__ == '__main__': main()
