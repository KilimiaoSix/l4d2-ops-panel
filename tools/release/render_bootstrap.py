#!/usr/bin/env python3
"""Render a self-contained installer with its independently trusted public key."""
import argparse
from pathlib import Path
import subprocess
from urllib.parse import urlsplit

from verify import VERSION

ROOT = Path(__file__).resolve().parent


def render(public_key, version, mirror=''):
    if not VERSION.fullmatch(version): raise ValueError('Invalid release version')
    if mirror:
        url = urlsplit(mirror)
        if (url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment
                or any(c.isspace() or c in "'\"\\`$" for c in mirror)):
            raise ValueError('Mirror must be a plain HTTPS base URL')
    key = Path(public_key).read_text(encoding='ascii').strip()
    if not key.startswith('-----BEGIN PUBLIC KEY-----') or not key.endswith('-----END PUBLIC KEY-----'):
        raise ValueError('Expected a public key, never a private key')
    result = subprocess.run(['openssl', 'rsa', '-pubin', '-in', str(public_key), '-text', '-noout'], capture_output=True, check=True)
    if b'(3072 bit)' not in result.stdout: raise ValueError('Release public key must be RSA-3072')
    canonical = subprocess.run(['openssl', 'pkey', '-pubin', '-in', str(public_key), '-pubout'], capture_output=True, check=True)
    if canonical.stdout.decode('ascii').strip() != key: raise ValueError('Expected canonical public PEM without surrounding commands')
    template = (ROOT / 'get.sh.in').read_text()
    return (template.replace('@@VERSION@@', version).replace('@@MIRROR@@', mirror.rstrip('/'))
            .replace('@@PUBLIC_KEY@@', key).replace('@@VERIFIER@@', (ROOT / 'verify.py').read_text().rstrip()))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--public-key', type=Path, required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--mirror', default='')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(render(args.public_key, args.version, args.mirror), encoding='utf-8')
    args.output.chmod(0o755)


if __name__ == '__main__': main()
