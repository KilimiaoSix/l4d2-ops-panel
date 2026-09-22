"""Start / stop / restart / monitor through LinuxGSM, one action at a time, in the background."""
import threading, time

from ..errors import ApiError
from ..integrations.lgsm import Lgsm
from ..store.audit import AuditLog

ACTIONS = ('start', 'stop', 'restart', 'monitor')


class ServerControl:
    def __init__(self, lgsm: Lgsm, audit: AuditLog):
        self.lgsm, self.audit = lgsm, audit
        self.state = {'running': None, 'last': ''}

    def run(self, action: str, actor: str) -> bool:
        """Kick off the action; False when another one is still running."""
        if not self.lgsm.available(): raise ApiError(400, '未配置 LinuxGSM 脚本')
        if action not in ACTIONS: raise ApiError(400, 'bad action')
        if self.state['running']: return False
        self.state['running'] = action
        self.audit.add(actor, 'server.' + action)
        def work():
            try:
                self.state['last'] = f'{time.strftime("%H:%M:%S")} {action}: ' + self.lgsm.run(action)
            except Exception as e:
                self.state['last'] = f'{action} 失败: {e}'
            finally:
                self.state['running'] = None
        threading.Thread(target=work, daemon=True).start()
        return True
