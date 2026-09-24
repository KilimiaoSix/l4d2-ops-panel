"""Docker game installation and durable installation metadata.

Game data is copied from the upstream image into a staging directory. The upstream
start.sh is deliberately bypassed because it rewrites server.cfg on every start.
"""
from __future__ import annotations

import itertools
import json
import os
import re
import secrets
import selectors
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from ..game_modes import MODES

GAME_IMAGE = 'laoyutang/l4d2-pure:latest'
PROJECT_NAME = 'l4d2'
TICKS = (30, 60, 100, 128)
DEFAULT_MIRROR = 'docker.cnb.cool'
_MIRROR = re.compile(r'^[A-Za-z0-9.-]+(?::[0-9]{1,5})?$')
_MARKER = '.l4d2-panel-install.json'
_REQUIRED = ('steam.inf', 'gameinfo.txt', 'bin/server_srv.so')

_START_SCRIPT_TEMPLATE = r'''#!/bin/sh
set -eu
# Select a compatible initial map without changing the saved server configuration.
mode=$(awk '
BEGIN { mode = "coop"; block = 0 }
{
    line = $0
    while (1) {
        if (block) {
            end = index(line, "*/")
            if (!end) { line = ""; break }
            line = substr(line, end + 2); block = 0
        }
        start = index(line, "/*")
        if (!start) break
        prefix = substr(line, 1, start - 1)
        rest = substr(line, start + 2)
        end = index(rest, "*/")
        if (end) line = prefix substr(rest, end + 2)
        else { line = prefix; block = 1; break }
    }
    sub(/\/\/.*/, "", line)
    gsub(/\r/, "", line)
    $0 = tolower(line)
    value = ""
    if ($1 == "mp_gamemode" && NF == 2) value = $2
    if ($1 == "sm_cvar" && $2 == "mp_gamemode" && NF == 3) value = $3
    gsub(/"/, "", value)
    if (value ~ /^(__MODE_IDS__)$/) mode = value
}
END { print mode }
' /l4d2/left4dead2/cfg/server.cfg)
case "$mode" in
__MAP_CASES__
    *) map=__DEFAULT_MAP__ ;;
esac
exec /l4d2/srcds_run "$@" +mp_gamemode "$mode" +map "$map"
'''


def render_start_script() -> str:
    modes = [(mode['id'], mode['map']) for mode in MODES]
    if any(not re.fullmatch(r'[a-z0-9_]+', value) for pair in modes for value in pair):
        raise ValueError('模式目录包含不安全的模式或地图标识')
    default_map = dict(modes)['coop']
    return (_START_SCRIPT_TEMPLATE.replace('__MODE_IDS__', '|'.join(mode for mode, _ in modes))
            .replace('__MAP_CASES__', '\n'.join(f'    {mode}) map={map_name} ;;' for mode, map_name in modes))
            .replace('__DEFAULT_MAP__', default_map))


START_SCRIPT = render_start_script()


@dataclass(frozen=True)
class InstallOptions:
    game_port: int = 27015
    tick: int = 30
    vac: bool = False
    mirror_url: str = DEFAULT_MIRROR
    rcon_password: str = ''


def normalize_mirror(value: str) -> str:
    value = str(value or '').strip().removeprefix('https://').removeprefix('http://').rstrip('/')
    if value and not _MIRROR.fullmatch(value):
        raise ValueError('镜像源格式无效')
    return value


def image_name(image: str, mirror: str) -> str:
    mirror = normalize_mirror(mirror)
    return f'{mirror}/{image}' if mirror else image


def render_compose(options: InstallOptions, game_dir: Path, mirror: str = DEFAULT_MIRROR,
                   *, image_override: str | None = None) -> str:
    command = ['-game', 'left4dead2', '-console', '-condebug', '-usercon', '-norestart',
               '-port', str(options.game_port), '-tickrate', str(options.tick)]
    if not options.vac:
        command.append('-insecure')
    command += ['+exec', 'server.cfg']
    game = {
        'image': image_override or image_name(GAME_IMAGE, mirror),
        'platform': 'linux/amd64',
        'user': f'{os.getuid()}:{os.getgid()}',
        'working_dir': '/l4d2',
        'environment': {'HOME': '/tmp'},
        'entrypoint': ['/bin/sh', '/l4d2/left4dead2/.l4d2-panel-start.sh'],
        'command': command,
        'restart': 'unless-stopped',
        'security_opt': ['seccomp:unconfined'],
        'ports': [f'{options.game_port}:{options.game_port}/tcp', f'{options.game_port}:{options.game_port}/udp'],
        'volumes': [{'type': 'bind', 'source': str(Path(game_dir).expanduser().resolve()),
                     'target': '/l4d2/left4dead2'}],
        'logging': {'options': {'max-size': '50m', 'max-file': '3'}},
    }
    return json.dumps({'services': {'l4d2': game}}, ensure_ascii=False, indent=2) + '\n'


