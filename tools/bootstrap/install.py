#!/usr/bin/env python3
"""Root-only installation of an already authenticated release, with code rollback.

Application Python is always executed as the dedicated service user. Mutable
panel data stays at a stable base while each code/venv release has its own path.
"""
import argparse
import base64
import hashlib
import http.client
import ipaddress
import json
import os
from pathlib import Path
import pwd
import re
import secrets
import shutil
import socket
import ssl
import stat
import subprocess
import time
import urllib.request
import urllib.error
import uuid

USER = 'l4d2panel'
HOME = Path('/home/l4d2panel')
BASE = HOME / 'panel'
CODE = Path('/opt/l4d2panel')
STATE = Path('/var/lib/l4d2panel-bootstrap')
RECORD = STATE / 'owner.json'
UNIT = Path('/etc/systemd/system/l4d2panel.service')
UNIT_NAME = 'l4d2panel.service'
HELPERS = Path('/usr/local/lib/l4d2panel-bootstrap')
NETWORK_UNIT = Path('/etc/systemd/system/l4d2panel-network.service')
APT_KEY = Path('/etc/apt/keyrings/l4d2panel-docker.asc')
APT_SOURCE = Path('/etc/apt/sources.list.d/l4d2panel-docker.sources')
DOCKER_KEY_SHA = '1500c1f56fa9e26b9b8f42452a553675796ade0807cdce11975eb98170b3a570'
DOCKER_SOURCES = ('https://download.docker.com/linux/ubuntu',
                  'https://mirrors.tuna.tsinghua.edu.cn/docker-ce/linux/ubuntu')


def run(args, *, capture=False, timeout=600, check=True, **kwargs):
    return subprocess.run([str(x) for x in args], check=check, timeout=timeout,
                          capture_output=capture, text=True, **kwargs)


def as_user(args, **kwargs):
    supplied = kwargs.pop('env', {})
    environment = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C.UTF-8', 'HOME': str(HOME)}
    if 'PYTHONPATH' in supplied: environment['PYTHONPATH'] = supplied['PYTHONPATH']
    return run(['runuser', '-u', USER, '--', *args], env=environment, **kwargs)


def atomic(path, data, mode=0o600, owner=None):
    path = Path(path)
    if path.is_symlink(): raise ValueError('Refusing linked file: ' + str(path))
    temporary = path.with_name('.' + path.name + '.' + uuid.uuid4().hex)
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, mode)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, 'wb') as output:
            output.write(data); output.flush(); os.fsync(output.fileno())
        if owner: os.chown(temporary, *owner)
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_DIRECTORY)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally: temporary.unlink(missing_ok=True)


def record(data): atomic(RECORD, (json.dumps(data, indent=2) + '\n').encode())


def recover_pending(data):
    pending = data.get('pending')
    if not pending: return data
    current = hashlib.sha256(UNIT.read_bytes()).hexdigest() if UNIT.exists() and not UNIT.is_symlink() else None
    previous = pending['record']
    if current not in (previous['unit_sha256'], pending['next_unit_sha256']):
        raise ValueError('Interrupted update conflicts with an external service-unit edit')
    run(['systemctl', 'stop', UNIT_NAME], check=False)
    if pending['unit'] is not None:
        atomic(UNIT, base64.b64decode(pending['unit'], validate=True), 0o644)
        if pending['launcher'] is not None:
            atomic(BASE / 'panel.py', base64.b64decode(pending['launcher'], validate=True), 0o644,
                   (previous['uid'], previous['gid']))
        record(previous)
        run(['systemctl', 'daemon-reload']); run(['systemctl', 'start', UNIT_NAME], check=False)
        print('已恢复被中断更新之前的代码入口；继续本次安装。')
        return previous
    # No previous install: retain the owned candidate as retryable, without
    # recording success or ever removing mutable files.
    data['unit_sha256'] = current
    data.pop('pending', None); record(data)
    return data


def real_directory(path):
    for part in (path, *path.parents):
        if part.is_symlink(): raise ValueError('Refusing linked directory: ' + str(part))
        if part.exists() and not part.is_dir(): raise ValueError('Expected directory: ' + str(part))


