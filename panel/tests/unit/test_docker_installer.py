import json
import os
import sys
import threading
import time

import pytest

from l4d2panel.integrations.game_installer import DockerGameInstaller, InstallOptions, render_compose
from l4d2panel.jobs import Job
from l4d2panel.game_modes import MODES


def game_files(root):
    (root / 'bin').mkdir(parents=True)
    (root / 'steam.inf').write_text('PatchVersion=1')
    (root / 'gameinfo.txt').write_text('gameinfo')
    (root / 'bin/server_srv.so').write_text('server')


def test_compose_launches_game_without_overwriting_cfg(tmp_path):
    config = json.loads(render_compose(InstallOptions(rcon_password='do-not-export', tick=60), tmp_path))
    assert set(config['services']) == {'l4d2'}
    game = config['services']['l4d2']
    assert game['platform'] == 'linux/amd64'
    assert game['user'] == f'{os.getuid()}:{os.getgid()}'
    assert game['entrypoint'] == ['/bin/sh', '/l4d2/left4dead2/.l4d2-panel-start.sh']
    assert '/l4d2/start.sh' not in json.dumps(config)
    assert 'do-not-export' not in json.dumps(config)
    assert 'container_name' not in game
    assert '+exec' in game['command'] and '+mp_gamemode' not in game['command']


def test_refuses_existing_game_before_docker_or_compose_mutation(tmp_path):
    game = tmp_path / 'game'
    game_files(game)
    installer = DockerGameInstaller(tmp_path / 'install', game, docker_bin='docker')
    with pytest.raises(RuntimeError, match='非空'):
        installer.run(InstallOptions(), Job('l4d2', 'install'))
    assert not installer.compose_file.exists()
    assert (game / 'steam.inf').read_text() == 'PatchVersion=1'


def test_readiness_checks_compose_and_daemon(tmp_path, monkeypatch):
    import subprocess
    calls = []
    def run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 1 if 'info' in cmd else 0, '', 'permission denied')
    monkeypatch.setattr(subprocess, 'run', run)
    installer = DockerGameInstaller(tmp_path, tmp_path / 'game', docker_bin='docker')
    ready, message = installer.readiness()
    assert ready is False and 'Docker' in message
    assert any('compose' in cmd for cmd in calls) and any('info' in cmd for cmd in calls)


def test_cancellation_terminates_silent_child(tmp_path):
    installer = DockerGameInstaller(tmp_path, tmp_path / 'game', docker_bin='docker')
    job = Job('l4d2', 'install')
    timer = threading.Timer(.2, lambda: setattr(job, 'cancel', True))
    timer.start()
    start = time.monotonic()
    try:
        with pytest.raises(RuntimeError, match='取消'):
            installer._run([sys.executable, '-c', 'import time; time.sleep(30)'], job, 'test')
    finally:
        timer.cancel()
    assert time.monotonic() - start < 3


def test_log_output_is_bounded_and_secret_redacted(tmp_path):
    installer = DockerGameInstaller(tmp_path, tmp_path / 'game', docker_bin='docker')
    installer._secrets = ['very-secret-rcon']
    job = Job('l4d2', 'install')
    installer._run([sys.executable, '-c', "print('very-secret-rcon ' * 1000)"], job, 'test')
    assert 'very-secret-rcon' not in json.dumps(job.to_dict())
    assert len(job.msg) <= 500


@pytest.fixture
def docker_fixture(tmp_path):
    """A CLI boundary fixture; executes real subprocesses and filesystem copies."""
    source = tmp_path / 'image'
    game_files(source)
    (source / 'cfg').mkdir()
    (source / 'cfg/server.cfg').write_text('rcon_password "image-default"')
    (source / 'steam.inf').chmod(0o444)
    script = tmp_path / 'docker-fixture'
    script.write_text('#!' + sys.executable + '\n' + '''
import json, pathlib, shutil, sys
base = pathlib.Path(__file__).parent
args = sys.argv[1:]
with (base / 'calls.jsonl').open('a') as out: out.write(json.dumps(args) + '\\n')
if args[0] == 'create':
    pathlib.Path(args[args.index('--cidfile') + 1]).write_text('a' * 64)
    print('a' * 64)
elif args[0] == 'cp':
    shutil.copytree(base / 'image', args[-1], dirs_exist_ok=True)
elif args[0] == 'ps' and (base / 'existing.json').exists():
    print('c' * 64)
elif args[0] == 'inspect' and '--format' not in args:
    print((base / 'existing.json').read_text())
elif args[0] == 'inspect':
    print('false' if (base / 'stopped').exists() else 'true')
elif args[0] == 'compose' and 'ps' in args:
    print('b' * 64)
elif args[0] == 'compose' and 'up' in args and (base / 'fail-up').exists():
    print('start failed')
    sys.exit(1)
''')
    script.chmod(0o700)
    return script


