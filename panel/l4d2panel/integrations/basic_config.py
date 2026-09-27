"""One revision and recoverable transaction for the four basic-setting files."""
import os
from pathlib import Path
import stat
import tempfile

from .game_mode_config import direct_assignments, rewrite_direct
from .hostname_file import canonical_name, read_name
from .pack_files import PackFiles, PackError, digest, json_bytes, safe_file
from .sm_files import SERVER_CFG_LOCK

SERVER = 'cfg/server.cfg'
HOSTNAME = 'addons/sourcemod/data/panel_hostname.txt'
MULTISLOTS = 'cfg/sourcemod/l4dmultislots.cfg'
CAPACITY = 'cfg/panel-capacity.cfg'
FILES = (SERVER, HOSTNAME, MULTISLOTS, CAPACITY)
CAPACITY_DATA = b'// Panel startup profile, not executed as engine CFG.\npanel_capacity 31\n'


def last_value(data, command):
    rows = direct_assignments(data or b'', command)
    return rows[-1][2] if rows else None


class BasicConfig:
    def __init__(self, game, state):
        self.game, self.state = Path(game), Path(state)
        self.transaction = PackFiles(game, state, editable_paths=FILES)

    def _snapshot(self):
        result = {}
        for name in FILES:
            path = safe_file(self.game, name)
            if not path.exists():
                if name == SERVER: raise PackError('游戏尚未安装或 server.cfg 丢失')
                result[name] = None; continue
            # Never follow a link swapped in after the path walk, or block on FIFO.
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, 'rb') as stream:
                before = os.fstat(stream.fileno())
                if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > 1024 * 1024:
                    raise PackError('基础配置必须为不超过 1 MiB 的独立普通文件')
                data = stream.read(1024 * 1024 + 1)
                after = os.fstat(stream.fileno())
            if (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                    after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) or len(data) > 1024 * 1024:
                raise PackError('读取配置时文件发生变化')
            result[name] = data
        return result

    @staticmethod
    def revision(snapshot):
        return digest(json_bytes({name: digest(data) if data is not None else None for name, data in snapshot.items()}))

    def read(self):
        with SERVER_CFG_LOCK:
            snapshot = self._snapshot()
            server = snapshot[SERVER]
            fallback = last_value(server, 'hostname')
            region = last_value(server, 'sv_region')
            limit = last_value(server, 'sv_maxplayers')
            name = read_name(snapshot[HOSTNAME])
            return {'revision': self.revision(snapshot), 'server_name': name or fallback or '',
                    'hostname_file': name is not None, 'ascii_fallback': fallback or 'L4D2 Server',
                    'password_set': bool(last_value(server, 'sv_password')),
                    'game_mode': last_value(server, 'mp_gamemode') or 'coop',
                    'region': int(region) if region is not None else 255,
                    'coop_players': int(limit) if limit and 4 <= int(limit) <= 12 else 4,
                    'pending': self.transaction.pending() is not None}

    def save(self, revision, updates, *, multiplayer=False, checkpoint=None):
        with SERVER_CFG_LOCK:
            original = self._snapshot()
            if revision != self.revision(original): raise PackError('基础配置已变化，请重新读取后保存')
            if self.transaction.pending(): raise PackError('上次基础设置保存未完成，请先恢复')
            changes, cvars, restart_required = {}, {}, False
            if 'server_name' in updates:
                name = canonical_name(updates['server_name'])
                changes[HOSTNAME] = (name + '\n').encode('utf-8')
                fallback = updates.get('ascii_fallback', name if name.isascii() else 'L4D2 Server')
                cvars['hostname'] = fallback
            elif 'ascii_fallback' in updates: cvars['hostname'] = updates['ascii_fallback']
            if 'password' in updates: cvars['sv_password'] = updates['password']
            if 'region' in updates: cvars['sv_region'] = str(updates['region'])
            if 'coop_players' in updates:
                count = updates['coop_players']
                if not multiplayer and count != 4: raise PackError('请先安装多人合作插件包')
                if multiplayer:
                    cvars.update(sv_maxplayers=str(count), sv_force_unreserved='1', sv_allow_lobby_connect_only='0')
                    changes[MULTISLOTS] = rewrite_direct(original[MULTISLOTS] or b'', {
                        'l4d_multislots_max_survivors': str(count), 'l4d_multislots_min_survivors': '4'})
                    changes[CAPACITY] = CAPACITY_DATA
                    restart_required = (any(last_value(original[SERVER], key) != value for key, value in
                        {'sv_maxplayers': str(count), 'sv_force_unreserved': '1', 'sv_allow_lobby_connect_only': '0'}.items())
                        or changes[MULTISLOTS] != original[MULTISLOTS] or changes[CAPACITY] != original[CAPACITY])
                elif last_value(original[SERVER], 'sv_maxplayers') is not None:
                    cvars['sv_maxplayers'] = '4'
            if cvars: changes[SERVER] = rewrite_direct(original[SERVER], cvars)
            changes = {name: data for name, data in changes.items() if data != original[name]}
            if not changes: return {'changed': False, 'revision': revision, 'transaction': None, 'capacity_changed': False}
            self.transaction._state_safe()
            with tempfile.TemporaryDirectory(prefix='.basic-stage-', dir=self.state) as directory:
                files = []
                for index, (name, data) in enumerate(changes.items()):
                    source = Path(directory) / str(index); source.write_bytes(data); source.chmod(0o600)
                    files.append({'path': name, 'source': str(source), 'sha256': digest(data), 'policy': 'edit',
                                  'pack': 'basic', 'expected': digest(original[name]) if original[name] is not None else None})
                self.transaction.install(files, {'basic': {'version': '1'}}, checkpoint=checkpoint)
            current = {**original, **changes}
            return {'changed': True, 'revision': self.revision(current), 'capacity_changed': restart_required,
                    'transaction': self.transaction.receipt()['transaction']}

    def recover(self):
        with SERVER_CFG_LOCK: return self.transaction.recover()
