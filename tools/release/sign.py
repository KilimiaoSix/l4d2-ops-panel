#!/usr/bin/env python3
"""Seal the final tar, rendered installer and version using a separately held key."""
import argparse
from pathlib import Path
import subprocess
import tempfile

from verify import ASSET, FILES, VERSION, sha256, verify


def seal(directory, private_key, public_key, version):
    directory, private_key, public_key = Path(directory), Path(private_key), Path(public_key)
    if not VERSION.fullmatch(version): raise ValueError('Invalid version')
    # Key mismatch must fail before producing any signed release metadata.
    result = subprocess.run(['openssl', 'pkey', '-in', str(private_key), '-pubout'], capture_output=True, check=True)
    if result.stdout.strip() != public_key.read_bytes().strip(): raise ValueError('Signing key does not match trusted public key')
    if not (directory / ASSET).is_file() or not (directory / 'get.sh').is_file(): raise ValueError('Build tar and installer first')
    (directory / 'VERSION').write_text(version + '\n', encoding='ascii')
    data = ''.join(sha256(directory / name) + '  ' + name + '\n' for name in sorted(FILES))
    (directory / 'SHA256SUMS').write_text(data, encoding='ascii')
    with tempfile.NamedTemporaryFile(dir=directory, prefix='.signature-') as signature:
        subprocess.run(['openssl', 'dgst', '-sha256', '-sign', str(private_key), '-out', signature.name,
                        str(directory / 'SHA256SUMS')], check=True, capture_output=True)
        (directory / 'SHA256SUMS.sig').write_bytes(Path(signature.name).read_bytes())
    verify(directory, public_key, version)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--private-key', type=Path, required=True)
    parser.add_argument('--public-key', type=Path, required=True)
    parser.add_argument('--version', required=True)
    args = parser.parse_args()
    seal(args.directory, args.private_key, args.public_key, args.version)


if __name__ == '__main__': main()