def test_full_install_preserves_configuration_on_retry_and_recovers_metadata(tmp_path, docker_fixture):
    install, game = tmp_path / 'install', tmp_path / 'game'
    installer = DockerGameInstaller(install, game, project='our-test', docker_bin=str(docker_fixture))
    (tmp_path / 'fail-up').touch()
    with pytest.raises(RuntimeError, match='启动游戏失败'):
        installer.run(InstallOptions(rcon_password='first-secret'), Job('l4d2', 'install'))
    assert not installer.installed()
    cfg = game / 'cfg/server.cfg'
    cfg.write_text('rcon_password "keep-secret"\nhostname "keep my server"')
    (tmp_path / 'fail-up').unlink()
    installer.run(InstallOptions(rcon_password='do-not-replace'), Job('l4d2', 'install'))
    assert cfg.read_text() == 'rcon_password "keep-secret"\nhostname "keep my server"'
    assert (game / 'steam.inf').stat().st_mode & 0o200
    assert installer.installed()
    assert installer.metadata()['project'] == 'our-test'
    assert 'secret' not in (install / 'installed.json').read_text()
    calls = [json.loads(line) for line in (tmp_path / 'calls.jsonl').read_text().splitlines()]
    assert len([call for call in calls if call[0] == 'create']) == 1
    assert [call for call in calls if call[0] == 'rm'] == [['rm', '-f', 'a' * 64]]
    recovered = DockerGameInstaller(install, game, project='our-test', docker_bin=str(docker_fixture))
    assert recovered.installed()
    assert not DockerGameInstaller(install, game, project='someone-else').installed()
    with pytest.raises(RuntimeError, match='已安装'):
        recovered.run(InstallOptions(), Job('l4d2', 'install'))


def test_incomplete_image_never_populates_target(tmp_path, docker_fixture):
    (tmp_path / 'image/bin/server_srv.so').unlink()
    game = tmp_path / 'game'
    game.mkdir()
    installer = DockerGameInstaller(tmp_path / 'install', game, docker_bin=str(docker_fixture))
    with pytest.raises(RuntimeError, match='不完整'):
        installer.run(InstallOptions(), Job('l4d2', 'install'))
    assert list(game.iterdir()) == []
    assert not installer.installed()
    assert not list(tmp_path.glob('.l4d2-seed-*'))


def test_failed_start_is_not_reported_installed(tmp_path, docker_fixture):
    (tmp_path / 'stopped').touch()
    installer = DockerGameInstaller(tmp_path / 'install', tmp_path / 'game', docker_bin=str(docker_fixture))
    with pytest.raises(RuntimeError, match='已退出'):
        installer.run(InstallOptions(), Job('l4d2', 'install'))
    assert not installer.installed()
    assert not (tmp_path / 'install/installed.json').exists()


@pytest.mark.parametrize('mode,map_name', [(mode['id'], mode['map']) for mode in MODES])
def test_startup_uses_last_saved_mode_without_mutating_config(tmp_path, mode, map_name):
    import subprocess
    from l4d2panel.integrations.game_installer import START_SCRIPT
    cfg = tmp_path / 'cfg/server.cfg'
    cfg.parent.mkdir()
    text = f'mp_gamemode coop\n// mp_gamemode versus\nsm_cvar mp_gamemode "{mode}" // saved\n'
    cfg.write_text(text)
    binary = tmp_path / 'srcds_run'
    binary.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
    binary.chmod(0o700)
    script = tmp_path / 'start.sh'
    script.write_text(START_SCRIPT.replace('/l4d2/left4dead2', str(tmp_path)).replace('/l4d2/srcds_run', str(binary)))
    result = subprocess.run(['/bin/sh', str(script), '-console'], capture_output=True, text=True, check=True)
    args = result.stdout.splitlines()
    assert args[args.index('+mp_gamemode') + 1] == mode
    assert args[args.index('+map') + 1] == map_name
    assert cfg.read_text() == text


