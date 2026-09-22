"""Custom campaigns (.vpk in <game>/addons): listing, upload, delete, Steam Workshop install, zip packaging."""
import os, re, secrets, shutil, time, zipfile
from pathlib import Path

from ..errors import ApiError
from ..integrations import workshop
from ..integrations.rcon import RconClient
from ..integrations.steam import SteamClient
from ..integrations.vpk import VPK_MAGIC, vpk_entries
from ..jobs import DownloadStore, Job, JobRegistry
from ..settings import Paths, Settings
from ..store.audit import AuditLog

INSTALL_NOTE = ('把压缩包里的 .vpk 放到 Left 4 Dead 2\\left4dead2\\addons\\ 目录，重启游戏后在“附加组件”里启用即可。\n'
                '服务器和所有玩家需要装同一个战役才能一起玩。\n')
PUBID = re.compile(r'(\d{6,12})')


def safe_vpk_name(n):
    """A bare file name ending in .vpk with shell/path-unfriendly characters replaced, or None."""
    n = os.path.basename(str(n)).strip()
    n = re.sub(r'[^\w.\-一-鿿 ]', '_', n)
    return n if n.lower().endswith('.vpk') and len(n) > 4 else None


class AddonService:
    def __init__(self, settings: Settings, paths: Paths, rcon: RconClient, steam: SteamClient, jobs: JobRegistry, downloads: DownloadStore, audit: AuditLog):
        self.settings, self.paths, self.rcon, self.steam, self.jobs, self.downloads, self.audit = settings, paths, rcon, steam, jobs, downloads, audit
        self.protected = set(settings.protected_addons)

    # ---- listing ----
    def info(self, name):
        path = self.paths.addons / name
        ents = vpk_entries(path)
        maps = sorted(e.split('/')[-1][:-4] for e in ents if e.startswith('maps/') and e.endswith('.bsp'))
        title = ''
        for e in ents:
            if e.startswith('missions/') and e.endswith('.txt'):
                title = e.split('/')[-1][:-4]; break
        return {'name': name, 'size_mb': round(os.path.getsize(path) / 1048576, 1), 'maps': maps, 'mission': title, 'protected': name in self.protected}

    def list(self):
        return [self.info(n) for n in sorted(os.listdir(self.paths.addons)) if n.lower().endswith('.vpk')]

    def overview(self):
        return {'addons': self.list(), 'jobs': self.jobs.snapshot('workshop'), 'zips': self.jobs.snapshot('zip')}

    def refresh(self) -> str:
        """Hot-reload the addon list in the running game (no restart needed)."""
        try: return self.rcon.run('update_addon_paths') + '\n' + self.rcon.run('mission_reload')
        except Exception as e: return f'(热加载失败: {e}，重启服务器后生效)'

    # ---- upload ----
    def upload_target(self, raw_name) -> tuple:
        """-> (safe name, temp path to stream the body into). Raises 400 for a non-.vpk name."""
        name = safe_vpk_name(raw_name)
        if not name: raise ApiError(400, '只接受 .vpk 文件')
        return name, self.paths.addons / (name + '.uploading')

    def check_upload_size(self, n: int):
        if n <= 0 or n > int(self.settings.max_upload_mb) * 1048576: raise ApiError(400, f'文件为空或超过 {self.settings.max_upload_mb}MB')

    def finish_upload(self, name, tmp, got: int, expected: int, actor: str) -> dict:
        tmp = Path(tmp)
        if got != expected:
            tmp.unlink(missing_ok=True); raise ApiError(400, f'上传中断 ({got}/{expected})')
        with open(tmp, 'rb') as f: magic = f.read(4)
        if magic != VPK_MAGIC:
            tmp.unlink(missing_ok=True); raise ApiError(400, '不是有效的 VPK 文件')
        os.replace(tmp, self.paths.addons / name)
        self.audit.add(actor, 'addon.upload', name)
        return {'ok': True, 'addon': self.info(name), 'out': self.refresh()}

    # ---- delete ----
    def delete(self, raw_name, actor: str) -> dict:
        name = safe_vpk_name(str(raw_name))
        if not name or name in self.protected or not (self.paths.addons / name).exists(): raise ApiError(400, '不能删除该文件')
        os.remove(self.paths.addons / name); self.audit.add(actor, 'addon.delete', name)
        return {'ok': True, 'out': self.refresh(), 'addons': self.list()}

    # ---- workshop ----
    def start_workshop(self, text, actor: str) -> str:
        m = PUBID.search(str(text or ''))
        if not m: raise ApiError(400, '请输入创意工坊 ID 或链接')
        pubid = m.group(1)
        if self.jobs.is_running('workshop', pubid): raise ApiError(400, '已经在下载了')
        self.jobs.start('workshop', pubid, lambda job: self._workshop(pubid, job), initial_msg='正在查询创意工坊…')
        self.audit.add(actor, 'addon.workshop', pubid)
        return pubid

    def cancel_workshop(self, pubid) -> None:
        if not self.jobs.cancel('workshop', str(pubid)): raise ApiError(400, '没有进行中的下载')

    def _wslog(self, pubid, msg):
        try:
            os.makedirs(self.paths.workshop_tmp, exist_ok=True)
            with open(self.paths.workshop_tmp / (pubid + '.log'), 'a', encoding='utf-8') as f: f.write(time.strftime('%Y-%m-%d %H:%M:%S ') + msg + '\n')
        except Exception: pass

    def _workshop(self, pubid: str, job: Job):
        t0 = time.time(); self._wslog(pubid, '开始'); dest = str(self.paths.workshop_tmp / (pubid + '.part'))
        dd = self.settings.depotdownloader; has_depot = bool(dd) and os.path.exists(dd)
        try:
            try: d = self.steam.pubfile_details(pubid)
            except Exception as e:
                self._wslog(pubid, f'Steam Web API 失败: {e}')
                if has_depot: return self._depot(pubid, job, t0)
                raise RuntimeError(f'{e}，且没有 DepotDownloader 可回退')
            if int(d.get('result', 0)) != 1: raise RuntimeError(f'创意工坊没有这个物品（result={d.get("result")}，可能已删除或设为私有）')
            if int(d.get('consumer_app_id', 550)) != 550: raise RuntimeError('这不是 Left 4 Dead 2 的创意工坊物品')
            if int(d.get('file_type', 0)) == 2: raise RuntimeError('这是一个合集，请分别下载里面的每个物品')
            url = d.get('file_url') or ''; size = int(d.get('file_size') or 0)
            job.name = safe_vpk_name(d.get('filename') or '') or f'workshop_{pubid}.vpk'; job.title = d.get('title', '')
            if not url or not size:
                if int(d.get('hcontent_file') or 0) and has_depot: return self._depot(pubid, job, t0)
                raise RuntimeError('这个物品没有可直接下载的文件' + ('，需要 DepotDownloader 才能下载' if int(d.get('hcontent_file') or 0) else ''))
            self._wslog(pubid, f'{job.title} -> {job.name} {size} 字节 {url}')
            os.makedirs(self.paths.workshop_tmp, exist_ok=True); job.msg = f'开始下载 {job.name}（{size / 1048576:.1f} MB）'
            workshop.download_ranged(url, size, dest, job, self.settings.workshop_connections, self.settings.workshop_retries, lambda m: self._wslog(pubid, m))
            with open(dest, 'rb') as f: magic = f.read(4)
            if magic != VPK_MAGIC: os.remove(dest); raise RuntimeError(f'下载的文件不是 VPK（{d.get("filename")}）')
            final = self.paths.addons / job.name
            try: os.replace(dest, final)
            except OSError: shutil.move(dest, final)
            el = int(time.time() - t0)
            job.files = [job.name]; job.state = 'done'
            job.msg = f'已安装: {job.name}（{size / 1048576:.1f} MB，用时 {el // 60} 分 {el % 60} 秒） ' + self.refresh()
            self._wslog(pubid, job.msg)
        except Exception as e:
            kept = os.path.exists(dest); cancelled = str(e) == workshop.CANCELLED
            job.state = 'error'
            job.msg = (workshop.CANCELLED if cancelled else f'下载失败: {e}') + ('；已下载的部分已保留，再点一次“下载安装”会接着下' if kept else '')
            self._wslog(pubid, job.msg)

    def _depot(self, pubid: str, job: Job, t0: float):
        """Fallback for items without a direct file_url: DepotDownloader into workshop_tmp/depot_<id> (kept on failure so it can resume)."""
        tmp = str(self.paths.workshop_tmp / ('depot_' + pubid))
        job.msg = '通过 DepotDownloader 下载中（这条路径没有进度显示）…'
        code = workshop.depot_download(self.settings.depotdownloader, pubid, tmp, self.paths.workshop_tmp / (pubid + '.log'))
        found = []
        for root, _, files in os.walk(tmp):
            for fn in files:
                if fn.lower().endswith('.vpk'):
                    dst = self.paths.addons / (safe_vpk_name(fn) or f'workshop_{pubid}.vpk'); shutil.move(os.path.join(root, fn), dst); found.append(dst.name)
        if not found: raise RuntimeError(f'DepotDownloader 没有下载到 vpk（退出码 {code}，详见 workshop_tmp/{pubid}.log）')
        shutil.rmtree(tmp, ignore_errors=True); el = int(time.time() - t0)
        job.files = found; job.state = 'done'
        job.msg = f'已安装: {", ".join(found)}（用时 {el // 60} 分 {el % 60} 秒） ' + self.refresh()

    # ---- zip for download ----
    def start_zip(self, names, actor: str) -> str:
        names = [n for n in (names or []) if n]
        if not names: raise ApiError(400, '请选择要打包的战役')
        token = secrets.token_urlsafe(12)
        self.jobs.start('zip', token, lambda job: self._zip(token, names, job), initial_msg='打包中…')
        self.audit.add(actor, 'addon.zip', ' '.join(names))
        return token

    def _zip(self, token: str, names, job: Job):
        os.makedirs(self.paths.downloads, exist_ok=True); self.downloads.purge()
        paths = []
        for n in names:
            s = safe_vpk_name(n)
            if s and (self.paths.addons / s).is_file(): paths.append(self.paths.addons / s)
        if not paths: raise RuntimeError('没有有效的 vpk 文件')
        out = self.paths.downloads / (token + '.zip')
        with zipfile.ZipFile(out, 'w', zipfile.ZIP_STORED, allowZip64=True) as z:
            for pth in paths: z.write(pth, pth.name)
            z.writestr('安装说明.txt', INSTALL_NOTE)
        dlname = (paths[0].name[:-4] if len(paths) == 1 else 'l4d2_addons') + '.zip'
        self.downloads.add(token, out, dlname)
        job.name = dlname; job.extra = {'token': token, 'size_mb': round(os.path.getsize(out) / 1048576, 1)}
        job.state, job.msg = 'done', '打包完成'

    def download(self, token):
        """-> (path, download name) of a finished zip; 404 when the token expired."""
        info = self.downloads.get(token)
        if not info: raise ApiError(404, '下载链接已过期，请重新打包')
        return info['path'], info['name']
