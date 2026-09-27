"""Supervised graceful restart and a durable, bounded candidate-startup rollback journal."""
import json
import os
import re
import subprocess
import uuid

from ..errors import ApiError
from ..integrations.panel_config import ConfigConflict, ConfigError, PanelConfigFile, revision


def supported_supervisor() -> bool:
    """An environment flag alone never authorizes process exit."""
    if not re.fullmatch(r'[a-fA-F0-9]{32}', os.environ.get('INVOCATION_ID', '')): return False
    try:
        from pathlib import Path
        if not any('/l4d2panel.service' == line.rstrip().split(':')[-1][-len('/l4d2panel.service'):]
                   for line in Path('/proc/self/cgroup').read_text().splitlines()): return False
        result = subprocess.run(['systemctl', 'show', 'l4d2panel.service', '--property=MainPID', '--value'],
                                capture_output=True, text=True, timeout=3)
        return result.returncode == 0 and result.stdout.strip() == str(os.getpid())
    except (OSError, ValueError, subprocess.SubprocessError): return False


class RestartJournal:
    def __init__(self, file: PanelConfigFile):
        self.file = file
        self.path = file.base / ('.panel-restart-' + file.prefix + '.json')

    def read(self):
        if not self.path.exists(): return None
        try:
            data = json.loads(self.path.read_bytes())
            valid = data['schema'] == 1 and data['stage'] in ('candidate', 'rollback') and data['attempts'] in (0, 1)
            valid = valid and all(re.fullmatch(r'[a-f0-9]{64}', data[k]) for k in ('previous', 'candidate'))
            if not valid or not isinstance(data['backup'], str): raise ValueError()
            return data
        except (ValueError, TypeError, KeyError, OSError):
            raise ConfigError('重启恢复记录无效，请检查恢复记录及配置备份') from None

    def write(self, data):
        self.file.atomic_write(self.path, json.dumps(data).encode())

    def prepare(self, backup, previous, candidate):
        if self.path.exists(): raise ConfigConflict('已有未完成的配置重启，请先恢复')
        self.write(dict(schema=1, stage='candidate', attempts=0, backup=backup, previous=previous, candidate=candidate))

    def clear(self):
        self.path.unlink(missing_ok=True)

    def current_revision(self):
        try: return revision(self.file.path.read_bytes())
        except OSError: raise ConfigError('无法读取待恢复配置') from None

    def before_start(self):
        """Try candidate once, restore once, then let systemd's exit-78 guard stop a failing loop."""
        data = self.read()
        if not data: return
        current = self.current_revision()
        if data['stage'] == 'candidate' and current == data['previous']:
            self.clear()  # interrupted before the atomic configuration replacement
            return
        expected = data['candidate'] if data['stage'] == 'candidate' else data['previous']
        if current != expected: raise ConfigConflict('配置已被外部修改，自动恢复停止；请人工检查当前配置')
        if data['stage'] == 'rollback': raise ConfigError('原配置也未能启动；自动恢复已停止，请检查服务日志')
        if data['attempts'] == 0:
            data['attempts'] = 1; self.write(data)
            return
        self.file.restore(data['backup'], data['candidate'])
        data['stage'], data['attempts'] = 'rollback', 1
        self.write(data)

    def restore(self):
        data = self.read()
        if not data: raise ConfigError('没有待恢复的面板配置')
        current = self.current_revision()
        if current == data['previous']:
            self.clear(); return
        self.file.restore(data['backup'], data['candidate'])
        self.clear()

    def healthy(self, applied_revision):
        data = self.read()
        if not data: return
        expected = data['candidate'] if data['stage'] == 'candidate' else data['previous']
        if applied_revision != expected or self.current_revision() != expected:
            raise ConfigConflict('配置在启动期间被修改，保留恢复记录')
        self.clear()


class PanelRestart:
    def __init__(self, file, gate):
        self.file, self.gate = file, gate
        self.journal = RestartJournal(file)
        self.boot = uuid.uuid4().hex
        self.applied_snapshot = file.read()
        self.applied_revision = self.applied_snapshot.revision
        self.supervised = supported_supervisor()
        self.exit_callback = None

    @property
    def available(self):
        return self.supervised and self.exit_callback is not None

    def reserve(self):
        if not self.available: raise ApiError(409, '需要由 l4d2panel systemd 服务管理才能自动重启')
        self.gate.begin_restart()

    def request_exit(self):
        # Called as a response background task, after the acknowledgement was sent.
        if self.available and self.gate.pending:
            self.exit_callback()

    def cancel(self):
        self.gate.cancel_restart()