def test_refuses_unowned_compose_file_without_overwriting_it(tmp_path, docker_fixture):
    installer = DockerGameInstaller(tmp_path / 'install', tmp_path / 'game', docker_bin=str(docker_fixture))
    installer.compose_dir.mkdir()
    installer.compose_file.write_text('services: {other: {image: existing}}')
    with pytest.raises(RuntimeError, match='Compose'):
        installer.run(InstallOptions(), Job('l4d2', 'install'))
    assert installer.compose_file.read_text() == 'services: {other: {image: existing}}'
    assert not installer.game_dir.exists()


def test_refuses_foreign_container_with_same_compose_project(tmp_path, docker_fixture):
    foreign = [{
        'Config': {'Labels': {'com.docker.compose.project.working_dir': '/someone/else'}},
        'Mounts': [{'Source': '/someone/else/game', 'Destination': '/l4d2/left4dead2', 'Type': 'bind'}],
    }]
    (tmp_path / 'existing.json').write_text(json.dumps(foreign))
    installer = DockerGameInstaller(tmp_path / 'install', tmp_path / 'game', docker_bin=str(docker_fixture))
    with pytest.raises(RuntimeError, match='项目名'):
        installer.run(InstallOptions(), Job('l4d2', 'install'))
    calls = [json.loads(line) for line in (tmp_path / 'calls.jsonl').read_text().splitlines()]
    assert not any(call[0] in ('pull', 'create', 'rm') for call in calls)
    assert not installer.game_dir.exists() and not installer.compose_file.exists()


@pytest.mark.parametrize('foreign', [True, False])
def test_retry_inspects_existing_container_paths_before_reusing_project(tmp_path, docker_fixture, foreign):
    installer = DockerGameInstaller(tmp_path / 'install', tmp_path / 'game', docker_bin=str(docker_fixture))
    (tmp_path / 'fail-up').touch()
    with pytest.raises(RuntimeError, match='启动游戏失败'):
        installer.run(InstallOptions(), Job('l4d2', 'install'))
    (tmp_path / 'fail-up').unlink()
    record = [{
        'Config': {'Labels': {'com.docker.compose.project.working_dir': str(installer.compose_dir)}},
        'Mounts': [{'Source': '/unrelated' if foreign else str(installer.game_dir),
                    'Destination': '/l4d2/left4dead2', 'Type': 'bind'}],
    }]
    (tmp_path / 'existing.json').write_text(json.dumps(record))
    job = Job('l4d2', 'install')
    if foreign:
        with pytest.raises(RuntimeError, match='项目名'):
            installer.run(InstallOptions(), job)
        assert not installer.installed()
    else:
        installer.run(InstallOptions(), job)
        assert installer.installed()
    assert 'Mounts' not in json.dumps(job.to_dict())


def test_retry_refuses_replaced_compose_even_when_game_is_owned(tmp_path, docker_fixture):
    installer = DockerGameInstaller(tmp_path / 'install', tmp_path / 'game', docker_bin=str(docker_fixture))
    (tmp_path / 'fail-up').touch()
    with pytest.raises(RuntimeError, match='启动游戏失败'):
        installer.run(InstallOptions(), Job('l4d2', 'install'))
    installer.compose_file.write_text('services: {unrelated: {image: existing}}')
    with pytest.raises(RuntimeError, match='Compose'):
        installer.run(InstallOptions(), Job('l4d2', 'install'))
    with pytest.raises(RuntimeError, match='Compose'):
        installer.write_compose(InstallOptions())
    assert 'unrelated' in installer.compose_file.read_text()


def test_durable_install_is_not_adopted_after_compose_is_replaced(tmp_path, docker_fixture):
    installer = DockerGameInstaller(tmp_path / 'install', tmp_path / 'game', docker_bin=str(docker_fixture))
    installer.run(InstallOptions(), Job('l4d2', 'install'))
    installer.compose_file.write_text('{"services":{"other":{"image":"unrelated"}}}')
    assert not installer.installed()


def test_start_script_rejects_unsafe_catalog_identifiers(monkeypatch):
    from l4d2panel.integrations import game_installer
    monkeypatch.setattr(game_installer, 'MODES', ({'id': 'coop', 'map': 'map; touch /tmp/pwn'},))
    with pytest.raises(ValueError, match='不安全'):
        game_installer.render_start_script()
