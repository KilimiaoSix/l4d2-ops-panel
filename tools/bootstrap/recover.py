#!/usr/bin/env python3
"""Root-owned recovery wrapper; application modules run only as the service user."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat

from install import BASE, CODE, RECORD, UNIT, UNIT_NAME, USER, as_user, run


def main():
    if os.geteuid() != 0: raise SystemExit('请使用 sudo l4d2panel-recover')
    with open('/run/l4d2panel-bootstrap.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        info = RECORD.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise SystemExit('安装归属记录不可用')
        data = json.loads(RECORD.read_text())
        release = Path(data['release'])
        if (data.get('schema') != 1 or data.get('user') != USER or release.parent != CODE
                or release.is_symlink() or data.get('pending') or UNIT.is_symlink()
                or hashlib.sha256(UNIT.read_bytes()).hexdigest() != data['unit_sha256']):
            raise SystemExit('安装状态或服务配置发生变化；请先检查安装记录')
        run(['systemctl', 'stop', UNIT_NAME])
        python = release / 'venv/bin/python'
        env = dict(os.environ, PYTHONPATH=str(release / 'panel'))
        try:
            as_user([python, BASE / 'panel.py', '--config', BASE / 'panel.json', '--restore-config'], env=env)
            as_user([python, BASE / 'panel.py', '--config', BASE / 'panel.json', '--check-config'], env=env)
        finally:
            run(['systemctl', 'reset-failed', UNIT_NAME], check=False)
            run(['systemctl', 'start', UNIT_NAME], check=False)
        print('已恢复面板配置并请求启动；账号和游戏数据保留。检查 sudo systemctl status l4d2panel。')


if __name__ == '__main__': main()
