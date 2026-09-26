"""Exact-target panel JSON edits, validation, private backups and revision-safe recovery.

Settings keeps the legacy permissive loader. New edits and --check-config use this stricter boundary.
No account, service or game-directory side effects happen here.
"""
import hashlib
import ipaddress
import json
import os
import re
import socket
import ssl
import tempfile
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from ..settings import Paths, Settings
from .join_address import endpoint

LIVE_FIELDS = frozenset({'panel_title', 'display_host', 'max_upload_mb', 'steam_api_key'})
RESTART_FIELDS = frozenset({'port', 'bind', 'tls', 'cert', 'key', 'session_days', 'rcon_host', 'rcon_port',
                           'rcon_password', 'lgsm_script', 'console_log', 'perf_csv', 'depotdownloader'})
LOCATION_FIELDS = frozenset({'game_dir', 'install_dir'})
WRITABLE_FIELDS = LIVE_FIELDS | RESTART_FIELDS | LOCATION_FIELDS
SECRET_FIELDS = frozenset({'password', 'rcon_password', 'steam_api_key'})


class ConfigError(ValueError):
    pass


class ConfigConflict(ConfigError):
    pass


def revision(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def decode(data: bytes) -> dict:
    try:
        raw = json.loads(data)
    except (ValueError, UnicodeError):
        raise ConfigError('配置不是有效的 JSON') from None
    if not isinstance(raw, dict): raise ConfigError('配置必须是 JSON 对象')
    return raw


def validate(raw: dict, base: Path, *, unknown=False, current=None, check_port=False) -> Settings:
    if unknown and set(raw) - Settings.model_fields.keys():
        raise ConfigError('配置包含未知字段: ' + ', '.join(sorted(set(raw) - Settings.model_fields.keys())))
    try:
        s = Settings.model_validate(raw, strict=True)
    except ValidationError as exc:
        # Never echo a Pydantic input value: it may be a password or API key.
        fields = ', '.join('.'.join(str(v) for v in e['loc']) for e in exc.errors())
        raise ConfigError('配置字段类型无效: ' + fields) from None
    for key, lo, hi in [('port', 1, 65535), ('rcon_port', 1, 65535), ('session_days', 1, 365),
                        ('max_upload_mb', 1, 102400), ('workshop_connections', 1, 32), ('workshop_retries', 0, 100)]:
        if not lo <= getattr(s, key) <= hi: raise ConfigError(f'{key} 必须在 {lo}–{hi} 之间')
    for key in WRITABLE_FIELDS:
        value = getattr(s, key)
        if isinstance(value, str) and (len(value) > 4096 or any(ord(c) < 32 or ord(c) == 127 for c in value)):
            raise ConfigError(f'{key} 不能包含控制字符或过长内容')
    if not s.panel_title.strip() or len(s.panel_title) > 100: raise ConfigError('panel_title 必须为 1–100 个字符')
    if not s.game_dir.strip() or not s.install_dir.strip(): raise ConfigError('游戏和安装目录不能为空')
    try:
        address = ipaddress.ip_address(s.bind)
    except ValueError:
        raise ConfigError('bind 必须是有效的监听 IP 地址') from None
    if s.display_host:
        try: endpoint(s.display_host, s.rcon_port)
        except ValueError:
            raise ConfigError('display_host 应为域名或 IP，可带端口，不含协议和路径') from None
    paths = Paths.from_settings(s, base)
    if s.tls:
        if not s.cert or not s.key or paths.cert == paths.key: raise ConfigError('TLS 需要分别指定证书和私钥')
        try:
            ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).load_cert_chain(str(paths.cert), str(paths.key))
        except (OSError, ssl.SSLError):
            raise ConfigError('TLS 证书或私钥不可读、格式无效或不匹配') from None
    if check_port:
        family = socket.AF_INET6 if address.version == 6 else socket.AF_INET
        # A new bind on the existing port would collide with our own live listener.
        # Check the address using port 0 in that case, and the real port otherwise.
        port = 0 if current and s.port == current.port else s.port
        try:
            with socket.socket(family, socket.SOCK_STREAM) as probe: probe.bind((s.bind, port))
        except OSError:
            raise ConfigError('监听地址不可用或端口已被占用') from None
    return s


@dataclass
class ConfigSnapshot:
    raw: dict
    data: bytes
    revision: str


