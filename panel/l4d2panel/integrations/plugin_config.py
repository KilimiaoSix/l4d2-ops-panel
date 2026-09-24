"""Conservative SourceMod auto-CFG editing; file contents are never executed."""
from collections import Counter
from decimal import Decimal, InvalidOperation
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
import threading
import uuid


MAX_BYTES = 512 * 1024
_LOCK = threading.RLock()
_NAME = re.compile(r'[A-Za-z_][A-Za-z0-9_]{0,62}\Z')
_NUMBER = re.compile(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z')
_TOKEN = re.compile(r'^[ \t]*([A-Za-z_][A-Za-z0-9_]*)\b')
_ASSIGN = re.compile(r'^[ \t]*(?P<name>[A-Za-z_][A-Za-z0-9_]*)[ \t]+(?P<token>"(?P<quoted>[^"\\\r\n]*)"|(?P<bare>[^\s";\\]+))(?P<tail>[ \t]*(?://[^\r\n]*)?)(?:\r\n|\n|\r)?\Z')
_META = re.compile(r'^(Default|Minimum|Maximum):[ \t]*"([^"\r\n]*)"[ \t]*$', re.I)
_HEADER = re.compile(r'^\s*//\s*ConVars for plugin\s+"([^"\r\n]+)"\s*$', re.I | re.M)
_BACKUP = re.compile(r'[a-f0-9]{32}\.cfg\Z')
_COMMANDS = {'exec', 'execifexists', 'sm', 'sm_cvar', 'alias', 'bind', 'unbind', 'echo', 'quit', 'exit', 'map', 'changelevel', 'wait', 'plugin_load', 'plugin_unload', 'rcon', 'say', 'say_team'}


class ConfigProblem(Exception):
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind
        self.message = message


def _decimal(value):
    if not isinstance(value, str) or not _NUMBER.fullmatch(value):
        return None
    try:
        number = Decimal(value)
        return number if number.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def _safe_value(value):
    return isinstance(value, str) and len(value) <= 254 and all(32 <= ord(c) <= 126 and c not in '"\\;' for c in value)


def validate_updates(document: dict, updates: dict) -> dict:
    """Validate a partial update for either persistence or individual RCON writes."""
    if not isinstance(updates, dict):
        raise ConfigProblem('invalid', '参数更新必须是名称和值的对象')
    parameters = {p['name']: p for p in document['parameters']}
    for name, value in updates.items():
        if not isinstance(name, str) or not _NAME.fullmatch(name) or name not in parameters:
            raise ConfigProblem('invalid', '未知或无效的参数名')
        parameter = parameters[name]
        if not parameter['editable']:
            raise ConfigProblem('invalid', f'{name} 为只读参数：{parameter["reason"]}')
        if not _safe_value(value):
            raise ConfigProblem('invalid', f'{name} 只接受最多 254 字节的可打印 ASCII，不能包含引号、反斜线或分号')
        if parameter['type'] == 'number':
            number = _decimal(value)
            if number is None:
                raise ConfigProblem('invalid', f'{name} 必须为有限数值')
            for key, violates in (('min', lambda bound: number < bound), ('max', lambda bound: number > bound)):
                if parameter[key] is not None and violates(Decimal(parameter[key])):
                    raise ConfigProblem('invalid', f'{name} 超出允许范围')
    return dict(updates)


def _decode(data: bytes):
    if len(data) > MAX_BYTES:
        raise ConfigProblem('invalid', '配置超过 512 KiB，暂不支持编辑')
    encoding = 'utf-8-sig' if data.startswith(b'\xef\xbb\xbf') else 'utf-8'
    try:
        text = data.decode(encoding)
    except UnicodeDecodeError:
        raise ConfigProblem('invalid', '不支持此配置编码，仅支持 UTF-8 或 UTF-8 BOM') from None
    if '\x00' in text:
        raise ConfigProblem('invalid', '配置含有 NUL 字节，不支持此格式')
    return text, encoding


def _parse(data: bytes):
    text, encoding = _decode(data)
    lines = text.splitlines(keepends=True)
    parameters, positions, comments, occurrences = [], {}, [], Counter()
    warnings = []
    ambiguous_file = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('//'):
            comments.append(stripped[2:].strip())
            continue
        if not stripped:
            comments = []
            continue
        if '/*' in line or '*/' in line:
            ambiguous_file = True
        token = _TOKEN.match(line)
        if not token:
            ambiguous_file = True
            comments = []
            warnings.append(f'第 {index + 1} 行不是支持的单值配置，保留原文')
            continue
        name = token.group(1)
        if name.lower() in _COMMANDS:
            ambiguous_file = True
            comments = []
            warnings.append(f'第 {index + 1} 行为命令，保留原文且不执行')
            continue
        occurrences[name.lower()] += 1
        match = _ASSIGN.fullmatch(line)
        if not match:
            ambiguous_file = True
        metadata, description = {}, []
        bad_metadata = False
        for comment in comments:
            meta = _META.fullmatch(comment)
            if meta:
                key = meta.group(1).lower()
                if key in metadata:
                    bad_metadata = True
                metadata[key] = meta.group(2)
            elif re.match(r'^(Default|Minimum|Maximum):', comment, re.I):
                bad_metadata = True
            elif comment and not comment.startswith('-') and not re.match(r'^(ConVars for plugin|This file was auto-generated)', comment, re.I):
                description.append(comment)
        comments = []
        minimum, maximum = metadata.get('minimum'), metadata.get('maximum')
        numeric = minimum is not None or maximum is not None
        if numeric and (any(v is not None and _decimal(v) is None for v in (minimum, maximum)) or
                        (minimum is not None and maximum is not None and _decimal(minimum) is not None and _decimal(maximum) is not None and Decimal(minimum) > Decimal(maximum))):
            bad_metadata = True
        reason = None
        if not _NAME.fullmatch(name):
            reason = '参数名超过长度限制或格式不支持'
        elif not match:
            reason = '无法可靠解析为单个赋值，可能包含多个命令'
        elif 'default' not in metadata:
            reason = '缺少标准 Default 元数据，无法确认是可编辑参数'
        elif bad_metadata:
            reason = '参数元数据格式不可靠'
        value = (match.group('quoted') if match.group('quoted') is not None else match.group('bare')) if match else line[token.end():].strip()
        if reason is None and not _safe_value(value):
            reason = '现有值包含不支持的字符或超出长度限制'
        parameters.append({'name': name, 'value': value, 'default': metadata.get('default'), 'min': minimum,
                           'max': maximum, 'description': '\n'.join(description),
                           'type': 'number' if numeric and not bad_metadata else 'text',
                           'editable': reason is None, 'reason': reason})
        if match:
            positions[name] = (index, match.start('token'), match.end('token'))
    # Commands, duplicate writes and unsupported syntax make effective values ambiguous.
    seen, unique = set(), []
    for parameter in parameters:
        name = parameter['name']
        if occurrences[name.lower()] > 1 or ambiguous_file:
            parameter['editable'] = False
            parameter['reason'] = '配置中存在重复参数' if occurrences[name.lower()] > 1 else '文件含命令或无法可靠解析的语法，可能覆盖参数'
        if name not in seen:
            seen.add(name)
            unique.append(parameter)
    if ambiguous_file:
        warnings.append('文件含命令或不支持的语法，参数全部只读；请使用专用适配')
    return {'encoding': encoding, 'parameters': unique, 'warnings': warnings}, lines, positions


class ConfigFiles:
    """root is the game's cfg/sourcemod directory; backups live outside it."""
    def __init__(self, root: Path, backup_root: Path):
        self.root = Path(root).absolute()
        self.backup_root = Path(backup_root).absolute()
        self.lock = _LOCK

    @staticmethod
    def _no_symlinks(path: Path):
        for part in (path, *path.parents):
            if part.is_symlink():
                raise ConfigProblem('invalid', '不支持符号链接路径')

    def _path(self, file: str) -> Path:
        if not isinstance(file, str) or not file or '\\' in file or '\x00' in file:
            raise ConfigProblem('invalid', '无效的配置路径')
        relative = PurePosixPath(file)
        if relative.is_absolute() or any(p in ('', '.', '..') for p in file.split('/')) or relative.suffix != '.cfg':
            raise ConfigProblem('invalid', '配置必须是 cfg/sourcemod 内的相对 .cfg 文件')
        path = self.root.joinpath(*relative.parts)
        self._no_symlinks(path)
        if not path.is_file():
            raise ConfigProblem('missing', '配置文件不存在')
        return path

    @staticmethod
    def _bytes(path: Path) -> bytes:
        try:
            with path.open('rb') as source:
                data = source.read(MAX_BYTES + 1)
        except FileNotFoundError:
            raise ConfigProblem('missing', '配置文件不存在') from None
        _decode(data)
        return data

    def _backup_dir(self, file: str) -> Path:
        identity = hashlib.sha256(str(self.root / file).encode('utf-8')).hexdigest()
        path = self.backup_root / identity
        self._no_symlinks(path)
        return path

    def _backups(self, file: str):
        directory = self._backup_dir(file)
        if not directory.exists():
            return []
        return sorted((p for p in directory.iterdir() if _BACKUP.fullmatch(p.name) and not p.is_symlink() and p.is_file()),
                      key=lambda p: (p.stat().st_mtime_ns, p.name), reverse=True)

    def _document(self, file: str, data: bytes):
        document, _, _ = _parse(data)
        document.update(file=file, revision=hashlib.sha256(data).hexdigest(),
                        backups=[{'id': p.stem, 'created': p.stat().st_mtime} for p in self._backups(file)])
        return document

    def discover(self, plugin: str) -> list:
        if not isinstance(plugin, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+\.smx', plugin) or plugin in ('.smx', '..smx'):
            raise ConfigProblem('invalid', '无效的插件文件名')
        with self.lock:
            self._no_symlinks(self.root)
            found, scanned = [], 0
            for directory, dirs, names in os.walk(self.root, followlinks=False):
                dirs[:] = sorted(d for d in dirs if not (Path(directory) / d).is_symlink())
                for name in sorted(names):
                    if not name.endswith('.cfg'):
                        continue
                    path = Path(directory) / name
                    if path.is_symlink() or not path.is_file():
                        continue
                    scanned += 1
                    if scanned > 512:
                        raise ConfigProblem('invalid', '配置文件超过 512 个，请缩小 cfg/sourcemod 中的配置范围')
                    try:
                        text, _ = _decode(self._bytes(path))
                    except ConfigProblem:
                        continue
                    headers = _HEADER.findall(text[:16384])
                    source = 'header' if headers and all(header == plugin for header in headers) else 'filename' if not headers and name == Path(plugin).stem + '.cfg' else None
                    if source:
                        found.append({'name': path.relative_to(self.root).as_posix(), 'source': source})
            return sorted(found, key=lambda item: item['name'])

    def read(self, file: str) -> dict:
        with self.lock:
            return self._document(file, self._bytes(self._path(file)))

    @staticmethod
    def _revision(data: bytes, revision: str):
        if not isinstance(revision, str) or hashlib.sha256(data).hexdigest() != revision:
            raise ConfigProblem('conflict', '配置文件已变化，请重新读取后操作')

    def _write(self, file: str, original: bytes, replacement: bytes):
        if original == replacement:
            return self._document(file, original), None
        _decode(replacement)
        path = self._path(file)
        directory = self._backup_dir(file)
        directory.mkdir(parents=True, exist_ok=True)
        backup_id = uuid.uuid4().hex
        backup = directory / (backup_id + '.cfg')
        temporary = None
        try:
            with backup.open('xb') as target:
                os.chmod(backup, 0o600)
                target.write(original)
                target.flush()
                os.fsync(target.fileno())
            mode = stat.S_IMODE(path.stat().st_mode)
            fd, temporary = tempfile.mkstemp(prefix='.panel-cfg-', dir=path.parent)
            with os.fdopen(fd, 'wb') as target:
                os.fchmod(target.fileno(), mode)
                target.write(replacement)
                target.flush()
                os.fsync(target.fileno())
            self._revision(self._bytes(self._path(file)), hashlib.sha256(original).hexdigest())
            os.replace(temporary, path)
            temporary = None
        except Exception:
            backup.unlink(missing_ok=True)
            raise
        finally:
            if temporary is not None:
                Path(temporary).unlink(missing_ok=True)
        cleanup_failed = False
        for old in self._backups(file)[20:]:
            try:
                old.unlink()
            except OSError:
                cleanup_failed = True
        document = self._document(file, replacement)
        if cleanup_failed:
            document['warnings'].append('配置已保存，部分过期备份未能清理')
        return document, backup_id

    def save(self, file: str, revision: str, updates: dict) -> tuple:
        with self.lock:
            data = self._bytes(self._path(file))
            self._revision(data, revision)
            document, lines, positions = _parse(data)
            for name, value in validate_updates(document, updates).items():
                if next(p['value'] for p in document['parameters'] if p['name'] == name) == value:
                    continue
                index, start, end = positions[name]
                lines[index] = lines[index][:start] + '"' + value + '"' + lines[index][end:]
            return self._write(file, data, ''.join(lines).encode(document['encoding']))

    def restore(self, file: str, revision: str, backup_id: str) -> tuple:
        with self.lock:
            data = self._bytes(self._path(file))
            self._revision(data, revision)
            if not isinstance(backup_id, str) or not re.fullmatch(r'[a-f0-9]{32}', backup_id):
                raise ConfigProblem('invalid', '无效的备份标识')
            backup = self._backup_dir(file) / (backup_id + '.cfg')
            self._no_symlinks(backup)
            return self._write(file, data, self._bytes(backup))
