"""SourceMod plugin manager: plugins/ holds the enabled .smx files, plugins/disabled/ the disabled ones; core
plugins in the protected list cannot be disabled or deleted."""
import os, re
from pathlib import Path

from ..errors import ApiError
from ..integrations.rcon import RconClient
from ..integrations.sm_files import list_smx
from ..settings import Paths, Settings
from ..store.audit import AuditLog

SMX_MAGIC = b'FFPS'
MAX_SMX = 20 * 1048576
OPS = ('reload', 'disable', 'enable', 'delete')


def plugin_name(n):
    """Bare plugin name (no directory, no .smx) made of [A-Za-z0-9_.-], or None."""
    n = os.path.basename(str(n)).strip()
    if n.endswith('.smx'): n = n[:-4]
    return n if re.match(r'^[\w.\-]+$', n) else None


class PluginService:
    def __init__(self, settings: Settings, paths: Paths, rcon: RconClient, audit: AuditLog):
        self.paths, self.rcon, self.audit = paths, rcon, audit
        self.protected = set(settings.protected_plugins)

    def list(self) -> dict:
        raw = ''
        try: raw = self.rcon.run('sm plugins list')
        except Exception: pass
        return {'enabled': [{'file': f, 'protected': f[:-4] in self.protected} for f in list_smx(self.paths.sm_plugins)],
                'disabled': [{'file': f} for f in list_smx(self.paths.sm_disabled)], 'raw': raw}

    def action(self, op: str, file, actor: str) -> dict:
        if op not in OPS: raise ApiError(400, 'bad op')
        nm = plugin_name(file)
        if not nm: raise ApiError(400, '无效的插件名')
        fn = nm + '.smx'; en = self.paths.sm_plugins / fn; di = self.paths.sm_disabled / fn
        if op == 'reload':
            out = self.rcon.run('sm plugins reload ' + nm)
        elif op == 'disable':
            if nm in self.protected: raise ApiError(400, '该插件受保护，不能禁用')
            if not en.exists(): raise ApiError(400, '插件不在启用目录')
            os.makedirs(self.paths.sm_disabled, exist_ok=True)
            out = ''
            try: out = self.rcon.run('sm plugins unload ' + nm)
            except Exception: pass
            os.replace(en, di); out = (out + ' — 已移入 disabled/').strip()
        elif op == 'enable':
            if not di.exists(): raise ApiError(400, '插件不在禁用目录')
            os.replace(di, en)
            try: out = self.rcon.run('sm plugins load ' + nm) + ' — 已启用'
            except Exception as e: out = f'已移入 plugins/，加载失败（换图或重启后生效）: {e}'
        else:   # delete
            if nm in self.protected: raise ApiError(400, '该插件受保护，不能删除')
            if not di.exists(): raise ApiError(400, '只能删除已禁用的插件（先禁用再删）')
            os.remove(di); out = '已删除禁用的插件 ' + fn
        self.audit.add(actor, 'plugin.' + op, fn)
        return {'out': out, **self.list()}

    def upload_target(self, raw_name) -> tuple:
        """-> (plugin name, temp path to stream the body into). Raises 400 for an unusable name."""
        nm = plugin_name(raw_name)
        if not nm: raise ApiError(400, '只接受 .smx 文件')
        return nm, self.paths.sm_plugins / (nm + '.smx.tmp')

    def check_upload_size(self, n: int):
        if n <= 0 or n > MAX_SMX: raise ApiError(400, '文件为空或过大（>20MB）')

    def finish_upload(self, nm: str, tmp, got: int, expected: int, actor: str) -> dict:
        tmp = Path(tmp)
        with open(tmp, 'rb') as f: magic = f.read(4)
        if got != expected or magic != SMX_MAGIC:
            tmp.unlink(missing_ok=True); raise ApiError(400, '不是有效的 .smx 插件文件')
        os.replace(tmp, self.paths.sm_plugins / (nm + '.smx'))
        self.audit.add(actor, 'plugin.upload', nm)
        try: out = self.rcon.run('sm plugins load ' + nm)
        except Exception as e: out = f'已上传，加载失败（换图或重启后生效）: {e}'
        return {'ok': True, 'out': out, **self.list()}
