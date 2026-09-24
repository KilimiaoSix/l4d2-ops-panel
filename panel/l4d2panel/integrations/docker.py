"""Docker Compose operations scoped to this installation's game service."""
import json
import shutil
import subprocess
from pathlib import Path

from .lgsm import ANSI
from ..settings import Paths, Settings


class DockerServer:
    def __init__(self, settings: Settings, paths: Paths):
        self.settings, self.paths = settings, paths
        self.compose_file = paths.install_dir / 'docker-compose.yaml'

    def available(self) -> bool:
        return bool(shutil.which('docker')) and self.compose_file.is_file()

    def _command(self, args, timeout=20):
        try:
            result = subprocess.run(['docker', *args], capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError('Docker 命令超时，请检查容器状态') from exc
        except OSError as exc:
            raise RuntimeError(f'无法运行 Docker: {exc}') from exc
        output = ANSI.sub('', result.stdout + result.stderr).strip()
        if result.returncode:
            raise RuntimeError(f'Docker 操作失败 ({result.returncode}): {output[-2000:]}')
        return result.stdout, output

    def _compose(self, args, timeout=20):
        return self._command(['compose', '-p', self.settings.docker_project, '-f', str(self.compose_file), *args], timeout)

    def _check_start_config(self):
        try:
            game = json.loads(self.compose_file.read_text())['services']['l4d2']
            volumes = game.get('volumes', [])
            if not all(isinstance(mount, dict) for mount in volumes):
                raise ValueError('unsupported mount format')
            mounts = [mount for mount in volumes if mount.get('target') == '/l4d2/left4dead2']
            if (len(mounts) != 1 or mounts[0].get('type') != 'bind' or
                    not mounts[0].get('source') or
                    Path(mounts[0]['source']).resolve() != self.paths.game.resolve()):
                raise ValueError('wrong game mount')
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            raise RuntimeError('Compose 配置无效或游戏绑定目录不属于当前安装，拒绝启动') from exc

    def _container(self):
        stdout, _ = self._command(['ps', '-a', '-q',
                                   '--filter', f'label=com.docker.compose.project={self.settings.docker_project}',
                                   '--filter', 'label=com.docker.compose.service=l4d2',
                                   '--filter', 'label=com.docker.compose.oneoff=False'])
        ids = stdout.split()
        if not ids: return None
        if len(ids) != 1: raise RuntimeError('发现多个游戏容器，无法确定容器归属')
        stdout, _ = self._command(['inspect', ids[0]])
        try:
            info = json.loads(stdout)[0]
            labels = info['Config'].get('Labels') or {}
            if (labels.get('com.docker.compose.project') != self.settings.docker_project or
                    labels.get('com.docker.compose.service') != 'l4d2' or
                    not labels.get('com.docker.compose.project.working_dir') or
                    Path(labels['com.docker.compose.project.working_dir']).resolve() != self.paths.install_dir.resolve()):
                raise RuntimeError('容器归属与当前游戏安装不一致')
            mounts = [mount for mount in info.get('Mounts', [])
                      if mount.get('Destination') == '/l4d2/left4dead2']
            if (len(mounts) != 1 or mounts[0].get('Type') != 'bind' or
                    not mounts[0].get('Source') or
                    Path(mounts[0]['Source']).resolve() != self.paths.game.resolve()):
                raise RuntimeError('容器游戏目录归属与当前安装不一致')
            return info
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise RuntimeError('Docker 返回了无效的容器状态') from exc

    def running(self) -> bool:
        info = self._container()
        return bool(info and info['State']['Running'])

    def run(self, action: str) -> str:
        if action == 'monitor':
            info = self._container()
            return f"Docker 游戏容器: {info['State']['Status']}" if info else 'Docker 游戏容器尚未创建'
        if action not in ('start', 'stop', 'restart'): raise ValueError('bad action')
        if action == 'start': self._check_start_config()
        info = self._container()
        if not info and action != 'start': return 'Docker 游戏容器尚未创建'
        if action == 'start':
            _, output = self._compose(['up', '-d', '--no-deps', 'l4d2'], timeout=240)
        else:
            # Stop/restart the inspected ID even if somebody replaced the Compose file.
            _, output = self._command([action, info['Id']], timeout=240)
        return output.splitlines()[-1] if output else f'{action} done'

    def console(self, n=150):
        info = self._container()
        if not info: return []
        _, output = self._command(['logs', '--tail', str(max(1, min(int(n), 1000))), info['Id']])
        return output.splitlines()
