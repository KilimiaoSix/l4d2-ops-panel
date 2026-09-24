import json
import subprocess
import threading
import time
from unittest.mock import Mock

import pytest

from l4d2panel.integrations.docker import DockerServer
from l4d2panel.services.features import FeatureDetector
from l4d2panel.services.monitoring import Monitoring
from l4d2panel.services.server_control import ServerControl
from l4d2panel.settings import Paths, Settings


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    settings = Settings(install_dir=str(tmp_path), game_dir=str(tmp_path / 'game'), docker_project='test-game', server_backend='docker')
    paths = Paths.from_settings(settings, tmp_path)
    (tmp_path / 'docker-compose.yaml').write_text(json.dumps({'services': {'l4d2': {'volumes': [
        {'type': 'bind', 'source': str(paths.game), 'target': '/l4d2/left4dead2'}]}}}))
    monkeypatch.setattr('l4d2panel.integrations.docker.shutil.which', lambda _: '/usr/bin/docker')
    return settings, paths, DockerServer(settings, paths)


def container(paths, running=True, project='test-game'):
    return {'Id': 'abc123', 'Config': {'Labels': {'com.docker.compose.project': project,
            'com.docker.compose.service': 'l4d2', 'com.docker.compose.project.working_dir': str(paths.install_dir)}},
            'State': {'Running': running, 'Status': 'running' if running else 'exited'},
            'Mounts': [{'Type': 'bind', 'Source': str(paths.game), 'Destination': '/l4d2/left4dead2'}]}


def command_mock(monkeypatch, outputs):
    calls = []
    def run(args, **kw):
        calls.append(args)
        result = outputs.pop(0)
        if isinstance(result, Exception): raise result
        return subprocess.CompletedProcess(args, *result)
    monkeypatch.setattr('l4d2panel.integrations.docker.subprocess.run', run)
    return calls


@pytest.mark.parametrize('action,suffix', [('start', ['up', '-d', '--no-deps', 'l4d2']), ('stop', ['stop', 'l4d2']), ('restart', ['restart', 'l4d2'])])
def test_control_targets_only_selected_game(runtime, monkeypatch, action, suffix):
    settings, paths, docker = runtime
    calls = command_mock(monkeypatch, [(0, 'abc123\n', ''), (0, json.dumps([container(paths)]), ''), (0, '', 'Container started')])
    assert docker.run(action) == 'Container started'
    if action == 'start':
        assert calls[-1] == ['docker', 'compose', '-p', 'test-game', '-f', str(paths.install_dir / 'docker-compose.yaml'), *suffix]
    else:
        assert calls[-1] == ['docker', action, 'abc123']


def test_monitor_only_reads_and_reports_stopped_container(runtime, monkeypatch):
    _, paths, docker = runtime
    calls = command_mock(monkeypatch, [(0, 'abc123\n', ''), (0, json.dumps([container(paths, False)]), '')])
    assert 'exited' in docker.run('monitor')
    assert all('start' not in c and 'up' not in c and 'restart' not in c for c in calls)


def test_running_and_logs_use_exact_container(runtime, monkeypatch):
    _, paths, docker = runtime
    calls = command_mock(monkeypatch, [(0, 'abc123\n', ''), (0, json.dumps([container(paths)]), ''),
                                      (0, 'abc123\n', ''), (0, json.dumps([container(paths)]), ''),
                                      (0, '\x1b[32mMap loaded\x1b[0m\n', 'warning\n')])
    assert docker.running() is True
    assert docker.console(10) == ['Map loaded', 'warning']
    assert calls[-1] == ['docker', 'logs', '--tail', '10', 'abc123']


def test_wrong_project_container_is_rejected(runtime, monkeypatch):
    _, paths, docker = runtime
    command_mock(monkeypatch, [(0, 'abc123\n', ''), (0, json.dumps([container(paths, project='other')]), '')])
    with pytest.raises(RuntimeError, match='归属'): docker.running()


@pytest.mark.parametrize('result,match', [((1, '', 'permission denied'), 'permission denied'),
                                        (subprocess.TimeoutExpired('docker', 20), '超时'),
                                        (FileNotFoundError('docker'), 'Docker')])
