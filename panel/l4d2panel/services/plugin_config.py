"""Plugin-owned configuration files and separately verified live ConVar writes."""
import json
import re
import threading
from decimal import Decimal, InvalidOperation

from ..errors import ApiError, IntegrationError
from ..integrations.convars import ConVarReadError, read_convar
from ..integrations.plugin_config import ConfigFiles, ConfigProblem, validate_updates

PLUGIN = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.-]*\.smx')
MAX_BATCH = 20


class PluginConfigService:
    def __init__(self, paths, rcon, audit):
        self.paths, self.rcon, self.audit = paths, rcon, audit
        self.files = ConfigFiles(paths.game / 'cfg' / 'sourcemod', paths.base / 'config_backups')
        self.lock = threading.RLock()

    def _file_call(self, fn, *args):
        try:
            return fn(*args)
        except ConfigProblem as exc:
            raise ApiError({'invalid': 400, 'conflict': 409, 'missing': 404}.get(exc.kind, 400), str(exc)) from exc
        except OSError as exc:
            raise ApiError(500, f'配置文件操作失败: {exc}') from exc

    def _plugin(self, plugin):
        if not PLUGIN.fullmatch(plugin):
            raise ApiError(400, '无效的插件文件名')
        enabled = self.paths.sm_plugins / plugin
        disabled = self.paths.sm_disabled / plugin
        if not any(p.is_file() and not p.is_symlink() for p in (enabled, disabled)):
            raise ApiError(404, '插件不存在')
        return enabled.is_file() and not enabled.is_symlink()

    def discover(self, plugin):
        self._plugin(plugin)
        return {'plugin': plugin, 'files': self._file_call(self.files.discover, plugin)}

    def read(self, plugin, file):
        candidates = self.discover(plugin)['files']
        if file not in {entry['name'] for entry in candidates}:
            raise ApiError(404, '未找到属于该插件的配置文件')
        return {'plugin': plugin, **self._file_call(self.files.read, file)}

    @staticmethod
    def _batch(items):
        if not 1 <= len(items) <= MAX_BATCH:
            raise ApiError(400, f'每次请选择 1–{MAX_BATCH} 个参数')

    def runtime(self, plugin, file, names):
        self._batch(names)
        doc = self.read(plugin, file)
        params = {p['name']: p for p in doc['parameters']}
        if len(set(names)) != len(names) or any(name not in params or not params[name]['editable'] for name in names):
            raise ApiError(400, '只能读取该配置中可识别的参数')
        enabled = self._plugin(plugin)
        values = []
        connection_error = None
        for name in names:
            value, error = None, None
            try:
                if not enabled:
                    raise IntegrationError('插件已禁用，运行值不可用')
                if connection_error:
                    raise IntegrationError(connection_error)
                value = read_convar(self.rcon, name)
            except ConVarReadError as exc:
                error = str(exc)
            except IntegrationError as exc:
                connection_error = error = str(exc)
            values.append({'name': name, 'value': value, 'error': error})
        return {'values': values}

    def _audit(self, actor, action, plugin, file, changes):
        # Structured records preserve complete values; one record per parameter.
        for name, change in changes.items():
            self.audit.add(actor, action, {'plugin': plugin, 'file': file, 'name': name, **change})

    def update(self, actor, plugin, file, revision, updates, mode):
        self._batch(updates)
        with self.lock:
            doc = self.read(plugin, file)
            if doc['revision'] != revision:
                raise ApiError(409, '配置已被其他操作修改，请重新读取后再保存')
            validated = self._file_call(validate_updates, doc, updates)
            if mode != 'save' and not self._plugin(plugin):
                raise ApiError(400, '插件已禁用，可以保存配置，启用后再应用')
            saved, backup_id = False, None
            old = {p['name']: p for p in doc['parameters']}
            if mode in ('save', 'save_apply'):
                result, backup_id = self._file_call(self.files.save, file, revision, validated)
                doc = {'plugin': plugin, **result}
                saved = True
                self._audit(actor, 'plugin.config.save', plugin, file,
                            {name: {'before': old[name]['value'], 'after': value} for name, value in validated.items()})
            applied = []
            if mode in ('apply', 'save_apply'):
                connection_error = None
                for name, requested in validated.items():
                    value, status, error = None, 'error', None
                    try:
                        if connection_error:
                            raise IntegrationError(connection_error)
                        # Values have already been constrained to safe single arguments.
                        self.rcon.run(f'sm_cvar {name} "{requested}"')
                        value = read_convar(self.rcon, name)
                        same = value == requested
                        if not same and old[name]['type'] == 'number':
                            try:
                                same = Decimal(value) == Decimal(requested)
                            except InvalidOperation:
                                pass
                        status = 'applied' if same else 'adjusted'
                    except ConVarReadError as exc:
                        error = str(exc)
                    except IntegrationError as exc:
                        connection_error = error = str(exc)
                    applied.append({'name': name, 'requested': requested, 'value': value, 'status': status, 'error': error})
                    self._audit(actor, 'plugin.config.apply', plugin, file,
                                {name: {'requested': requested, 'actual': value, 'status': status}})
            return {'saved': saved, 'backup_id': backup_id, 'document': doc, 'applied': applied}

    def restore(self, actor, plugin, file, revision, backup_id):
        with self.lock:
            self.read(plugin, file)
            doc, previous = self._file_call(self.files.restore, file, revision, backup_id)
            self.audit.add(actor, 'plugin.config.restore', json.dumps({'plugin': plugin, 'file': file, 'backup_id': backup_id}, ensure_ascii=False))
            return {'saved': True, 'backup_id': previous, 'document': {'plugin': plugin, **doc}, 'applied': []}