def platform_guard():
    if os.geteuid() != 0 or os.uname().machine != 'x86_64': raise ValueError('Requires root on x86_64')
    values = dict(line.split('=', 1) for line in Path('/etc/os-release').read_text().splitlines() if '=' in line)
    if values.get('ID', '').strip('"') != 'ubuntu' or values.get('VERSION_ID', '').strip('"') not in ('22.04', '24.04'):
        raise ValueError('Only Ubuntu 22.04/24.04 is supported')
    if not Path('/run/systemd/system').is_dir(): raise ValueError('Requires a running systemd system')
    return values['VERSION_CODENAME'].strip('"')


def ownership():
    for path in (HOME, BASE, CODE, STATE, HELPERS): real_directory(path)
    if RECORD.exists():
        info = RECORD.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError('Bootstrap ownership record is not protected')
        data = json.loads(RECORD.read_text())
        if data.get('schema') != 1 or data.get('home') != str(HOME) or data.get('user') != USER:
            raise ValueError('Foreign bootstrap ownership record')
        data = recover_pending(data)
    else:
        try: pwd.getpwnam(USER)
        except KeyError: pass
        else: raise ValueError('Dedicated username already belongs to an unmanaged installation')
        active_unit = run(['systemctl', 'show', UNIT_NAME, '-p', 'LoadState', '--value'], capture=True).stdout.strip()
        reserved = (HOME, CODE, UNIT, STATE, HELPERS, NETWORK_UNIT, APT_KEY, APT_SOURCE,
                    Path('/usr/local/bin/l4d2panel-recover'), Path('/usr/local/bin/l4d2panel-network'))
        if any(path.exists() or path.is_symlink() for path in reserved) or active_unit != 'not-found':
            raise ValueError('Existing user, service or directory is not owned by this installer')
        STATE.mkdir(mode=0o700)
        data = {'schema': 1, 'user': USER, 'home': str(HOME), 'identity': uuid.uuid4().hex,
                'version': None, 'uid': None, 'gid': None, 'unit_sha256': None, 'credentials_reported': False}
        record(data)
    try: account = pwd.getpwnam(USER)
    except KeyError:
        if data['uid'] is not None: raise ValueError('Managed account is missing; refusing to recreate its UID')
        run(['useradd', '--system', '--user-group', '--create-home', '--home-dir', HOME, '--shell', '/usr/sbin/nologin',
             '--comment', 'L4D2 Panel ' + data['identity'], USER])
        account = pwd.getpwnam(USER)
    if (account.pw_dir != str(HOME) or account.pw_gecos != 'L4D2 Panel ' + data['identity']
            or data['uid'] is not None and (account.pw_uid, account.pw_gid) != (data['uid'], data['gid'])):
        raise ValueError('Dedicated service account ownership changed')
    if UNIT.exists():
        if UNIT.is_symlink() or hashlib.sha256(UNIT.read_bytes()).hexdigest() != data['unit_sha256']:
            raise ValueError('Service unit was externally changed; refusing to replace it')
    elif data['unit_sha256'] is not None: raise ValueError('Managed unit is missing')
    data.update(uid=account.pw_uid, gid=account.pw_gid); record(data)
    HOME.chmod(0o750)
    BASE.mkdir(mode=0o750, exist_ok=True); os.chown(BASE, account.pw_uid, account.pw_gid)
    CODE.mkdir(mode=0o755, exist_ok=True)
    CODE.chmod(0o755)
    return data


def docker_ready():
    if not shutil.which('docker'): return False
    return all(run(command, capture=True, check=False, timeout=30).returncode == 0 for command in
               (['docker', 'version'], ['docker', 'compose', 'version']))