def test_errors_are_not_reported_as_success(runtime, monkeypatch, result, match):
    docker = runtime[2]
    command_mock(monkeypatch, [(0, '', ''), result])
    with pytest.raises(RuntimeError, match=match): docker.run('start')


def test_missing_container_is_offline(runtime, monkeypatch):
    command_mock(monkeypatch, [(0, '', '')])
    assert runtime[2].running() is False


def test_control_shares_install_lock_and_recovers_on_failure(runtime):
    settings, _, _ = runtime
    lock = threading.Lock()
    docker = Mock(); docker.run.side_effect = RuntimeError('denied')
    lgsm, audit = Mock(), Mock()
    service = ServerControl(lgsm, audit, docker=docker, settings=settings, operation_lock=lock)
    lock.acquire()
    assert service.run('restart', 'owner') is False
    lock.release()
    assert service.run('restart', 'owner') is True
    for _ in range(100):
        if service.state['running'] is None: break
        time.sleep(.01)
    assert 'denied' in service.state['last'] and not lock.locked()
    lgsm.run.assert_not_called()


def test_docker_monitoring_collects_real_stats_and_throttles(runtime, monkeypatch):
    settings, paths, _ = runtime
    docker = Mock(); docker.console.return_value = ['container log']
    rcon = Mock(); rcon.run.side_effect = ['CPU In Out Uptime Users FPS Players\n20.5 500 8192 30 2 59.9 7\n', 'players : 2 humans, 5 bots (8 max)']
    monitor = Monitoring(settings, paths, docker=docker, rcon=rcon)
    assert monitor.console() == ['container log']
    row = monitor.perf_rows()[0]
    assert {k: row[k] for k in ('humans', 'cpu', 'out_kb', 'fps')} == dict(humans=2, cpu=20.5, out_kb=8.0, fps=59.9)
    assert monitor.latest_perf()['fps'] == '59.9'
    assert len(monitor.perf_lines()) == 2
    assert rcon.run.call_count == 2


def test_unavailable_stats_does_not_invent_samples(runtime):
    settings, paths, _ = runtime
    rcon = Mock(); rcon.run.side_effect = OSError('offline')
    monitor = Monitoring(settings, paths, docker=Mock(), rcon=rcon)
    assert monitor.perf_rows() == [] and monitor.latest_perf() is None


def test_docker_features_do_not_require_host_log_files(runtime):
    settings, _, _ = runtime
    server = Mock(); server.available.return_value = True
    lgsm = Mock(); lgsm.available.return_value = False
    features = FeatureDetector(settings, Mock(), lgsm, server=server).get(False)
    assert features['docker'] and features['server_control'] and features['console_log'] and features['perf']
    assert features['lgsm'] is False


@pytest.mark.parametrize('action', ['start', 'stop', 'restart'])
def test_mutation_rejects_other_installation_before_modifying(runtime, monkeypatch, action):
    _, paths, docker = runtime
    other = container(paths)
    other['Config']['Labels']['com.docker.compose.project.working_dir'] = '/another/install'
    calls = command_mock(monkeypatch, [(0, 'abc123\n', ''), (0, json.dumps([other]), '')])
    with pytest.raises(RuntimeError, match='归属'): docker.run(action)
    assert len(calls) == 2


def test_samples_expire_throttle_and_keep_last_120(runtime, monkeypatch):
    settings, paths, _ = runtime
    now = [100]
    monkeypatch.setattr('l4d2panel.services.monitoring.time.monotonic', lambda: now[0])
    rcon = Mock()
    rcon.run.side_effect = lambda command: '1 2 3 4 5 60 7' if command == 'stats' else 'players : 2 humans, 5 bots (8 max)'
    monitor = Monitoring(settings, paths, docker=Mock(), rcon=rcon)
    for _ in range(125):
        monitor.perf_rows()
        now[0] += 15
    assert len(monitor.perf_rows(200)) == 120
    assert rcon.run.call_count == 252
    now[0] += 14
    monitor.latest_perf()
    assert rcon.run.call_count == 252


@pytest.mark.parametrize('response', ['unknown command', 'nan 1 2 3 4 5 6', '-1 1 2 3 4 5 6', '1 2 3'])
def test_malformed_stats_cannot_create_performance_sample(runtime, response):
    settings, paths, _ = runtime
    rcon = Mock(); rcon.run.return_value = response
    assert Monitoring(settings, paths, docker=Mock(), rcon=rcon).perf_rows() == []