class DockerGameInstaller:
    def __init__(self, compose_dir: Path, game_dir: Path, project: str = PROJECT_NAME,
                 docker_bin: str | None = None, *, image_override: str | None = None):
        self.compose_dir = Path(compose_dir).expanduser().resolve()
        self.game_dir = Path(game_dir).expanduser().resolve()
        self.project = project
        self.docker_bin = docker_bin or shutil.which('docker')
        self.image_override = image_override
        self._secrets: list[str] = []

    @property
    def compose_file(self) -> Path:
        return self.compose_dir / 'docker-compose.yaml'

    def readiness(self) -> tuple[bool, str]:
        self.docker_bin = self.docker_bin or shutil.which('docker')
        if not self.docker_bin:
            return False, '未检测到 Docker，请先安装 Docker'
        for args, label in ((['compose', 'version'], 'Docker Compose 不可用'),
                            (['info', '--format', '{{.ServerVersion}}'], 'Docker daemon 不可用或当前用户没有权限')):
            try:
                result = subprocess.run([self.docker_bin, *args], capture_output=True, text=True, timeout=8)
                if result.returncode:
                    return False, label
            except (OSError, subprocess.TimeoutExpired):
                return False, label
        return True, ''

    def available(self) -> bool:
        return self.readiness()[0]

    def _identity(self) -> dict:
        return {'game_dir': str(self.game_dir), 'project': self.project}

    def _owner_identity(self) -> dict:
        return {**self._identity(), 'compose_dir': str(self.compose_dir)}

    def _owned(self) -> bool:
        try:
            return json.loads((self.game_dir / _MARKER).read_text()) == self._owner_identity()
        except (OSError, ValueError):
            return False

    def _valid_game(self, root: Path) -> bool:
        return all((root / name).is_file() for name in _REQUIRED)

    def metadata(self) -> dict:
        try:
            result = json.loads((self.compose_dir / 'installed.json').read_text())
            if not isinstance(result, dict) or any(result.get(k) != v for k, v in self._identity().items()):
                return {}
            if type(result.get('game_port')) is not int or not 1 <= result['game_port'] <= 65535:
                return {}
            return result
        except (OSError, ValueError):
            return {}

    def installed(self) -> bool:
        try:
            self._check_compose_file()
        except RuntimeError:
            return False
        return bool(self.metadata() and self.compose_file.is_file() and self._owned()
                    and self._valid_game(self.game_dir) and (self.game_dir / 'cfg/server.cfg').is_file()
                    and (self.game_dir / '.l4d2-panel-start.sh').is_file())

    def _check_target(self) -> None:
        if self.game_dir.exists() and (not self.game_dir.is_dir() or any(self.game_dir.iterdir())):
            if not self._owned():
                raise RuntimeError('game_dir 非空且不是本面板的安装目录，拒绝覆盖已有游戏')
            if not self._valid_game(self.game_dir):
                raise RuntimeError('已初始化的游戏文件不完整，请检查目录；安装器不会覆盖已有文件')

    def _check_compose_file(self) -> None:
        if not self.compose_file.exists():
            return
        conflict = 'install_dir 中存在非本安装任务的 Compose 文件，拒绝覆盖'
        if not self._owned():
            raise RuntimeError(conflict)
        try:
            config = json.loads(self.compose_file.read_text())
            services = config['services']
            if set(services) != {'l4d2'}:
                raise ValueError('unrelated services')
            game = services['l4d2']
            expected = {'type': 'bind', 'source': str(self.game_dir), 'target': '/l4d2/left4dead2'}
            if expected not in game.get('volumes', []) or game.get('entrypoint') != [
                    '/bin/sh', '/l4d2/left4dead2/.l4d2-panel-start.sh']:
                raise ValueError('unrelated game')
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            raise RuntimeError(conflict) from None

    def _check_project(self, job) -> None:
        self._check_compose_file()
        ids = self._run([self.docker_bin, 'ps', '-a', '-q',
                         '--filter', f'label=com.docker.compose.project={self.project}',
                         '--filter', 'label=com.docker.compose.service=l4d2'],
                        job, '检查 Docker 项目', timeout=30, log_output=False).split()
        if not ids:
            return
        conflict = 'Docker 项目名已被其他游戏容器使用，请更换 docker_project 和 install_dir'
        if not self._owned() or any(not re.fullmatch(r'[a-f0-9]{12,64}', cid) for cid in ids):
            raise RuntimeError(conflict)
        try:
            containers = json.loads(self._run([self.docker_bin, 'inspect', *ids], job,
                                             '检查已有游戏容器', timeout=30, log_output=False))
            if not isinstance(containers, list) or len(containers) != len(ids):
                raise ValueError('invalid inspect result')
            for container in containers:
                labels = container.get('Config', {}).get('Labels', {}) or {}
                same_directory = labels.get('com.docker.compose.project.working_dir') == str(self.compose_dir)
                same_game = any(mount.get('Type') == 'bind'
                                and mount.get('Source') == str(self.game_dir)
                                and mount.get('Destination') == '/l4d2/left4dead2'
                                for mount in container.get('Mounts', []))
                if not same_directory or not same_game:
                    raise ValueError('foreign container')
        except (ValueError, TypeError, AttributeError):
            raise RuntimeError(conflict) from None

    def _atomic_json(self, target: Path, value: dict) -> None:
        fd, name = tempfile.mkstemp(prefix='.' + target.name, dir=target.parent)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(value, stream, ensure_ascii=False, indent=2)
            os.replace(name, target)
        finally:
            Path(name).unlink(missing_ok=True)

    def write_compose(self, options: InstallOptions) -> Path:
        self._check_compose_file()
        self.compose_dir.mkdir(parents=True, exist_ok=True)
        config = json.loads(render_compose(options, self.game_dir, options.mirror_url,
                                          image_override=self.image_override))
        self._atomic_json(self.compose_file, config)
        return self.compose_file

    def command(self) -> list[str]:
        if not self.docker_bin:
            raise RuntimeError('未检测到 Docker')
        return [self.docker_bin, 'compose', '-p', self.project, '-f', str(self.compose_file)]

    def _redact(self, text: str) -> str:
        for secret in self._secrets:
            if secret:
                text = text.replace(secret, '[REDACTED]')
        return text

    def _log(self, job, line: str) -> None:
        line = self._redact(line).strip()[-500:]
        if line:
            logs = job.extra.setdefault('logs', [])
            logs.append(line)
            del logs[:-80]
            job.msg = line

    def _run(self, cmd: list[str], job, label: str, *, timeout: float = 3600, log_output: bool = True) -> str:
        if job.cancel:
            raise RuntimeError('安装已取消')
        proc = subprocess.Popen(cmd, cwd=str(self.compose_dir), stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT)
        output, pending = b'', b''
        started = time.monotonic()
        selector = selectors.DefaultSelector()
        try:
            selector.register(proc.stdout, selectors.EVENT_READ)
            while selector.get_map():
                if job.cancel:
                    raise RuntimeError('安装已取消')
                if time.monotonic() - started > timeout:
                    raise RuntimeError(f'{label}超时')
                for key, _ in selector.select(.1):
                    chunk = os.read(key.fd, 8192)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    output = (output + chunk)[-32768:]
                    pending += chunk
                    while b'\n' in pending:
                        line, pending = pending.split(b'\n', 1)
                        if log_output:
                            self._log(job, line.decode('utf-8', errors='replace'))
                    if len(pending) > 65536:
                        if log_output:
                            self._log(job, pending.decode('utf-8', errors='replace'))
                        pending = b''
            if pending and log_output:
                self._log(job, pending.decode('utf-8', errors='replace'))
            while proc.poll() is None:
                if job.cancel:
                    raise RuntimeError('安装已取消')
                if time.monotonic() - started > timeout:
                    raise RuntimeError(f'{label}超时')
                time.sleep(.05)
            if job.cancel:
                raise RuntimeError('安装已取消')
            if proc.returncode:
                raise RuntimeError(f'{label}失败（退出码 {proc.returncode}）')
            return self._redact(output.decode('utf-8', errors='replace')).strip()
        finally:
            selector.close()
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2)
            if proc.stdout:
                proc.stdout.close()

    def _seed_bind_mount(self, options: InstallOptions, job) -> None:
        if self._owned():
            return
        self.game_dir.parent.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix='.l4d2-seed-', dir=self.game_dir.parent))
        cidfile = self.compose_dir / ('.seed-' + secrets.token_hex(12) + '.cid')
        try:
            image = self.image_override or image_name(GAME_IMAGE, options.mirror_url)
            self._run([self.docker_bin, 'create', '--platform', 'linux/amd64', '--cidfile', str(cidfile), image],
                      job, '创建初始化容器', timeout=60)
            cid = cidfile.read_text().strip()
            if not re.fullmatch(r'[a-f0-9]{12,64}', cid):
                raise RuntimeError('初始化容器 ID 无效')
            self._run([self.docker_bin, 'cp', f'{cid}:/l4d2/left4dead2/.', str(stage)], job, '复制游戏文件')
            if not self._valid_game(stage):
                raise RuntimeError('镜像中的游戏文件不完整')
            # docker cp (without -a) gives the caller ownership; keep owner writes
            # enabled for uploads/config edits even when the source files are read-only.
            for path in itertools.chain((stage,), stage.rglob('*')):
                if job.cancel:
                    raise RuntimeError('安装已取消')
                if not path.is_symlink():
                    os.chmod(path, path.stat().st_mode | 0o600 | (0o100 if path.is_dir() else 0))
            self._initialize_config(options, stage)
            (stage / '.l4d2-panel-start.sh').write_text(START_SCRIPT, encoding='utf-8')
            self._atomic_json(stage / _MARKER, self._owner_identity())
            if job.cancel:
                raise RuntimeError('安装已取消')
            if self.game_dir.exists():
                self.game_dir.rmdir()  # Fails safely if another writer populated it.
            os.replace(stage, self.game_dir)
        finally:
            # The cidfile is unique to this operation. Never remove a named/shared container.
            if cidfile.is_file():
                cid = cidfile.read_text().strip()
                if re.fullmatch(r'[a-f0-9]{12,64}', cid):
                    try:
                        subprocess.run([self.docker_bin, 'rm', '-f', cid], capture_output=True, timeout=15)
                    except (OSError, subprocess.TimeoutExpired):
                        pass
                cidfile.unlink(missing_ok=True)
            if stage.exists():
                shutil.rmtree(stage)

    def _initialize_config(self, options: InstallOptions, stage: Path) -> None:
        # Configure inside staging so adoption and first credential creation commit
        # together. Subsequent attempts must preserve all user configuration.
        target = stage / 'cfg/server.cfg'
        target.parent.mkdir(parents=True, exist_ok=True)
        password = options.rcon_password or secrets.token_urlsafe(24)
        if any(c in password for c in '\r\n"\\'):
            raise ValueError('RCON 密码包含不支持的字符')
        self._secrets.append(password)
        fd, name = tempfile.mkstemp(prefix='.server.cfg-', dir=target.parent)
        try:
            with os.fdopen(fd, 'w') as stream:
                stream.write(f'hostname "L4D2 Server"\nrcon_password "{password}"\nsv_lan 0\n'
                             'sv_allow_lobby_connect_only 0\nmp_gamemode coop\nsv_logfile 1\nlog on\n')
            os.replace(name, target)
        finally:
            Path(name).unlink(missing_ok=True)

    def run(self, options: InstallOptions, job) -> None:
        self._check_target()
        if self.installed():
            raise RuntimeError('游戏已安装，请使用服务器管理操作')
        if self.compose_dir == self.game_dir or self.compose_dir.is_relative_to(self.game_dir):
            raise RuntimeError('install_dir 不能位于 game_dir 内')
        self.compose_dir.mkdir(parents=True, exist_ok=True)
        self._secrets = [options.rcon_password] if options.rcon_password else []
        self._check_project(job)
        job.total, job.done = 4, 0
        image = self.image_override or image_name(GAME_IMAGE, options.mirror_url)
        if not self.image_override:
            self._run([self.docker_bin, 'pull', '--platform', 'linux/amd64', image], job, '拉取游戏镜像')
        job.done = 1
        self._seed_bind_mount(options, job)
        if not (self.game_dir / 'cfg/server.cfg').is_file():
            raise RuntimeError('server.cfg 已丢失，请恢复配置后重试')
        config_text = (self.game_dir / 'cfg/server.cfg').read_text(encoding='utf-8', errors='replace')
        self._secrets.extend(re.findall(r'^\s*rcon_password\s+"([^"]+)"', config_text, re.M))
        self.write_compose(options)
        job.done = 2
        self._run(self.command() + ['up', '-d', '--no-build', '--pull', 'never', 'l4d2'], job, '启动游戏')
        job.done = 3
        cid = self._run(self.command() + ['ps', '-q', 'l4d2'], job, '查询游戏容器', timeout=30).strip()
        if not re.fullmatch(r'[a-f0-9]{12,64}', cid):
            raise RuntimeError('游戏容器没有运行')
        running = self._run([self.docker_bin, 'inspect', '--format', '{{.State.Running}}', cid],
                            job, '检查游戏容器', timeout=30)
        if running != 'true':
            raise RuntimeError('游戏容器启动后已退出，请查看 Docker 日志')
        if job.cancel:
            raise RuntimeError('安装已取消')
        self._atomic_json(self.compose_dir / 'installed.json', {
            **self._identity(), 'game_port': options.game_port, 'tick': options.tick,
            'vac': options.vac, 'mirror_url': normalize_mirror(options.mirror_url),
        })
        job.done, job.msg = 4, 'L4D2 游戏容器已启动，首次加载地图可能需要等待'
