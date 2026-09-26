"""Interactive service-user install. Existing configuration and service are preserved."""
import getpass
import ipaddress
import json
import os
from pathlib import Path
import pwd
import re
import shlex
import shutil
import ssl
import subprocess
import tempfile

from .integrations.panel_config import validate
from .integrations.join_address import endpoint


def ask(label, default='', optional=False):
    hint = '；输入 - 清空' if optional else ''
    value = input(f'{label} [{default}]{hint}: ').strip()
    if value == '-' and optional: return ''
    return value or default


def run(command, **kwargs):
    return subprocess.run([str(x) for x in command], check=True, **kwargs)


def create_exclusive(path, data, mode=0o600):
    with open(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode), 'wb') as stream:
        stream.write(data); stream.flush(); os.fsync(stream.fileno())


def certificate(base, config):
    cert, key = base / config['cert'], base / config['key']
    if any(p.is_symlink() for p in (cert, key)): raise ValueError('证书和私钥不能为符号链接')
    if cert.exists() or key.exists():
        ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).load_cert_chain(cert, key)
        return
    host = endpoint(config['display_host'], config['rcon_port'])[0].rsplit(':', 1)[0].strip('[]') if config['display_host'] else 'localhost'
    try: ipaddress.ip_address(host); san = 'IP:' + host
    except ValueError: san = 'DNS:' + host
    with tempfile.TemporaryDirectory(prefix='.certificate-', dir=base) as directory:
        staged = Path(directory)
        run(['openssl', 'req', '-x509', '-newkey', 'rsa:3072', '-nodes', '-keyout', staged / 'key.pem',
             '-out', staged / 'cert.pem', '-days', '825', '-subj', '/CN=' + host, '-addext',
             'subjectAltName=' + san + ',IP:127.0.0.1,IP:::1,DNS:localhost'], capture_output=True)
        create_exclusive(key, (staged / 'key.pem').read_bytes())
        create_exclusive(cert, (staged / 'cert.pem').read_bytes())


def configuration(base):
    path = base / 'panel.json'
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file(): raise ValueError('panel.json 必须是普通文件')
        config = json.loads(path.read_text(encoding='utf-8'))
        validate(config, base)
        print('已有 panel.json 已验证并原样保留；账号、数据库和游戏文件不重建。')
        return config, False
    home = Path.home()
    print('回车接受默认值；可选字段输入 - 表示清空。密码输入不会回显。')
    config = {'game_dir': ask('游戏目录（…/left4dead2）', str(home / 'serverfiles/left4dead2')),
        'lgsm_script': ask('LinuxGSM 实例脚本', str(home / 'l4d2server'), True),
        'rcon_host': ask('RCON/查询地址（服务器网卡 IP）', '127.0.0.1'),
        'rcon_port': int(ask('RCON 端口', '27015')),
        'console_log': ask('控制台日志', str(home / 'log/console/l4d2server-console.log'), True),
        'perf_csv': ask('性能采样 CSV', str(home / 'log/perf-samples.csv'), True),
        'depotdownloader': ask('DepotDownloader 路径', str(home / 'tools/depotdownloader/DepotDownloader'), True),
        'display_host': ask('对外显示的域名或 IP（可带游戏端口）', '', True),
        'bootstrap_user': ask('面板管理员账号', 'admin'),
        'password': getpass.getpass('面板管理员密码（留空则首次访问时设置）: '),
        'rcon_password': '', 'cert': 'cert.pem', 'key': 'key.pem', 'session_days': 7,
        'panel_title': 'L4D2 运维面板', 'max_upload_mb': 3072, 'protected_addons': ['admin_system.vpk']}
    mode = ask('监听方式：1 自带 HTTPS；2 仅本机 HTTP，交给反向代理', '1')
    if mode not in ('1', '2'): raise ValueError('监听方式必须为 1 或 2')
    config.update(tls=mode == '1', bind='0.0.0.0' if mode == '1' else '127.0.0.1',
                  port=int(ask('面板端口', '8443' if mode == '1' else '8080')))
    validate({**config, 'tls': False}, base, unknown=True, check_port=True)
    if config['tls']: certificate(base, config)
    validate(config, base, unknown=True)
    create_exclusive(path, (json.dumps(config, ensure_ascii=False, indent=2) + '\n').encode())
    return config, True


