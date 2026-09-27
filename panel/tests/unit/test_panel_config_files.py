import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from l4d2panel.integrations.panel_config import ConfigConflict, ConfigError, PanelConfigFile, check_config
from l4d2panel.settings import Settings, load_settings


@pytest.fixture
def config_file(tmp_path):
    base = tmp_path / 'app'; base.mkdir()
    outside = tmp_path / 'external'; outside.mkdir()
    path = outside / 'actual.json'
    path.write_text(json.dumps({'panel_title': 'Old', 'legacy_extension': {'preserve': 7}, 'steam_api_key': 'private'}))
    return PanelConfigFile(path, base)


def test_external_exact_target_unknown_preservation_private_backup_and_noop(config_file):
    f = config_file; before = f.read(); settings = Settings(**before.raw)
    saved = f.save(before.revision, {'panel_title': '新的标题'}, settings)
    assert saved.changed == ['panel_title']
    assert f.read().raw['legacy_extension'] == {'preserve': 7}
    assert f.backup_bytes(saved.backup) == before.data
    assert not (f.base / 'panel.json').exists()
    if os.name == 'posix':
        assert f.path.stat().st_mode & 0o777 == 0o600
        assert (f.backups / saved.backup).stat().st_mode & 0o777 == 0o600
    mtime = f.path.stat().st_mtime_ns
    again = f.save(saved.snapshot.revision, {'panel_title': '新的标题'}, settings)
    assert not again.changed and again.backup is None
    assert f.path.stat().st_mtime_ns == mtime and len(list(f.backups.iterdir())) == 1
    with pytest.raises(ConfigConflict): f.save(before.revision, {'panel_title': 'stale'}, settings)
    restored = f.restore(saved.backup, saved.snapshot.revision)
    assert restored.snapshot.data == before.data


@pytest.mark.parametrize('updates', [
    {'password': 'do-not-echo-me'}, {'unknown': 1}, {'port': True}, {'port': '9000'}, {'port': 65536},
    {'session_days': 0}, {'max_upload_mb': -1}, {'bind': 'https://example.org'}, {'tls': True},
    {'display_host': 'https://example.org'}, {'display_host': 'user:secret@host'}, {'display_host': 'host/path'},
    {'steam_api_key': 'do-not-echo-me\n'}, {'panel_title': ''},
])
def test_invalid_candidate_never_changes_disk_or_echoes_secret(config_file, updates):
    f = config_file; before = f.read()
    with pytest.raises(ConfigError) as exc: f.save(before.revision, updates, Settings(**before.raw))
    assert 'do-not-echo-me' not in str(exc.value)
    assert f.read().data == before.data and not f.backups.exists()


def test_current_listener_is_not_mistaken_for_a_port_collision(config_file):
    f = config_file
    with socket.socket() as listener, socket.socket() as occupied:
        listener.bind(('127.0.0.1', 0)); listener.listen()
        occupied.bind(('127.0.0.1', 0)); occupied.listen()
        current = Settings(port=listener.getsockname()[1])
        before = f.read()
        saved = f.save(before.revision, {'port': current.port}, current)
        assert saved.snapshot.raw['port'] == current.port
        with pytest.raises(ConfigError, match='端口'):
            f.save(saved.snapshot.revision, {'port': occupied.getsockname()[1]}, current)


def test_replace_failure_keeps_original_and_recovery_respects_external_edit(config_file, monkeypatch):
    f = config_file; before = f.read(); current = Settings(**before.raw)
    with monkeypatch.context() as m:
        def fail(*a): raise OSError('simulated disk failure')
        m.setattr(os, 'replace', fail)
        with pytest.raises(OSError): f.save(before.revision, {'panel_title': 'failed'}, current)
    assert f.read().data == before.data
    assert [p.name for p in f.path.parent.glob('.actual.json.*')] == ['.actual.json.lock']
    saved = f.save(before.revision, {'panel_title': 'saved'}, current)
    f.path.write_text('{"panel_title":"external"}')
    with pytest.raises(ConfigConflict): f.restore(saved.backup, saved.snapshot.revision)
    assert f.read().raw['panel_title'] == 'external'
    with pytest.raises(ConfigError): f.backup_bytes('../actual.json')


def test_tls_certificate_pair_is_checked_as_service_user(config_file, tmp_path):
    f = config_file
    cert, key = tmp_path / 'cert.pem', tmp_path / 'key.pem'
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-subj', '/CN=localhost',
                    '-days', '1', '-keyout', str(key), '-out', str(cert)], check=True, capture_output=True)
    saved = f.save(f.read().revision, {'tls': True, 'cert': str(cert), 'key': str(key)}, Settings())
    assert saved.snapshot.raw['tls'] is True
    with pytest.raises(ConfigError, match='TLS'):
        f.save(saved.snapshot.revision, {'key': str(cert)}, Settings())
    with pytest.raises(ConfigError, match='TLS'):
        f.save(saved.snapshot.revision, {'cert': str(tmp_path / 'missing')}, Settings())


def test_check_config_is_strict_without_changing_legacy_loader(config_file):
    f = config_file
    assert load_settings(f.path).panel_title == 'Old'
    with pytest.raises(ConfigError, match='legacy_extension'): check_config(f.path, f.base)
    f.path.write_text('{"port": 8081, "game_dir":"uncreated-game"}')
    assert check_config(f.path, f.base).port == 8081
    assert not (f.base / 'uncreated-game').exists()


def test_check_config_cli_uses_environment_precedence_and_has_no_side_effects(tmp_path):
    root = Path(__file__).resolve().parents[2]
    conf = tmp_path / 'external.json'; conf.write_text('{"panel_title":"check only"}')
    env = dict(os.environ, L4D2PANEL_CONFIG=str(conf))
    result = subprocess.run([sys.executable, str(root / 'panel.py'), '--config', str(tmp_path / 'wrong'), '--check-config'],
                            env=env, capture_output=True, text=True)
    assert result.returncode == 0 and 'Configuration valid' in result.stdout
    assert list(tmp_path.iterdir()) == [conf]
    conf.write_text('{"steam_api_key":false}')
    result = subprocess.run([sys.executable, str(root / 'panel.py'), '--check-config'], env=env, capture_output=True, text=True)
    assert result.returncode != 0 and 'steam_api_key' in result.stderr
