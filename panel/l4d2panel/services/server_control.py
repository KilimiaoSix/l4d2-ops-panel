"""Server lifecycle through the selected backend, serialized with game installation."""
import threading, time

from ..errors import ApiError
from ..integrations.lgsm import Lgsm
from ..integrations.srcds import srcds_running
from ..store.audit import AuditLog

ACTIONS = ('start', 'stop', 'restart', 'monitor')


class ServerControl:
    def __init__(self, lgsm: Lgsm, audit: AuditLog, docker=None, settings=None, operation_lock=None):
        self.lgsm, self.audit, self.docker, self.settings = lgsm, audit, docker, settings
        self.operation_lock = operation_lock if operation_lock is not None else threading.Lock()
        self.state = {'running': None, 'last': ''}

    @property
    def backend(self):
        return self.docker if self.settings and self.settings.server_backend == 'docker' else self.lgsm

    def available(self):
        return self.backend is not None and self.backend.available()

    def running(self):
        return self.docker.running() if self.backend is self.docker and self.docker else srcds_running()

    def run(self, action: str, actor: str) -> bool:
        """Kick off the action; False when another action or install is still running."""
        if action not in ACTIONS: raise ApiError(400, 'bad action')
        if not self.operation_lock.acquire(blocking=False): return False
        try:
            backend = self.backend
            if not self.available():
                name = 'Docker 或 Compose 安装文件' if self.settings and self.settings.server_backend == 'docker' else 'LinuxGSM 脚本'
                raise ApiError(400, f'未配置 {name}')
            self.state['running'] = action
            self.audit.add(actor, 'server.' + action)
            def work():
                try:
                    self.state['last'] = f'{time.strftime("%H:%M:%S")} {action}: ' + backend.run(action)
                except Exception as e:
                    self.state['last'] = f'{action} 失败: {e}'
                finally:
                    self.state['running'] = None
                    self.operation_lock.release()
            threading.Thread(target=work, daemon=True).start()
        except Exception:
            self.state['running'] = None
            self.operation_lock.release()
            raise
        return True
