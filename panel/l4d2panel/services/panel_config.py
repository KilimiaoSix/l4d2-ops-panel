"""Owner-facing configuration workflow; disk, runtime consumers and restart agree on one revision."""
import threading

from ..errors import ApiError
from ..integrations.panel_config import (ConfigConflict, ConfigError, LIVE_FIELDS, LOCATION_FIELDS,
                                         RESTART_FIELDS, SECRET_FIELDS, WRITABLE_FIELDS)


class PanelConfigService:
    def __init__(self, settings, file, restart, audit, steam, features, installed):
        self.settings, self.file, self.restart, self.audit = settings, file, restart, audit
        self.steam, self.features, self.installed = steam, features, installed
        self.lock = threading.Lock()

    def locked_fields(self):
        locked = {}
        if self.installed():
            locked.update({k: '已有游戏或安装数据，不能从面板迁移目录' for k in LOCATION_FIELDS})
        if self.settings.server_backend == 'docker':
            locked.update({k: 'Docker 安装元数据管理此连接' for k in ('rcon_host', 'rcon_port', 'rcon_password')})
        return locked

    def get(self):
        try:
            snapshot = self.file.read()
            from ..settings import Settings
            saved = Settings.model_validate(snapshot.raw)
        except (ConfigError, ValueError): raise ApiError(400, '面板配置无法读取或格式无效') from None
        locked = self.locked_fields()
        fields = {}
        for key in sorted(WRITABLE_FIELDS):
            item = {'effect': 'live' if key in LIVE_FIELDS else 'restart', 'editable': key not in locked,
                    'locked_reason': locked.get(key, '')}
            if key in SECRET_FIELDS: item['set'] = bool(getattr(saved, key))
            else: item['value'] = getattr(saved, key)
            fields[key] = item
        return {'fields': fields, 'revision': snapshot.revision, 'applied_revision': self.restart.applied_revision,
                'config_path': str(self.file.path), 'supervised': self.restart.available,
                'boot': self.restart.boot, 'restart_pending': self.restart.gate.pending}

    def save(self, expected, updates, restart, actor):
        with self.lock:
            reserved = False
            try:
                old, candidate, changed, proposed = self.file.prepare(expected, updates, self.settings)
                from ..settings import Settings
                applied = Settings.model_validate(self.restart.applied_snapshot.raw)
                on_disk = Settings.model_validate(old.raw)
                if applied != on_disk:
                    raise ApiError(409, '启动配置已被外部程序修改，请先从服务管理器重启面板，再编辑配置')
                for key in changed:
                    if key in self.locked_fields(): raise ApiError(409, self.locked_fields()[key])
                requires = bool(set(changed) & (RESTART_FIELDS | LOCATION_FIELDS))
                if requires and not restart: raise ApiError(409, 'restart_required: 这些配置需要确认重启后保存')
                if requires:
                    self.restart.reserve(); reserved = True
                    result = self.file.save(expected, updates, self.settings, before_commit=self.restart.journal.prepare)
                else:
                    with self.restart.gate.activity():
                        result = self.file.save(expected, updates, self.settings)
                        for key in result.changed: setattr(self.settings, key, getattr(proposed, key))
                        self.steam.api_key = self.settings.steam_api_key
                        self.features.invalidate()
                        self.restart.applied_revision = result.snapshot.revision
                        self.restart.applied_snapshot = result.snapshot
                self.audit.add(actor, 'panel.config', ','.join(result.changed) or 'unchanged')
                return {'saved': bool(result.changed), 'revision': result.snapshot.revision, 'changed': result.changed,
                        'restart_scheduled': requires, 'boot': self.restart.boot, 'backup': result.backup,
                        'next_listener': {'bind': proposed.bind, 'port': proposed.port, 'tls': proposed.tls}}
            except Exception as exc:
                if reserved:
                    # A failed commit must not leave a pending admission gate. Recover only our own version.
                    try:
                        if self.restart.journal.read(): self.restart.journal.restore()
                    except ConfigError:
                        self.restart.cancel()
                        raise ApiError(409, '保存失败且配置发生外部变化，请运行 l4d2panel-recover 检查恢复') from None
                    self.restart.cancel()
                if isinstance(exc, ConfigConflict): raise ApiError(409, str(exc)) from None
                if isinstance(exc, ConfigError): raise ApiError(400, str(exc)) from None
                if isinstance(exc, OSError): raise ApiError(500, '保存配置失败，请检查文件权限和磁盘空间') from None
                raise
