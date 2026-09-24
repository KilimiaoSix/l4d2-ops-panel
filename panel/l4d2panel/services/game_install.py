"""Install one game container and activate it in the existing panel."""
import secrets
import threading

from ..errors import ApiError
from ..integrations.game_installer import DEFAULT_MIRROR, TICKS, DockerGameInstaller, InstallOptions, normalize_mirror
from ..jobs import JobRegistry
from ..settings import Paths, Settings
from ..store.audit import AuditLog


class GameInstallService:
    def __init__(self, settings: Settings, paths: Paths, jobs: JobRegistry, audit: AuditLog,
                 installer=None, operation_lock=None, activate=None):
        self.settings, self.paths, self.jobs, self.audit = settings, paths, jobs, audit
        self.installer = installer or DockerGameInstaller(paths.install_dir, paths.game, settings.docker_project)
        self.operation_lock = operation_lock or threading.Lock()
        self.activate = activate or (lambda metadata: None)

    def status(self):
        available, reason = self.installer.readiness()
        installed = self.installer.installed()
        job = self.jobs.get('install', 'l4d2')
        defaults = {'game_port': self.settings.rcon_port, 'tick': 30, 'vac': False, 'mirror_url': DEFAULT_MIRROR}
        if installed:
            metadata = self.installer.metadata()
            defaults.update({k: metadata[k] for k in defaults if k in metadata})
        return {'available': available, 'reason': reason, 'installed': installed,
                'compose_file': str(self.installer.compose_file), 'game_dir': str(self.paths.game),
                'job': job.to_dict() if job else None, 'defaults': defaults}

    def start(self, body, actor):
        port = body.get('game_port', self.settings.rcon_port)
        tick = body.get('tick', 30)
        if not isinstance(port, int) or not 1 <= port <= 65535:
            raise ApiError(400, '游戏端口必须在 1-65535 之间')
        if port == self.settings.port:
            raise ApiError(400, '游戏端口不能与当前面板端口相同')
        if tick not in TICKS: raise ApiError(400, 'Tick 必须是 30、60、100 或 128')
        try: mirror = normalize_mirror(body.get('mirror_url', DEFAULT_MIRROR))
        except ValueError as e: raise ApiError(400, str(e))
        if not self.operation_lock.acquire(blocking=False):
            raise ApiError(409, '安装或服务器操作正在进行，请稍后重试')
        try:
            available, reason = self.installer.readiness()
            if not available: raise ApiError(400, reason)
            if self.installer.installed(): raise ApiError(409, '游戏已经安装，请使用服务器控制；此入口不覆盖已有安装')
            options = InstallOptions(game_port=port, tick=tick, vac=body.get('vac', False), mirror_url=mirror,
                                     rcon_password=secrets.token_hex(16))
            def work(job):
                try:
                    self.installer.run(options, job)
                    # Metadata is committed only after the container is running. Recover the same
                    # connection on panel restart, without storing secrets in panel.json or responses.
                    self.activate(self.installer.metadata())
                    self.audit.add(actor, 'game.install.result', 'done')
                except Exception:
                    self.audit.add(actor, 'game.install.result', 'error')
                    raise
                finally:
                    self.operation_lock.release()
            job = self.jobs.start('install', 'l4d2', work, initial_msg='正在准备安装…')
        except Exception:
            self.operation_lock.release()
            raise
        self.audit.add(actor, 'game.install', f'game_port={port} tick={tick}')
        return job.id

    def cancel(self, actor):
        if not self.jobs.cancel('install', 'l4d2'): raise ApiError(400, '没有进行中的安装任务')
        self.audit.add(actor, 'game.install.cancel')