def install_docker(codename):
    if docker_ready(): return
    conflicts = []
    for package in ('docker.io', 'docker-compose', 'docker-compose-v2', 'podman-docker', 'containerd', 'runc'):
        result = run(['dpkg-query', '-W', '-f=${Status}', package], capture=True, check=False)
        if result.returncode == 0 and 'install ok installed' in result.stdout: conflicts.append(package)
    if conflicts: raise ValueError('Existing Docker stack needs operator repair; no packages removed: ' + ', '.join(conflicts))
    key = None
    for base in DOCKER_SOURCES:
        try:
            with urllib.request.urlopen(base + '/gpg', timeout=30) as response: key = response.read(65537)
        except (urllib.error.URLError, TimeoutError, ConnectionError): continue
        if hashlib.sha256(key).hexdigest() != DOCKER_KEY_SHA:
            raise ValueError('Docker repository key changed; review required')
        break
    if key is None: raise ValueError('Official and mirror Docker key downloads failed; retry after restoring network access')
    Path('/etc/apt/keyrings').mkdir(exist_ok=True, mode=0o755)
    Path('/etc/apt/keyrings').chmod(0o755)
    atomic(APT_KEY, key, 0o644)
    for index, base in enumerate(DOCKER_SOURCES):
        source = ('Types: deb\nURIs: ' + base + '\nSuites: ' + codename +
                  '\nComponents: stable\nArchitectures: amd64\nSigned-By: /etc/apt/keyrings/l4d2panel-docker.asc\n')
        atomic(APT_SOURCE, source.encode(), 0o644)
        try:
            # APT normally exits zero after some failed index downloads. Require
            # every index to succeed, and retain APT's signature/package checks.
            run(['apt-get', '-o', 'Acquire::https::Timeout=20', '-o', 'Acquire::Retries=1',
                 '-o', 'APT::Update::Error-Mode=any', 'update'])
            run(['apt-get', '-o', 'Acquire::https::Timeout=20', '-o', 'Acquire::Retries=1',
                 'install', '--yes', '--no-upgrade', 'docker-ce', 'docker-ce-cli', 'containerd.io', 'docker-compose-plugin'])
            break
        except subprocess.SubprocessError:
            if index == len(DOCKER_SOURCES) - 1: raise
            print('Docker 官方源不可达，切换国内镜像；继续使用固定 Docker 公钥与 APT 签名校验。', flush=True)
    run(['systemctl', 'enable', '--now', 'docker'])
    if not docker_ready(): raise ValueError('Docker or Compose failed its live check')


def host_name(value):
    if not value or len(value) > 253 or any(c.isspace() for c in value): raise ValueError('Invalid public hostname')
    raw = value[1:-1] if value.startswith('[') and value.endswith(']') else value
    if '%' in raw: raise ValueError('IPv6 scope IDs cannot be used for a public certificate')
    try: return str(ipaddress.ip_address(raw))
    except ValueError:
        if re.fullmatch(r'[0-9.]+', value): raise ValueError('Invalid public IPv4 address') from None
        value = value.encode('idna').decode('ascii').lower()
        if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?', value) or '..' in value:
            raise ValueError('Public host must be an IP or DNS name without a port')
        if any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', part) for part in value.split('.')):
            raise ValueError('Invalid public DNS name')
        return value


def discover_host():
    try:
        value = urllib.request.urlopen('https://api.ipify.org', timeout=10).read(128).decode().strip()
        return str(ipaddress.ip_address(value))
    except Exception:
        route = json.loads(run(['ip', '-json', 'route', 'get', '1.1.1.1'], capture=True).stdout)
        value = str(ipaddress.ip_address(route[0]['prefsrc']))
        print('公网地址自动查询失败，暂用本机地址；请在面板中核实朋友连接地址。')
        return value


