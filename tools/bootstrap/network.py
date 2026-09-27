#!/usr/bin/env python3
"""Narrow, root-owned port helper. Never enables/disables a firewall or touches SSH."""
import argparse
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import shutil
import stat

from install import RECORD, STATE, USER, atomic, run


def port(value):
    if not value.isascii() or not value.isdecimal() or not 1 <= int(value) <= 65535:
        raise argparse.ArgumentTypeError('端口必须是 1–65535 的整数')
    return int(value)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--panel-port', type=port)
    parser.add_argument('--game-port', type=port)
    args = parser.parse_args()
    if os.geteuid() != 0: raise SystemExit('请使用 sudo l4d2panel-network')
    info = RECORD.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise SystemExit('安装归属记录不可用')
    owner = json.loads(RECORD.read_text())
    if owner.get('schema') != 1 or owner.get('user') != USER: raise SystemExit('没有本工具管理的安装')
    with open('/run/l4d2panel-network.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        file = STATE / 'network.json'
        if file.is_symlink(): raise SystemExit('拒绝链接的网络配置')
        values = json.loads(file.read_text()) if file.exists() else {'panel': 8443, 'game': 27015}
        values = {'panel': args.panel_port or port(str(values['panel'])), 'game': args.game_port or port(str(values['game']))}
        atomic(file, (json.dumps(values) + '\n').encode())
        ufw_active = False
        if shutil.which('ufw'):
            status = run(['ufw', 'status'], capture=True, env=dict(os.environ, LC_ALL='C')).stdout
            ufw_active = status.startswith('Status: active')
        if ufw_active:
            for number, protocol in ((values['panel'], 'tcp'), (values['game'], 'tcp'), (values['game'], 'udp')):
                run(['ufw', 'allow', str(number) + '/' + protocol, 'comment', 'l4d2panel-managed'])
        else: print('UFW 未启用；保持原有防火墙状态，不修改 SSH。')
        # Docker DNAT bypasses normal UFW INPUT rules. Only add a tagged allow
        # for this host's original destination and the selected game port.
        for family, executable in (('-4', 'iptables'), ('-6', 'ip6tables')):
            if not shutil.which(executable): continue
            if run([executable, '-w', '5', '-S', 'DOCKER-USER'], capture=True, check=False).returncode: continue
            addresses = json.loads(run(['ip', '-json', family, 'address', 'show', 'scope', 'global'], capture=True).stdout)
            hosts = {str(ipaddress.ip_address(info['local'])) for link in addresses for info in link.get('addr_info', [])}
            for host in sorted(hosts):
                for protocol in ('tcp', 'udp'):
                    rule = ['-p', protocol, '-m', 'conntrack', '--ctdir', 'ORIGINAL', '--ctorigdst', host,
                        '--ctorigdstport', str(values['game']), '-m', 'comment', '--comment', 'l4d2panel-managed', '-j', 'ACCEPT']
                    if run([executable, '-w', '5', '-C', 'DOCKER-USER', *rule], capture=True, check=False).returncode:
                        run([executable, '-w', '5', '-I', 'DOCKER-USER', '1', *rule])
        print(f'本机规则检查完成：面板 {values["panel"]}/TCP，游戏 {values["game"]}/TCP+UDP。')
        print('云安全组和路由器仍需单独配置；自定义 nftables/firewalld 规则需人工核对。公网 UDP 与真实客户端连接尚未验证。')


if __name__ == '__main__': main()
