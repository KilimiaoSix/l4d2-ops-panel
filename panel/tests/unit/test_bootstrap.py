import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('bootstrap_install', ROOT / 'tools/bootstrap/install.py')
bootstrap = importlib.util.module_from_spec(spec); spec.loader.exec_module(bootstrap)


@pytest.mark.parametrize('value,expected', [('1.2.3.4', '1.2.3.4'), ('[2001:db8::1]', '2001:db8::1'),
    ('Play.Example', 'play.example'), ('游戏.example', 'xn--unup4y.example')])
def test_certificate_host(value, expected): assert bootstrap.host_name(value) == expected


@pytest.mark.parametrize('value', ['', 'http://host', 'host:8443', 'bad;quit', 'a/b', 'a\nb', 'a..b', '-a.example',
    'fe80::1%eth0;quit', '[fe80::1%eth0]', '999.1.2.3'])
def test_certificate_host_rejects_commands_and_urls(value):
    with pytest.raises(ValueError): bootstrap.host_name(value)


def test_atomic_write_refuses_link_and_preserves_private_mode(tmp_path):
    target = tmp_path / 'panel.json'; bootstrap.atomic(target, b'secret')
    assert target.stat().st_mode & 0o777 == 0o600
    alias = tmp_path / 'alias'; alias.symlink_to(target)
    with pytest.raises(ValueError): bootstrap.atomic(alias, b'replaced')
    assert target.read_bytes() == b'secret'


def test_public_apt_key_mode_survives_private_bootstrap_umask(tmp_path):
    previous = os.umask(0o077)
    try: bootstrap.atomic(tmp_path / 'public.asc', b'public key', 0o644)
    finally: os.umask(previous)
    assert (tmp_path / 'public.asc').stat().st_mode & 0o777 == 0o644


@pytest.fixture
def layout(tmp_path, monkeypatch):
    state, base = tmp_path / 'state', tmp_path / 'panel'; state.mkdir(); base.mkdir()
    monkeypatch.setattr(bootstrap, 'BASE', base)
    monkeypatch.setattr(bootstrap, 'RECORD', state / 'owner.json')
    monkeypatch.setattr(bootstrap, 'UNIT', tmp_path / 'service')
    calls = []
    monkeypatch.setattr(bootstrap, 'run', lambda command, **kw: calls.append(command))
    return base, calls


def pending(layout):
    base, calls = layout
    old_unit, new_unit = b'old service', b'new service'
    old = {'unit_sha256': hashlib.sha256(old_unit).hexdigest(), 'uid': os.getuid(), 'gid': os.getgid(), 'version': 'old'}
    data = {**old, 'pending': {'record': old, 'unit': base64.b64encode(old_unit).decode(),
        'launcher': base64.b64encode(b'old launcher').decode(), 'next_unit_sha256': hashlib.sha256(new_unit).hexdigest()}}
    return data, new_unit


def test_interrupted_update_restores_code_entry_and_not_data(layout):
    base, calls = layout; data, new_unit = pending(layout)
    bootstrap.UNIT.write_bytes(new_unit)
    (base / 'panel.py').write_bytes(b'new launcher')
    for name in ('panel.db', 'panel.db-wal', 'panel.json', 'cert.pem', 'key.pem'):
        (base / name).write_bytes(b'mutable data')
    restored = bootstrap.recover_pending(data)
    assert restored['version'] == 'old' and 'pending' not in restored
    assert bootstrap.UNIT.read_bytes() == b'old service' and (base / 'panel.py').read_bytes() == b'old launcher'
    assert all((base / name).read_bytes() == b'mutable data' for name in ('panel.db', 'panel.db-wal', 'panel.json', 'cert.pem', 'key.pem'))
    assert calls == [['systemctl', 'stop', 'l4d2panel.service'], ['systemctl', 'daemon-reload'], ['systemctl', 'start', 'l4d2panel.service']]


def test_interrupted_update_will_not_overwrite_external_unit_edit(layout):
    data, _ = pending(layout); bootstrap.UNIT.write_bytes(b'external edit')
    with pytest.raises(ValueError, match='external'): bootstrap.recover_pending(data)
    assert bootstrap.UNIT.read_bytes() == b'external edit' and layout[1] == []


def test_first_install_failure_stays_retryable_without_success_marker(layout):
    data, new_unit = pending(layout)
    data['version'] = None; data['pending']['record']['unit_sha256'] = None; data['pending']['unit'] = None
    bootstrap.UNIT.write_bytes(new_unit)
    result = bootstrap.recover_pending(data)
    assert result['version'] is None and 'pending' not in result
    assert result['unit_sha256'] == hashlib.sha256(new_unit).hexdigest()


def test_service_uses_stable_base_and_versioned_runtime():
    text = bootstrap.unit_text(Path('/opt/l4d2panel/2.1.0-example'))
    assert 'User=l4d2panel' in text and 'RestartPreventExitStatus=78' in text
    assert 'PYTHONPATH=/opt/l4d2panel/2.1.0-example/panel' in text
    assert '/home/l4d2panel/panel/panel.py --config /home/l4d2panel/panel/panel.json' in text


def test_root_private_staging_code_is_readable_after_copy(tmp_path):
    source, release = tmp_path / 'stage', tmp_path / 'release'
    (source / 'panel' / 'l4d2panel').mkdir(parents=True, mode=0o700)
    (source / 'panel').chmod(0o700)
    (source / 'panel/l4d2panel/main.py').write_text('code')
    release.mkdir()
    previous = os.umask(0o077)
    try: bootstrap.copy_application(source, release)
    finally: os.umask(previous)
    assert all(path.stat().st_mode & 0o777 == 0o755 for path in (release / 'panel', release / 'panel/l4d2panel'))
