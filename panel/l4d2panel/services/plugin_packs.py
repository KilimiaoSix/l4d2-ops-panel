"""Plugin profile orchestration; file mechanics and network fetches live in integrations."""
import time

from ..errors import ApiError
from ..integrations.pack_files import PackError, PackFiles
from ..integrations.pack_registry import PackRegistry
from .features import active_plugin_names


class PluginPackService:
    def __init__(self, root, paths, jobs, server, rcon, state, audit, invalidate):
        self.registry = PackRegistry(root)
        self.files = PackFiles(paths.game, paths.base / 'pack_state')
        self.paths, self.jobs, self.server, self.rcon = paths, jobs, server, rcon
        self.state, self.audit, self.invalidate = state, audit, invalidate

    def _game_ready(self):
        return all((self.paths.game / name).is_file() for name in ('steam.inf', 'gameinfo.txt', 'bin/server_srv.so'))

    def _runtime(self):
        if not self._game_ready(): return None
        try:
            names = self.rcon.run('sm plugins list').lower()
            if 'listing' not in names and 'plugins' not in names: return None
            return active_plugin_names(names)
        except Exception: return None

    def status(self, probe=False):
        try:
            receipt, pending = self.files.receipt(), self.files.pending()
            index = self.registry.payload_index()
        except (PackError, ValueError, OSError) as error:
            raise ApiError(409, str(error))
        names = self._runtime() if probe else None
        runtime = {}
        for name in self.registry.resolve(list(self.registry.packs), check_conflicts=False):
            pack = self.registry.packs[name]
            active = None
            if names is not None:
                active = all(token.lower() in names for token in pack['probes']) if pack['probes'] else None
                if name == 'l4dtoolz':
                    try: active = 'l4dtoolz' in self.rcon.run('plugin_print').lower()
                    except Exception: active = None
                deps = [runtime[n] for n in pack['requires']]
                if any(d is False for d in deps): active = False
                elif any(d is None for d in deps): active = None
            runtime[name] = active
        rows = []
        for name, pack in self.registry.packs.items():
            installed = name in receipt['packs']
            available = all(self.registry.packs[n]['payload'] in index or n in self.registry.manifest.get('official_downloads', {})
                            for n in self.registry.resolve([name]))
            active = runtime[name]
            rows.append({**pack, 'available': available, 'installed': installed,
                         'state': 'incomplete' if pending else 'active' if active is True else
                                  'unknown' if installed and probe and active is None else 'restart_required' if installed else 'not_installed',
                         'runtime': 'active' if active is True else 'missing' if active is False else 'unknown'})
        job = self.jobs.get('packs', 'install')
        return {'schema': 1, 'packs': rows, 'profiles': self.registry.manifest['profiles'],
                'game_installed': self._game_ready(), 'pending': {'id': pending['id'], 'phase': pending['phase'], 'errors': pending.get('errors', [])} if pending else None,
                'job': job.to_dict() if job else None}

    def start(self, selection, stop_game, actor):
        try: selected = self.registry.resolve(selection)
        except PackError as error: raise ApiError(400, str(error))
        if not self._game_ready(): raise ApiError(409, '请先完成游戏安装')
        if not self.server.operation_lock.acquire(blocking=False): raise ApiError(409, '安装或服务器操作正在进行')
        try:
            if self.files.pending(): raise ApiError(409, '上次插件安装未完成，请先恢复')
            if self.server.running() and not stop_game: raise ApiError(409, '安装插件需要停止游戏，请确认停止并安装')
            def work(job):
                try:
                    files = self.registry.files(selected, self.paths.base / 'pack_state' / 'downloads', job)
                    self.files.plan(files)
                    if job.cancel: raise PackError('安装已取消，未更改游戏文件')
                    self._stop(stop_game, job)
                    versions = {n: {'version': self.registry.packs[n]['version'], 'installed_at': int(time.time())} for n in selected}
                    self.files.install(files, versions, job)
                    self.state.put('minimal_pack_committed', 'minimal' in self.files.receipt()['packs'])
                    self.invalidate()
                    job.msg = '插件文件已安装；启动游戏后检查实际加载状态'
                    self.audit.add(actor, 'packs.install.result', 'done ' + ','.join(selected))
                except Exception:
                    self.audit.add(actor, 'packs.install.result', 'error ' + ','.join(selected)); raise
                finally: self.server.operation_lock.release()
            job = self.jobs.start('packs', 'install', work, initial_msg='正在校验插件包…')
        except Exception:
            self.server.operation_lock.release(); raise
        self.audit.add(actor, 'packs.install', ','.join(selected))
        return {'job': job.id, 'resolved': selected}

    def _stop(self, allowed, job):
        if not self.server.running(): return
        if not allowed: raise PackError('游戏正在运行，尚未确认停止')
        if not self.server.available(): raise PackError('未配置可用的游戏停服入口，请手动停止后重试')
        job.msg = '正在停止游戏…'
        # Already holding operation_lock: never call ServerControl.run recursively.
        self.server.backend.run('stop')
        if self.server.running(): raise PackError('游戏未完全停止，没有提交插件文件')

    def recover(self, stop_game, actor):
        if not self.server.operation_lock.acquire(blocking=False): raise ApiError(409, '安装或服务器操作正在进行')
        try:
            if self.server.running() and not stop_game: raise ApiError(409, '恢复需要停止游戏')
            def work(job):
                try:
                    self._stop(stop_game, job)
                    restored = self.files.recover()
                    self.state.put('minimal_pack_committed', 'minimal' in self.files.receipt()['packs'])
                    self.invalidate()
                    job.msg = '事务已恢复，可以重新安装' if restored else '没有需要恢复的事务'
                    self.audit.add(actor, 'packs.recover.result', 'done')
                except Exception:
                    self.audit.add(actor, 'packs.recover.result', 'error'); raise
                finally: self.server.operation_lock.release()
            job = self.jobs.start('packs', 'install', work)
        except Exception:
            self.server.operation_lock.release(); raise
        self.audit.add(actor, 'packs.recover'); return {'job': job.id}

    def cancel(self, actor):
        if not self.jobs.cancel('packs', 'install'): raise ApiError(409, '没有运行中的插件任务')
        self.audit.add(actor, 'packs.cancel'); return {'ok': True}