def new_config(data, host):
    path = BASE / 'panel.json'
    if path.exists():
        if path.is_symlink() or not path.is_file(): raise ValueError('Refusing non-regular panel configuration')
        config = json.loads(path.read_text())
        if data.get('initializing_cert'): initialize_certificate(data)
        return config, False
    if data['version'] is not None: raise ValueError('Managed panel configuration is missing')
    host = host_name(host or discover_host())
    with socket.socket(socket.AF_INET6 if ':' in host else socket.AF_INET) as probe:
        probe.bind(('::' if ':' in host else '0.0.0.0', 8443))
    cert, key = BASE / 'cert.pem', BASE / 'key.pem'
    if cert.exists() or key.exists(): raise ValueError('Preexisting certificate without managed configuration; refusing overwrite')
    data.update(initializing_cert=True, panel_host=host); record(data)
    config = {'password': secrets.token_urlsafe(24), 'bootstrap_user': 'admin', 'port': 8443,
        'bind': '::' if ':' in host else '0.0.0.0', 'tls': True, 'cert': str(cert), 'key': str(key),
        'session_days': 7, 'db': str(BASE / 'panel.db'), 'rcon_host': '127.0.0.1', 'rcon_port': 27015,
        'rcon_password': '', 'game_dir': str(HOME / 'game'), 'server_backend': 'docker', 'docker_project': 'l4d2-panel',
        'install_dir': str(BASE / 'docker'), 'lgsm_script': '', 'console_log': '', 'perf_csv': '', 'depotdownloader': '',
        'panel_title': 'L4D2 运维面板', 'display_host': ('[' + host + ']' if ':' in host else host) + ':27015'}
    atomic(path, (json.dumps(config, ensure_ascii=False, indent=2) + '\n').encode(), owner=(data['uid'], data['gid']))
    initialize_certificate(data)
    return config, True


def initialize_certificate(data):
    import tempfile
    cert, key = BASE / 'cert.pem', BASE / 'key.pem'
    try:
        ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).load_cert_chain(cert, key)
    except (OSError, ssl.SSLError):
        host = host_name(data['panel_host'])
        try: ipaddress.ip_address(host); san = 'IP:' + host
        except ValueError: san = 'DNS:' + host
        with tempfile.TemporaryDirectory(prefix='certificate-', dir=STATE) as directory:
            staged_cert, staged_key = Path(directory) / 'cert.pem', Path(directory) / 'key.pem'
            run(['openssl', 'req', '-x509', '-newkey', 'rsa:3072', '-nodes', '-keyout', staged_key,
                 '-out', staged_cert, '-days', '825', '-subj', '/CN=' + host, '-addext',
                 'subjectAltName=' + san + ',IP:127.0.0.1,IP:::1,DNS:localhost'], capture=True)
            for staged, target in ((staged_cert, cert), (staged_key, key)):
                atomic(target, staged.read_bytes(), owner=(data['uid'], data['gid']))
    data['initializing_cert'] = False; record(data)


def unit_text(release):
    return f'''[Unit]
Description=L4D2 Ops Panel (managed bootstrap)
After=network-online.target docker.service
Wants=network-online.target docker.service

[Service]
Type=simple
User={USER}
Group={USER}
WorkingDirectory={BASE}
Environment=PYTHONPATH={release}/panel
Environment=HOME={HOME}
ExecStart={release}/venv/bin/python {BASE}/panel.py --config {BASE}/panel.json
Restart=always
RestartSec=3
RestartPreventExitStatus=78
TimeoutStopSec=30
UMask=0077
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
'''


def copy_application(source, release):
    shutil.copytree(source / 'panel', release / 'panel')
    # The verified staging tree is root-private (umask 077). copytree preserves
    # that mode, so explicitly make immutable code traversable by the service user.
    for path in (release / 'panel', *(release / 'panel').rglob('*')):
        if path.is_dir(): path.chmod(0o755)


def install_helpers(source, data, config):
    HELPERS.mkdir(mode=0o755, exist_ok=True)
    for name in ('install.py', 'recover.py', 'network.py'):
        atomic(HELPERS / name, (source / 'tools/bootstrap' / name).read_bytes(), 0o644)
    for name in ('recover', 'network'):
        script = '#!/bin/sh\nexec /usr/bin/python3 ' + str(HELPERS / (name + '.py')) + ' "$@"\n'
        atomic('/usr/local/bin/l4d2panel-' + name, script.encode(), 0o755)
    network_unit = '''[Unit]
Description=L4D2 Panel managed host port rules
After=docker.service network-online.target
Wants=docker.service network-online.target
PartOf=docker.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/l4d2panel-network
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target docker.service
'''
    atomic(NETWORK_UNIT, network_unit.encode(), 0o644)
    # Preserve an explicitly selected root-helper game port across panel updates.
    # Changing the game's published port is a separate operation from updating code.
    ports = ['/usr/local/bin/l4d2panel-network', '--panel-port', str(config['port'])]
    if not (STATE / 'network.json').exists(): ports += ['--game-port', str(config['rcon_port'])]
    run(ports)
    run(['systemctl', 'daemon-reload']); run(['systemctl', 'enable', '--now', 'l4d2panel-network.service'])
    return json.loads((STATE / 'network.json').read_text())


