"""Versioned, crash-recoverable plugin file commits. Reads never perform recovery.

The caller holds the shared server operation lock and has verified the game is stopped.
Every input is staged before publishing a journal; recovery only undoes our own bytes.
"""
import hashlib
import json
import os
import re
import stat
import tempfile
import uuid
from pathlib import Path, PurePosixPath


class PackError(ValueError):
    pass


def digest(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')


def durable_unlink(path):
    path.unlink()
    if os.name == 'posix':
        descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(descriptor)
        finally: os.close(descriptor)


def atomic_write(path, data, mode=0o600):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.chmod(temp, mode)
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.replace(temp, path)
        if os.name == 'posix':
            descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try: os.fsync(descriptor)
            finally: os.close(descriptor)
    finally:
        if os.path.exists(temp): os.unlink(temp)


def relative_path(name):
    if not isinstance(name, str) or not name or '\\' in name or ':' in name or '\x00' in name:
        raise PackError('无效的插件文件路径')
    parts = PurePosixPath(name).parts
    if name.startswith('/') or any(p in ('', '.', '..') for p in name.split('/')):
        raise PackError('插件路径不能越界')
    if not parts or parts[0] not in ('addons', 'cfg'):
        raise PackError('插件文件必须位于 addons/ 或 cfg/')
    return parts


def safe_file(root, name):
    """Reject links and special files in every existing component, including root."""
    root = Path(root)
    if root.is_symlink(): raise PackError('插件根目录不能是符号链接')
    target = root.joinpath(*relative_path(name))
    current = root
    for part in relative_path(name):
        current = current / part
        try: info = current.lstat()
        except FileNotFoundError: continue
        if stat.S_ISLNK(info.st_mode) or not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
            raise PackError(f'文件类型不安全：{name}')
        if stat.S_ISREG(info.st_mode) and (current != target or info.st_nlink != 1):
            raise PackError(f'文件路径或硬链接不安全：{name}')
        if current == target and not stat.S_ISREG(info.st_mode):
            raise PackError(f'目标不是普通文件：{name}')
    return target


def file_hash(path):
    return digest(path.read_bytes()) if path.is_file() else None


class PackFiles:
    SCHEMA = 1

    def __init__(self, game, state, *, editable_paths=()):
        self.game, self.state = Path(game), Path(state)
        # Basic settings reuse the journal with a fixed internal path allowlist.
        # Public plugin manifests still only accept managed/seed policies.
        self.editable_paths = frozenset(editable_paths)
        self.receipt_path = self.state / 'receipt.json'
        self.journal_path = self.state / 'transaction.json'

    def _read(self, path):
        if path.is_symlink(): raise PackError('插件状态不能使用符号链接')
        if not path.exists(): return None
        value = json.loads(path.read_text(encoding='utf-8'))
        if value.get('schema') != self.SCHEMA or value.get('game_dir') != str(self.game.resolve()):
            raise PackError('插件状态版本或游戏目录归属不匹配')
        return value

    def receipt(self):
        return self._read(self.receipt_path) or {'schema': 1, 'game_dir': str(self.game.resolve()), 'packs': {}, 'files': {}}

    def pending(self):
        journal = self._read(self.journal_path)
        return journal if journal and journal['phase'] not in ('committed', 'rolled_back') else None

    def _state_safe(self):
        for path in (self.state, self.receipt_path, self.journal_path, self.state / 'transactions'):
            if path.is_symlink(): raise PackError('插件状态不能使用符号链接')
        self.state.mkdir(parents=True, exist_ok=True, mode=0o700)

    def plan(self, files):
        """files: [{path, source, sha256, policy, pack}]; validate the complete set."""
        if self.pending(): raise PackError('上次插件事务尚未恢复，请先恢复')
        receipt = self.receipt(); result = []; names = set()
        for item in files:
            name = item['path']; target = safe_file(self.game, name)
            if name in names: raise PackError(f'插件载荷重叠：{name}')
            names.add(name)
            policy = item['policy']
            if policy not in ('managed', 'seed') and not (policy == 'edit' and name in self.editable_paths):
                raise PackError('未知文件策略')
            mode = item.get('mode', 0o644)
            if mode not in (0o644, 0o755) or mode == 0o755 and name not in ('addons/sourcemod/scripting/spcomp', 'addons/sourcemod/scripting/spcomp64'):
                raise PackError('插件文件权限无效')
            source = Path(item['source'])
            info = source.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1: raise PackError('载荷不是独立普通文件')
            data = source.read_bytes()
            if digest(data) != item['sha256']: raise PackError(f'载荷校验失败：{name}')
            if policy != 'edit' and name.startswith('cfg/') and name.lower().endswith('.cfg') and not data.isascii():
                raise PackError(f'引擎配置必须为 ASCII：{name}')
            old = file_hash(target)
            if policy == 'edit' and ('expected' not in item or item['expected'] != old):
                raise PackError(f'配置已被外部修改：{name}')
            owned = receipt['files'].get(name, {}).get('sha256')
            if policy == 'managed' and old not in (None, item['sha256'], owned):
                raise PackError(f'已有非托管或已修改的文件，未覆盖：{name}')
            action = 'preserve' if policy == 'seed' and old is not None else 'same' if old == item['sha256'] else 'write'
            result.append({**item, 'source': str(source), 'old': old, 'action': action})
        return result

    def install(self, files, packs, job=None, checkpoint=None):
        plan = self.plan(files); self._state_safe()
        transaction_id = uuid.uuid4().hex
        directory = self.state / 'transactions' / transaction_id
        directory.mkdir(parents=True, mode=0o700)
        before_receipt = self.receipt_path.read_bytes() if self.receipt_path.exists() else None
        receipt = self.receipt(); receipt['packs'].update(packs)
        journal = {'schema': 1, 'game_dir': str(self.game.resolve()), 'id': transaction_id,
                   'phase': 'prepared', 'entries': [], 'receipt_before': before_receipt.decode() if before_receipt else None}
        if job: job.total, job.done = len(plan), 0
        # Private backups and staging are durable before the first game-file mutation.
        for index, item in enumerate(plan):
            if job and job.cancel: raise PackError('安装已取消，未更改游戏文件')
            name = item['path']; target = safe_file(self.game, name)
            if file_hash(target) != item['old']: raise PackError(f'预检后文件已变化：{name}')
            if item['action'] == 'write':
                data = Path(item['source']).read_bytes()
                if digest(data) != item['sha256']: raise PackError(f'载荷已变化：{name}')
                atomic_write(directory / f'{index}.new', data)
                mode = stat.S_IMODE(target.stat().st_mode) if target.exists() else item.get('mode', 0o644)
                if target.exists(): atomic_write(directory / f'{index}.old', target.read_bytes())
                journal['entries'].append({'path': name, 'index': index, 'old': item['old'], 'new': item['sha256'], 'mode': mode})
            receipt['files'][name] = {'sha256': item['old'] if item['action'] == 'preserve' else item['sha256'],
                                      'policy': item['policy'], 'pack': item['pack']}
        receipt['transaction'] = transaction_id
        journal['receipt_after'] = json_bytes(receipt).decode()
        atomic_write(self.journal_path, json_bytes(journal))
        try:
            if checkpoint: checkpoint('prepared', 0)
            journal['phase'] = 'applying'; atomic_write(self.journal_path, json_bytes(journal))
            entries = {e['path']: e for e in journal['entries']}
            for index, item in enumerate(plan):
                if job and job.cancel: raise PackError('安装已取消')
                name = item['path']; target = safe_file(self.game, name)
                if file_hash(target) != item['old']: raise PackError(f'提交前文件已变化：{name}')
                if name in entries:
                    entry = entries[name]; data = (directory / f'{entry["index"]}.new').read_bytes()
                    if digest(data) != entry['new']: raise PackError('暂存文件校验失败')
                    atomic_write(target, data, entry['mode'])
                if job: job.done, job.msg = index + 1, f'处理文件 {index + 1}/{len(plan)}'
                if checkpoint: checkpoint('file', index)
            # Do not overwrite an external receipt edit either.
            if (self.receipt_path.read_bytes() if self.receipt_path.exists() else None) != before_receipt:
                raise PackError('插件收据在提交时被外部修改')
            atomic_write(self.receipt_path, json_bytes(receipt))
            if checkpoint: checkpoint('receipt', 0)
            journal['phase'] = 'committed'; atomic_write(self.journal_path, json_bytes(journal))
        except Exception as error:
            try: self.recover()
            except Exception as recovery: raise PackError(f'{error}；自动回滚未完成：{recovery}') from error
            raise
        return receipt

    def recover(self):
        journal = self.pending()
        if not journal: return False
        self._state_safe()
        transaction_id = journal['id']
        if not re.fullmatch('[0-9a-f]{32}', transaction_id): raise PackError('无效事务编号')
        directory = self.state / 'transactions' / transaction_id
        if directory.is_symlink(): raise PackError('备份目录不能使用链接')
        errors = []
        for entry in reversed(journal['entries']):
            try:
                target = safe_file(self.game, entry['path']); current = file_hash(target)
                if current == entry['old']: continue
                if current != entry['new']: raise PackError('文件已被外部修改')
                if entry['old'] is None: durable_unlink(target)
                else:
                    backup = directory / f'{int(entry["index"])}.old'
                    if backup.is_symlink(): raise PackError('备份不能使用链接')
                    data = backup.read_bytes()
                    if digest(data) != entry['old']: raise PackError('备份校验失败')
                    atomic_write(target, data, entry['mode'])
            except Exception as error: errors.append(f'{entry["path"]}: {error}')
        current_receipt = self.receipt_path.read_bytes().decode('utf-8') if self.receipt_path.exists() else None
        if current_receipt == journal['receipt_after']:
            if journal['receipt_before'] is None: durable_unlink(self.receipt_path)
            else: atomic_write(self.receipt_path, journal['receipt_before'].encode())
        elif current_receipt != journal['receipt_before']: errors.append('收据已被外部修改')
        if errors:
            journal['phase'] = 'incomplete'; journal['errors'] = errors
            atomic_write(self.journal_path, json_bytes(journal)); raise PackError('；'.join(errors))
        journal['phase'] = 'rolled_back'; atomic_write(self.journal_path, json_bytes(journal))
        return True
