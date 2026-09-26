import io
from pathlib import Path
import subprocess
import sys
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tools/release'))
from verify import ASSET, verify, extract
from sign import seal
from render_bootstrap import render


@pytest.fixture(scope='module')
def keys(tmp_path_factory):
    root = tmp_path_factory.mktemp('signing')
    private, public = root / 'private.pem', root / 'public.pem'
    subprocess.run(['openssl', 'genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:3072', '-out', str(private)], check=True, capture_output=True)
    private.chmod(0o600)
    subprocess.run(['openssl', 'pkey', '-in', str(private), '-pubout', '-out', str(public)], check=True, capture_output=True)
    return private, public


def archive(path, extra=None):
    rows = {'VERSION': b'2.1.0\n', 'panel/panel.py': b'pass', 'panel/requirements.txt': b'',
            'panel/constraints.txt': b'', 'panel/l4d2panel/static/index.html': b'html',
            'panel/packs/manifest.json': b'{}', 'tools/bootstrap/install.py': b'pass'}
    with tarfile.open(path, 'w:gz') as tar:
        for name, value in rows.items():
            info = tarfile.TarInfo(name); info.size = len(value); tar.addfile(info, io.BytesIO(value))
        if extra: tar.addfile(extra, io.BytesIO(b''))


@pytest.fixture
def signed(tmp_path, keys):
    archive(tmp_path / ASSET)
    (tmp_path / 'get.sh').write_text('#!/bin/bash\nexit 0\n')
    seal(tmp_path, *keys, '2.1.0')
    return tmp_path


def test_signed_release_extracts_only_after_both_checks(signed, keys):
    source = verify(signed, keys[1], '2.1.0')
    destination = signed / 'stage'; extract(source, destination, '2.1.0')
    assert (destination / 'VERSION').read_text() == '2.1.0\n'
    with pytest.raises(ValueError, match='already exists'): extract(source, destination, '2.1.0')


@pytest.mark.parametrize('name', [ASSET, 'VERSION', 'get.sh', 'SHA256SUMS', 'SHA256SUMS.sig'])
def test_tampering_cannot_pass(signed, keys, name):
    with (signed / name).open('ab') as output: output.write(b'changed')
    with pytest.raises(ValueError): verify(signed, keys[1], '2.1.0')


def test_requested_version_and_signing_key_are_bound(signed, keys, tmp_path):
    with pytest.raises(ValueError, match='requested version'): verify(signed, keys[1], '2.1.1')
    wrong = tmp_path / 'other.pem'; wrong.write_bytes(b'not the public key')
    with pytest.raises(ValueError, match='match trusted'): seal(signed, keys[0], wrong, '2.1.0')
    with pytest.raises(ValueError, match='signature'): verify(signed, wrong, '2.1.0')


@pytest.mark.parametrize('name,kind', [('../escape', tarfile.REGTYPE), ('/absolute', tarfile.REGTYPE),
    ('panel/link', tarfile.SYMTYPE), ('panel/hardlink', tarfile.LNKTYPE), ('panel/device', tarfile.CHRTYPE),
    ('panel/../escape', tarfile.REGTYPE), ('panel\\escape', tarfile.REGTYPE), ('VERSION', tarfile.REGTYPE),
    ('panel', tarfile.REGTYPE), ('panel/./escape', tarfile.REGTYPE)])
def test_even_signed_archive_rejects_unsafe_members(tmp_path, name, kind):
    path = tmp_path / ASSET; member = tarfile.TarInfo(name); member.type = kind; member.linkname = '/etc/passwd'
    archive(path, member)
    with pytest.raises(ValueError): extract(path, tmp_path / 'stage', '2.1.0')
    assert not (tmp_path / 'stage').exists()


def test_rendered_installer_has_trusted_key_and_valid_shell(tmp_path, keys):
    path = tmp_path / 'get.sh'
    script = render(keys[1], '2.1.0', 'https://mirror.example/releases')
    path.write_text(script)
    subprocess.run(['bash', '-n', str(path)], check=True)
    result = subprocess.run(['bash', str(path), '--help'], check=True, capture_output=True, text=True)
    assert '--repair-docker' in result.stdout and '@@' not in script
    assert 'BEGIN PRIVATE KEY' not in script and 'BEGIN PUBLIC KEY' in script
    assert 'RELEASE_VERSION=' in script  # /etc/os-release defines VERSION itself.
    with pytest.raises(ValueError): render(keys[0], '2.1.0')
    for mirror in ("https://a/'$(id)", 'http://mirror.example', 'https://u:p@mirror.example', 'https://a/?token=x'):
        with pytest.raises(ValueError): render(keys[1], '2.1.0', mirror)