def health(config):
    bind = config.get('bind', '127.0.0.1')
    host = '::1' if bind == '::' else '127.0.0.1' if bind == '0.0.0.0' else bind
    if config.get('tls'):
        cert = Path(config['cert']); cert = cert if cert.is_absolute() else BASE / cert
        pem = cert.read_text(); first = pem[:pem.index('-----END CERTIFICATE-----') + len('-----END CERTIFICATE-----')]
        expected = hashlib.sha256(ssl.PEM_cert_to_DER_cert(first)).digest()
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT); context.check_hostname = False; context.verify_mode = ssl.CERT_NONE
        connection = http.client.HTTPSConnection(host, config['port'], timeout=3, context=context)
        connection.connect()
        # Local health traffic pins the exact configured leaf before any request.
        if hashlib.sha256(connection.sock.getpeercert(binary_form=True)).digest() != expected:
            connection.close(); raise ValueError('Local health certificate mismatch')
    else: connection = http.client.HTTPConnection(host, config['port'], timeout=3)
    try:
        connection.request('GET', '/api/health'); response = connection.getresponse()
        if response.status != 200: raise ValueError('Health response is not ready')
        return json.loads(response.read(65536))
    finally: connection.close()


def healthy(config, version, old_boot):
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        try:
            pid = int(run(['systemctl', 'show', UNIT_NAME, '-p', 'MainPID', '--value'], capture=True, timeout=5).stdout)
            value = health(config)
            if (pid > 0 and value['pid'] == pid and value['version'] == version and value['ready'] is True
                    and value['boot'] != old_boot and re.fullmatch(r'[a-f0-9]{32}', value['boot'])): return value
        except (OSError, ValueError, KeyError, subprocess.SubprocessError, http.client.HTTPException): pass
        time.sleep(0.5)
    raise ValueError('New version/process did not pass its 90-second startup check')