def test_status_docker_inspection_overrides_unrelated_host_process(runtime):
    from l4d2panel.services.status import StatusService
    settings, _, _ = runtime
    a2s = Mock(); a2s.query.return_value = {'online': False}
    game = Mock(); game.flags.return_value = {}
    features = Mock(); features.get.return_value = {}
    server = Mock(); server.running.return_value = False; server.state = {}
    process_check = Mock(return_value=True)
    status = StatusService(settings, a2s, game, features, Mock(), server, process_check)
    result = status.build({'username': 'admin', 'role': 'owner'})
    assert result['srcds'] is False and result['backend'] == 'docker'
    process_check.assert_not_called()
    game.players.assert_not_called()
    server.running.side_effect = RuntimeError('daemon unavailable')
    assert status.build({'username': 'admin', 'role': 'owner'})['server_error'] == 'daemon unavailable'


def test_working_directory_symlink_refers_to_same_install(runtime, monkeypatch, tmp_path):
    _, paths, docker = runtime
    alias = tmp_path / 'alias'
    alias.symlink_to(paths.install_dir, target_is_directory=True)
    info = container(paths)
    info['Config']['Labels']['com.docker.compose.project.working_dir'] = str(alias)
    command_mock(monkeypatch, [(0, 'abc123\n', ''), (0, json.dumps([info]), '')])
    assert docker.running() is True


def test_console_daemon_failure_has_actionable_api_error(runtime):
    from l4d2panel.errors import ApiError
    settings, paths, _ = runtime
    docker = Mock(); docker.console.side_effect = RuntimeError('Docker 操作失败: daemon offline')
    monitor = Monitoring(settings, paths, docker=docker)
    with pytest.raises(ApiError, match='daemon offline'):
        monitor.console()


@pytest.mark.parametrize('action', ['start', 'stop', 'restart', 'monitor'])
def test_runtime_rejects_container_with_other_game_mount(runtime, monkeypatch, action):
    _, paths, docker = runtime
    info = container(paths)
    info['Mounts'][0]['Source'] = str(paths.base / 'other-game')
    calls = command_mock(monkeypatch, [(0, 'abc123\n', ''), (0, json.dumps([info]), '')])
    with pytest.raises(RuntimeError, match='归属'): docker.run(action)
    assert len(calls) == 2


@pytest.mark.parametrize('value', ['not-json', {'services': {'l4d2': {'volumes': [
    {'type': 'bind', 'source': '/other-game', 'target': '/l4d2/left4dead2'}]}}}])
def test_start_rejects_replaced_compose_before_any_container_change(runtime, monkeypatch, value):
    _, paths, docker = runtime
    docker.compose_file.write_text(value if isinstance(value, str) else json.dumps(value))
    calls = command_mock(monkeypatch, [])
    with pytest.raises(RuntimeError, match='Compose'): docker.run('start')
    assert calls == []


def test_stop_uses_actual_owned_container_even_if_compose_broken(runtime, monkeypatch):
    _, paths, docker = runtime
    docker.compose_file.write_text('broken compose')
    calls = command_mock(monkeypatch, [(0, 'abc123\n', ''), (0, json.dumps([container(paths)]), ''), (0, 'abc123', '')])
    assert docker.run('stop') == 'abc123'
    assert calls[0] == ['docker', 'ps', '-a', '-q', '--filter', 'label=com.docker.compose.project=test-game',
                        '--filter', 'label=com.docker.compose.service=l4d2', '--filter', 'label=com.docker.compose.oneoff=False']
    assert calls[-1] == ['docker', 'stop', 'abc123']


def test_start_cannot_shadow_owned_bind_with_shorthand_volume(runtime, monkeypatch):
    _, paths, docker = runtime
    config = json.loads(docker.compose_file.read_text())
    config['services']['l4d2']['volumes'].append('/other-game:/l4d2/left4dead2')
    docker.compose_file.write_text(json.dumps(config))
    calls = command_mock(monkeypatch, [])
    with pytest.raises(RuntimeError, match='Compose'): docker.run('start')
    assert calls == []