@dataclass
class ConfigSave:
    snapshot: ConfigSnapshot
    changed: list
    backup: str | None


class PanelConfigFile:
    def __init__(self, path: Path, base: Path):
        self.path, self.base = Path(path).resolve(), Path(base).resolve()
        self.backups = self.base / 'config_backups' / 'panel'
        self.prefix = revision(str(self.path).encode())
        self.lock = threading.RLock()

    def read(self) -> ConfigSnapshot:
        try: data = self.path.read_bytes()
        except OSError: raise ConfigError('无法读取启动时指定的面板配置') from None
        return ConfigSnapshot(decode(data), data, revision(data))

    @contextmanager
    def exclusive(self):
        with self.lock:
            # Atomic rename alone cannot serialize separate panel/recovery processes.
            # Linux is the supported deployment platform; the in-process lock also works on Windows.
            lock_path = self.path.parent / ('.' + self.path.name + '.lock')
            fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT, 0o600)
            try:
                if os.name == 'posix':
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_EX)
                yield
            finally:
                os.close(fd)

    @staticmethod
    def atomic_write(path: Path, data: bytes):
        fd, tmp = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
        try:
            with os.fdopen(fd, 'wb') as out:
                out.write(data); out.flush(); os.fsync(out.fileno())
            os.chmod(tmp, 0o600)
            os.replace(tmp, path)
            if os.name == 'posix':
                dfd = os.open(path.parent, os.O_RDONLY)
                try: os.fsync(dfd)
                finally: os.close(dfd)
        finally:
            Path(tmp).unlink(missing_ok=True)

    def _backup(self, data: bytes) -> str:
        self.backups.mkdir(parents=True, exist_ok=True, mode=0o700)
        name = self.prefix + '-' + uuid.uuid4().hex + '.json'
        with open(os.open(self.backups / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as out:
            out.write(data); out.flush(); os.fsync(out.fileno())
        return name

    def prepare(self, expected: str, updates: dict, current: Settings):
        if set(updates) - WRITABLE_FIELDS: raise ConfigError('包含不允许修改的配置字段')
        old = self.read()
        if old.revision != expected: raise ConfigConflict('配置已被修改，请刷新后重试')
        candidate = {**old.raw, **updates}
        before = Settings.model_validate(old.raw)
        changed = sorted(k for k, v in updates.items() if getattr(before, k) != v or type(getattr(before, k)) is not type(v))
        settings = validate(candidate, self.base, current=current, check_port=bool(set(changed) & {'port', 'bind'}))
        return old, candidate, changed, settings

    def save(self, expected: str, updates: dict, current: Settings, before_commit=None) -> ConfigSave:
        with self.exclusive():
            old, candidate, changed, _ = self.prepare(expected, updates, current)
            if not changed: return ConfigSave(old, [], None)
            data = (json.dumps(candidate, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
            backup = self._backup(old.data)
            if before_commit: before_commit(backup, old.revision, revision(data))
            # Detect external editors that do not honor our lock during validation/backup.
            if self.read().revision != expected: raise ConfigConflict('配置在保存期间被其他程序修改')
            self.atomic_write(self.path, data)
            return ConfigSave(ConfigSnapshot(candidate, data, revision(data)), changed, backup)

    def backup_bytes(self, name: str) -> bytes:
        if not re.fullmatch(re.escape(self.prefix) + r'-[a-f0-9]{32}\.json', name):
            raise ConfigError('备份不属于此配置文件')
        path = self.backups / name
        if path.is_symlink(): raise ConfigError('备份不能是符号链接')
        try: return path.read_bytes()
        except OSError: raise ConfigError('无法读取配置备份') from None

    def restore(self, name: str, expected: str) -> ConfigSave:
        with self.exclusive():
            old = self.read()
            if old.revision != expected: raise ConfigConflict('配置已被外部修改，拒绝覆盖恢复')
            data = self.backup_bytes(name)
            raw = decode(data)
            validate(raw, self.base)
            if data == old.data: return ConfigSave(old, [], None)
            backup = self._backup(old.data)
            if self.read().revision != expected: raise ConfigConflict('恢复期间配置被其他程序修改')
            self.atomic_write(self.path, data)
            return ConfigSave(ConfigSnapshot(raw, data, revision(data)), ['restore'], backup)


def check_config(path: Path, base: Path):
    file = PanelConfigFile(path, base)
    return validate(file.read().raw, base, unknown=True)