def install(args):
    codename = platform_guard()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}', args.version): raise ValueError('Invalid release version')
    source = args.release.resolve()
    if args.host: args.host = host_name(args.host)
    if (source / 'VERSION').read_text() != args.version + '\n': raise ValueError('Release version mismatch')
    if shutil.disk_usage('/opt').free < 1024 ** 3: raise ValueError('At least 1 GiB free disk is required before installing')
    data = ownership()
    os.environ['DEBIAN_FRONTEND'] = 'noninteractive'
    # Repair this installer's partial repository/key before a generic apt update;
    # otherwise a previous interrupted Docker setup can prevent its own retry.
    install_docker(codename)
    run(['apt-get', 'update'])
    run(['apt-get', 'install', '--yes', '--no-upgrade', 'python3', 'python3-venv', 'ca-certificates', 'openssl'])
    run(['usermod', '-aG', 'docker', USER])
    as_user(['docker', 'version'], capture=True); as_user(['docker', 'compose', 'version'], capture=True)
    if args.repair_docker and data['version']:
        print('Docker / Compose 已恢复，服务用户连接正常；现有面板和游戏数据保留。'); return
    config, created = new_config(data, args.host)
    release = CODE / (args.version + '-' + uuid.uuid4().hex[:12])
    release.mkdir(mode=0o755); os.chown(release, data['uid'], data['gid'])
    copy_application(source, release)
    as_user(['python3', '-m', 'venv', release / 'venv'])
    python = release / 'venv/bin/python'
    as_user([python, '-m', 'pip', 'install', '--disable-pip-version-check', '-r', release / 'panel/requirements.txt'])
    env = dict(os.environ, PYTHONPATH=str(release / 'panel'))
    check = ('from pathlib import Path; from l4d2panel.main import main; '
             f'main(["--config", {str(BASE / "panel.json")!r}, "--check-config"], base_dir=Path({str(BASE)!r}))')
    as_user([python, '-c', check], env=env)
    old_unit = UNIT.read_bytes() if UNIT.exists() else None
    old_launcher = (BASE / 'panel.py').read_bytes() if (BASE / 'panel.py').exists() else None
    try: old_boot = health(config)['boot']
    except Exception: old_boot = None
    old_record = dict(data)
    new_unit = unit_text(release).encode()
    data['pending'] = {'record': old_record,
        'unit': base64.b64encode(old_unit).decode() if old_unit is not None else None,
        'launcher': base64.b64encode(old_launcher).decode() if old_launcher is not None else None,
        'next_unit_sha256': hashlib.sha256(new_unit).hexdigest()}
    record(data)
    # Stop only the panel. The existing Docker game and all mutable directories stay in place.
    if old_unit: run(['systemctl', 'stop', UNIT_NAME])
    try:
        seed = ('from pathlib import Path; from l4d2panel.settings import load_settings; '
                'from l4d2panel.context import build_context; '
                f'build_context(load_settings({str(BASE / "panel.json")!r}), Path({str(BASE)!r}), Path({str(BASE / "panel.json")!r}))')
        as_user([python, '-c', seed], env=env, capture=True)
        atomic(BASE / 'panel.py', (source / 'panel/panel.py').read_bytes(), 0o644, (data['uid'], data['gid']))
        atomic(UNIT, new_unit, 0o644)
        data.update(unit_sha256=hashlib.sha256(new_unit).hexdigest(), candidate=str(release)); record(data)
        run(['systemctl', 'daemon-reload']); run(['systemctl', 'enable', UNIT_NAME]); run(['systemctl', 'restart', UNIT_NAME])
        result = healthy(config, args.version, old_boot)
        committed = {**data, 'version': args.version, 'release': str(release), 'candidate': None, 'boot': result['boot']}
        committed.pop('pending', None); record(committed); data = committed
    except BaseException:
        recover_pending(data)
        if old_unit:
            print('新版本启动失败；已恢复先前服务配置与代码路径，数据库和游戏数据保持原位。', flush=True)
        else:
            print('首次启动未完成，配置和安装记录已保留；修复原因后可重跑同一安装命令。', flush=True)
        raise
    network_ports = install_helpers(source, data, config)
    if not created and args.host and args.host != data.get('panel_host'):
        print('--host 仅用于首次安装；此次保留已有配置和证书。')
    host = data.get('panel_host') or config['display_host'].rsplit(':', 1)[0].strip('[]')
    if ':' in host: host = '[' + host + ']'
    print(f'面板版本 {args.version} 已由新进程启动。地址：{"https" if config.get("tls") else "http"}://{host}:{config["port"]}/')
    print(f'本机规则使用面板 {network_ports["panel"]}/TCP、游戏 {network_ports["game"]}/TCP+UDP；云安全组也需放行。公网连接尚未验证。')
    if config.get('tls'):
        cert_path = Path(config['cert']); cert_path = cert_path if cert_path.is_absolute() else BASE / cert_path
        print(run(['openssl', 'x509', '-in', cert_path, '-noout', '-fingerprint', '-sha256'], capture=True).stdout.strip())
        print('请核对上述证书指纹，或配置受信任证书。')
    print(f'恢复面板配置：sudo l4d2panel-recover；调整本机游戏端口：sudo l4d2panel-network --game-port {network_ports["game"]}')
    if not data['credentials_reported']:
        print('初始账号：' + config['bootstrap_user'] + '    初始密码：' + config['password'])
        data['credentials_reported'] = True; record(data)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--release', type=Path, required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--host', default='')
    parser.add_argument('--repair-docker', action='store_true')
    args = parser.parse_args()
    try: install(args)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        raise SystemExit('安装未完成：' + str(error)) from None


if __name__ == '__main__': main()
