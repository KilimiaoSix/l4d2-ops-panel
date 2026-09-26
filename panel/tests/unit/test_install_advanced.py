import json
import os
import ssl
from pathlib import Path

import pytest

from l4d2panel import install_advanced as installer


def test_optional_field_can_be_cleared_and_enter_keeps_default(monkeypatch):
    answers = iter(['', '-'])
    monkeypatch.setattr('builtins.input', lambda _: next(answers))
    assert installer.ask('路径', '/existing/path', True) == '/existing/path'
    assert installer.ask('路径', '/existing/path', True) == ''


def test_existing_config_is_byte_preserved_without_prompt(tmp_path, monkeypatch):
    raw = b'{"port":8080,"password":"private-value","legacy_extension":42}\n'
    (tmp_path / 'panel.json').write_bytes(raw)
    monkeypatch.setattr('builtins.input', lambda _: pytest.fail('existing config must not prompt'))
    config, created = installer.configuration(tmp_path)
    assert created is False and config['legacy_extension'] == 42
    assert (tmp_path / 'panel.json').read_bytes() == raw
    assert list(tmp_path.iterdir()) == [tmp_path / 'panel.json']


def test_new_config_clears_paths_and_does_not_create_game(tmp_path, monkeypatch):
    answers = iter([str(tmp_path / 'absent-game'), '-', '127.0.0.1', '27015', '-', '-', '-', '', 'admin', '2', '48327'])
    monkeypatch.setattr('builtins.input', lambda _: next(answers))
    monkeypatch.setattr(installer.getpass, 'getpass', lambda _: 'only-in-private-config')
    config, created = installer.configuration(tmp_path)
    assert created is True and not (tmp_path / 'absent-game').exists()
    assert all(config[k] == '' for k in ('lgsm_script', 'console_log', 'perf_csv', 'depotdownloader'))
    assert (tmp_path / 'panel.json').stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize('host,expected', [('play.example:27020', 'DNS:play.example'),
    ('192.0.2.3:27020', 'IP Address:192.0.2.3'), ('[2001:db8::1]:27020', 'IP Address:2001:DB8:0:0:0:0:0:1')])
def test_certificate_has_host_only_san_and_is_not_replaced(tmp_path, host, expected):
    config = {'cert': 'cert.pem', 'key': 'key.pem', 'display_host': host, 'rcon_port': 27015}
    installer.certificate(tmp_path, config)
    before = {n: (tmp_path / n).read_bytes() for n in ('cert.pem', 'key.pem')}
    output = installer.run(['openssl', 'x509', '-in', tmp_path / 'cert.pem', '-noout', '-ext', 'subjectAltName'], capture_output=True, text=True).stdout
    assert expected in output and '27020' not in output
    installer.certificate(tmp_path, config)
    assert all((tmp_path / n).read_bytes() == data for n, data in before.items())


def test_partial_certificate_pair_is_preserved(tmp_path):
    (tmp_path / 'key.pem').write_bytes(b'preexisting key')
    with pytest.raises((OSError, ssl.SSLError)):
        installer.certificate(tmp_path, {'cert': 'cert.pem', 'key': 'key.pem', 'display_host': '', 'rcon_port': 27015})
    assert (tmp_path / 'key.pem').read_bytes() == b'preexisting key' and not (tmp_path / 'cert.pem').exists()


def test_existing_file_is_never_overwritten(tmp_path):
    target = tmp_path / 'panel.json'; target.write_bytes(b'existing')
    with pytest.raises(FileExistsError): installer.create_exclusive(target, b'new')
    assert target.read_bytes() == b'existing'
