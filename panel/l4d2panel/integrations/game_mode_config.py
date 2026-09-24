"""Persist direct server.cfg mode commands without interpreting exec files or plugins.

Only standalone mp_gamemode and sm_cvar mp_gamemode assignments are editable.
Ambiguous command syntax fails closed; unrelated bytes never need decoding.
"""
from dataclasses import dataclass, field
import os
from pathlib import Path
import re
import stat
import tempfile

from .sm_files import SERVER_CFG_LOCK
from ..game_modes import MODE_IDS



_MAX_BYTES = 1024 * 1024
_WORD = re.compile(rb'\bmp_gamemode\b', re.I)
_TOKENS = re.compile(rb'"(?:\\.|[^"\\])*"|;|[^\s;"]+')
_ASSIGNMENT = re.compile(
    rb'^[ \t]*(?P<prefix>sm_cvar[ \t]+)?(?P<command>mp_gamemode)[ \t]+'
    rb'(?P<value>"[A-Za-z0-9_]+"|[A-Za-z0-9_]+)[ \t\r\n]*$', re.I)


class ModeConfigError(Exception):
    """The config cannot be safely read, changed, or restored."""


@dataclass(frozen=True)
class _Snapshot:
    data: bytes
    identity: tuple
    permissions: int


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
            info.st_ctime_ns, info.st_mode)


def _contains_mode_command(code):
    tokens = _TOKENS.findall(code)
    for i, token in enumerate(tokens):
        if i and tokens[i - 1] != b';':
            continue
        if token.strip(b'"').lower() == b'sm_cvar' and i + 1 < len(tokens):
            token = tokens[i + 1]
        if token.strip(b'"').lower() == b'mp_gamemode':
            return True
    return False


def _assignments(data):
    """Return byte spans of direct assignments, retaining comments and formatting."""
    result = []
    offset = 0
    in_block = False
    for line in data.splitlines(keepends=True):
        visible = bytearray(line)
        quoted = False
        escaped = False
        i = 3 if offset == 0 and line.startswith(b'\xef\xbb\xbf') else 0
        visible[:i] = b' ' * i
        while i < len(line):
            if in_block:
                end = line.find(b'*/', i)
                stop = len(line) if end < 0 else end + 2
                if _WORD.search(line[i:stop]):
                    raise ModeConfigError('server.cfg 含块注释中的 mp_gamemode，无法安全修改')
                visible[i:stop] = b' ' * (stop - i)
                i = stop
                in_block = end < 0
                continue
            if not quoted and line[i:i + 2] == b'//':
                visible[i:] = b' ' * (len(line) - i)
                break
            if not quoted and line[i:i + 2] == b'/*':
                in_block = True
                continue
            if line[i] == 34 and not escaped:
                quoted = not quoted
            escaped = quoted and line[i] == 92 and not escaped
            i += 1
        if _contains_mode_command(visible):
            match = _ASSIGNMENT.fullmatch(visible)
            if not match:
                raise ModeConfigError('server.cfg 含复合或不明确的 mp_gamemode 指令，无法安全修改')
            start, end = match.span('value')
            value = match.group('value').strip(b'"').decode('ascii')
            result.append((offset + start, offset + end, value,
                           offset + match.start('command'), bool(match.group('prefix'))))
        offset += len(line)
    if in_block:
        raise ModeConfigError('server.cfg 含未闭合块注释，无法安全修改')
    return result


@dataclass
class ModeConfigChange:
    backup: str | None
    changed: bool
    _config: 'ModeConfig' = field(repr=False)
    _original: _Snapshot = field(repr=False)
    _written: bytes = field(repr=False)
    _written_inode: tuple | None = field(default=None, repr=False)

    def rollback(self) -> None:
        if not self.changed:
            return
        with SERVER_CFG_LOCK:
            current = self._config._snapshot()
            if (current.data != self._written or
                    current.identity[:2] != self._written_inode or
                    current.permissions != self._original.permissions):
                raise ModeConfigError('server.cfg 已被其他操作修改，拒绝回滚')
            self._config._replace(current, self._original.data, self._original.permissions)
            self.changed = False