def unit_quote(value, *, command=False):
    value = str(value)
    if any(ord(c) < 32 or ord(c) == 127 for c in value): raise ValueError('服务路径包含控制字符')
    value = value.replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%')
    return '"' + (value.replace('$', '$$') if command else value) + '"'


def install_service(base):
    manual = shlex.join([str(base / 'venv/bin/python'), str(base / 'panel.py'), '--config', str(base / 'panel.json')])
    if not shutil.which('systemctl') or not shutil.which('sudo') or subprocess.run(['sudo', '-n', 'true'], capture_output=True).returncode:
        print('未配置免交互 sudo，手动启动：' + manual); return
    state = run(['systemctl', 'show', 'l4d2panel.service', '-p', 'LoadState', '--value'], capture_output=True, text=True).stdout.strip()
    if state != 'not-found':
        print('已有 l4d2panel.service 保持原样；请核对其运行用户和路径后按需重启。')
        print('当前目录的手动启动命令：' + manual); return
    user = pwd.getpwuid(os.getuid()).pw_name
    if not re.fullmatch(r'[a-z_][a-z0-9_-]*[$]?', user): raise ValueError('服务用户名格式不支持')
    unit = f'''[Unit]
Description=L4D2 Ops Panel
After=network.target

[Service]
User={user}
WorkingDirectory={unit_quote(base)}
ExecStart={unit_quote(base / 'venv/bin/python', command=True)} {unit_quote(base / 'panel.py', command=True)} --config {unit_quote(base / 'panel.json', command=True)}
Restart=always
RestartSec=3
RestartPreventExitStatus=78
TimeoutStopSec=30
UMask=0077

[Install]
WantedBy=multi-user.target
'''
    # Exclusive creation avoids overwriting a unit created since the state check.
    run(['sudo', '-n', 'python3', '-c',
         'import os,sys; p="/etc/systemd/system/l4d2panel.service"; '
         'f=os.fdopen(os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o644),"wb"); f.write(sys.stdin.buffer.read()); f.close()'], input=unit.encode())
    run(['sudo', '-n', 'systemctl', 'daemon-reload'])
    run(['sudo', '-n', 'systemctl', 'enable', '--now', 'l4d2panel.service'])
    print('systemd 服务已启动；请通过页面确认面板就绪。')


def main():
    if os.geteuid() == 0: raise SystemExit('请以运行游戏的普通用户执行 install.sh')
    base = Path.cwd().resolve()
    try:
        config, created = configuration(base)
        if not (base / 'l4d2panel/static/index.html').is_file(): print('前端尚未构建；请使用完整发布包或先执行 npm run build。')
        install_service(base)
        print(f'面板监听 {config.get("bind", "127.0.0.1")}:{config.get("port", 8080)}，TLS={config.get("tls", False)}。')
        if config.get('tls'):
            result = run(['openssl', 'x509', '-in', base / config.get('cert', 'cert.pem'), '-noout', '-fingerprint', '-sha256'], capture_output=True, text=True)
            print(result.stdout.strip()); print('请核对证书指纹，或配置受信任证书；云安全组需放行面板 TCP 端口。')
        if created: print('初始账号：' + config['bootstrap_user'] + ('；使用刚输入的密码登录。' if config['password'] else '；首次访问时设置密码。'))
    except (ValueError, OSError, subprocess.SubprocessError) as error: raise SystemExit('安装未完成：' + str(error)) from None


if __name__ == '__main__': main()
