"""Exercise the sampler against the real TCP RCON adapter and CSV consumer."""
import importlib.util
import json
from pathlib import Path

import pytest

from l4d2panel.integrations.rcon import RconClient
from l4d2panel.services.monitoring import Monitoring
from l4d2panel.settings import Paths, Settings
from tests.fakes.game import FakeGame, STATUS_IDLE

MODULE = Path(__file__).resolve().parents[3] / 'tools/perf-sampler.py'
spec = importlib.util.spec_from_file_location('perf_sampler', MODULE)
sampler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sampler)
STATS = 'CPU In Out Uptime Users FPS Players\n12.5 2048 4096 20 4 29.9 7'


@pytest.fixture
def game():
    server = FakeGame()
    original = server.reply
    server.stats_text = STATS
    server.reply = lambda cmd: server.stats_text if cmd == 'stats' else original(cmd)
    try:
        yield server
    finally:
        server.stop()


def client(game, password='fakerc0n'):
    return RconClient('127.0.0.1', game.port, lambda: password, timeout=1)


def test_live_protocol_csv_matches_panel_consumer(game, tmp_path):
    row = sampler.sample(client(game))
    output = tmp_path / 'perf.csv'
    sampler.append_sample(output, row)
    settings = Settings(perf_csv=str(output))
    monitoring = Monitoring(settings, Paths.from_settings(settings, tmp_path))
    assert monitoring.perf_rows() == [{'t': row[0], 'humans': 2, 'cpu': 12.5, 'out_kb': 4.0, 'fps': 29.9}]
    assert monitoring.latest_perf()['fps'] == '29.9'
    assert game.commands == ['status', 'stats']


def test_empty_server_does_not_request_stats(game):
    game.status_text = STATUS_IDLE
    assert sampler.sample(client(game)) is None
    assert game.commands == ['status']


def test_explicit_empty_probe_is_real_data(game):
    game.status_text = STATUS_IDLE
    row = sampler.sample(client(game), include_empty=True)
    assert row[1] == 0
    assert row[5] == 29.9
    assert game.commands == ['status', 'stats']


@pytest.mark.parametrize('invalid', ['unavailable', 'nan 1 2 3 4 30 7', '0 1 2 3 4 inf 7', '-1 1 2 3 4 30 7', '0 1 2 3 4 30 1.5'])
def test_invalid_stats_propagates_without_fabricating_sample(game, invalid):
    game.stats_text = invalid
    with pytest.raises(ValueError, match='stats'):
        sampler.sample(client(game))


def test_invalid_status_does_not_query_stats(game):
    game.status_text = 'Server shutting down'
    with pytest.raises(ValueError, match='status'):
        sampler.sample(client(game))
    assert game.commands == ['status']


def test_auth_failure_never_runs_commands(game):
    with pytest.raises(Exception, match='RCON'):
        sampler.sample(client(game, password='wrong'))
    assert game.commands == []


def test_rotation_bounds_history_and_keeps_latest_rows(tmp_path):
    output = tmp_path / 'perf.csv'
    row = ['12:00:00', 2, 12.5, 2048, 4096, 29.9, 7]
    for _ in range(40):
        sampler.append_sample(output, row, max_bytes=150)
    assert {p.name for p in tmp_path.iterdir()} == {'perf.csv', 'perf.csv.1', 'perf.csv.2'}
    for path in tmp_path.iterdir():
        assert path.stat().st_size <= 150
        assert path.read_text().startswith(sampler.HEADER)
        assert path.read_text().count('time,humans') == 1


def test_config_resolves_paths_and_refreshes_cfg_password(game, tmp_path, monkeypatch):
    monkeypatch.delenv('OUT', raising=False)
    cfg_dir = tmp_path / 'game/cfg'
    cfg_dir.mkdir(parents=True)
    server_cfg = cfg_dir / 'server.cfg'
    server_cfg.write_text('rcon_password "fakerc0n"\n')
    config = tmp_path / 'panel.json'
    config.write_text(json.dumps({'game_dir': 'game', 'perf_csv': 'perf.csv', 'rcon_host': '127.0.0.1', 'rcon_port': game.port}))
    connected, output = sampler.create_client(config)
    assert output == tmp_path / 'perf.csv'
    assert sampler.sample(connected)[1] == 2
    server_cfg.write_text('rcon_password "rotated"\n')
    game.password = 'rotated'
    assert sampler.sample(connected)[1] == 2
    assert game.auth_failures == 0


def test_explicit_config_password_and_output_override(game, tmp_path, monkeypatch):
    config = tmp_path / 'panel.json'
    config.write_text(json.dumps({'rcon_password': 'fakerc0n', 'rcon_host': '127.0.0.1', 'rcon_port': game.port}))
    monkeypatch.setenv('OUT', 'override.csv')
    connected, output = sampler.create_client(config)
    assert output == tmp_path / 'override.csv'
    assert sampler.sample(connected)[1] == 2


def test_missing_password_fails_before_network(game, tmp_path):
    config = tmp_path / 'panel.json'
    config.write_text(json.dumps({'game_dir': 'absent', 'rcon_host': '127.0.0.1', 'rcon_port': game.port}))
    with pytest.raises(ValueError, match='password'):
        sampler.create_client(config)
    assert game.commands == []


def test_docker_does_not_start_a_second_sampler(tmp_path):
    config = tmp_path / 'panel.json'
    config.write_text('{"server_backend": "docker"}')
    with pytest.raises(ValueError, match='Docker'):
        sampler.create_client(config)