class ModeConfig:
    def __init__(self, path):
        # Do not resolve: resolving here would silently follow a server.cfg symlink.
        self.path = Path(path).absolute()

    def _snapshot(self):
        try:
            fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, 'rb') as source:
                before = os.fstat(source.fileno())
                if not stat.S_ISREG(before.st_mode) or before.st_size > _MAX_BYTES:
                    raise ModeConfigError('server.cfg 必须是大小不超过 1 MiB 的普通文件')
                data = source.read(_MAX_BYTES + 1)
                after = os.fstat(source.fileno())
            if len(data) > _MAX_BYTES or _identity(before) != _identity(after):
                raise ModeConfigError('server.cfg 读取期间发生变化或超过 1 MiB')
            return _Snapshot(data, _identity(after), stat.S_IMODE(after.st_mode))
        except OSError as error:
            raise ModeConfigError('无法安全读取 server.cfg（文件缺失、符号链接或权限错误）') from error

    def read(self) -> str | None:
        """Last direct assignment only; exec files and runtime overrides are not read."""
        with SERVER_CFG_LOCK:
            commands = _assignments(self._snapshot().data)
            return commands[-1][2] if commands else None

    def _replace(self, expected, data, permissions):
        temporary = None
        try:
            fd, temporary = tempfile.mkstemp(prefix='.server-mode-', dir=self.path.parent)
            with os.fdopen(fd, 'wb') as target:
                target.write(data)
                target.flush()
                os.fchmod(target.fileno(), permissions)
                os.fsync(target.fileno())
                info = os.fstat(target.fileno())
            if self._snapshot() != expected:
                raise ModeConfigError('server.cfg 已被其他操作修改，请重试')
            os.replace(temporary, self.path)
            temporary = None
            return (info.st_dev, info.st_ino)
        except OSError as error:
            raise ModeConfigError('无法原子写入 server.cfg，原配置未被替换') from error
        finally:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass

    def save(self, mode) -> ModeConfigChange:
        if not isinstance(mode, str) or mode not in MODE_IDS:
            raise ModeConfigError('不支持的游戏模式')
        with SERVER_CFG_LOCK:
            original = self._snapshot()
            commands = _assignments(original.data)
            replacement = original.data
            for start, end, value, command_start, prefixed in reversed(commands):
                if value != mode:
                    replacement = replacement[:start] + b'"' + mode.encode('ascii') + b'"' + replacement[end:]
                if not prefixed:
                    replacement = replacement[:command_start] + b'sm_cvar ' + replacement[command_start:]
            if not commands:
                newline = b'\r\n' if b'\r\n' in replacement else b'\n'
                if replacement and not replacement.endswith((b'\n', b'\r')):
                    replacement += newline
                replacement += b'sm_cvar mp_gamemode "' + mode.encode('ascii') + b'"' + newline
            if len(replacement) > _MAX_BYTES:
                raise ModeConfigError('保存后 server.cfg 将超过 1 MiB')
            change = ModeConfigChange(None, replacement != original.data, self, original, replacement)
            if not change.changed:
                return change
            backup = None
            try:
                fd, backup = tempfile.mkstemp(prefix=self.path.name + '.bak-mode-', dir=self.path.parent)
                with os.fdopen(fd, 'wb') as target:
                    target.write(original.data)
                    target.flush()
                    os.fsync(target.fileno())
                change._written_inode = self._replace(original, replacement, original.permissions)
                change.backup = Path(backup).name
                return change
            except (OSError, ModeConfigError) as error:
                if backup is not None:
                    try:
                        os.unlink(backup)
                    except OSError:
                        pass
                if isinstance(error, ModeConfigError):
                    raise
                raise ModeConfigError('无法安全备份 server.cfg，原配置未被替换') from error
