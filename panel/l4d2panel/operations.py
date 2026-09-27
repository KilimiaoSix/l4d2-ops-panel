"""One admission gate for requests, daemon jobs, game operations and a pending panel restart."""
import threading
from contextlib import contextmanager

from .errors import ApiError


class OperationGate:
    def __init__(self):
        self.lock = threading.Lock()
        self.active = 0
        self.pending = False

    def enter(self):
        with self.lock:
            if self.pending: raise ApiError(409, '面板正在重启，请稍后重试')
            self.active += 1

    def leave(self):
        with self.lock:
            self.active -= 1

    @contextmanager
    def activity(self):
        self.enter()
        try: yield
        finally: self.leave()

    def begin_restart(self):
        with self.lock:
            if self.pending or self.active: raise ApiError(409, '后台任务或写入正在进行，请完成后再重启面板')
            self.pending = True

    def cancel_restart(self):
        with self.lock: self.pending = False
