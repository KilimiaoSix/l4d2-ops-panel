#!/usr/bin/env python3
"""L4D2 Ops Panel — a single-file web panel for Left 4 Dead 2 dedicated servers (Python 3 stdlib only).

Talks to the game over RCON / A2S, optionally drives LinuxGSM for start/stop, reads logs and a perf CSV,
manages custom campaigns (upload / Steam Workshop download) and integrates with a few SourceMod plugins
when they are present (Private Whitelist, SI Preset, Points System). Everything is configured in panel.json.
"""
import shutil
import json, os, re, ssl, socket, struct, subprocess, threading, time, secrets, sys, glob, sqlite3, hashlib, hmac, zipfile
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, unquote, quote, parse_qsl
from contextlib import closing

DIR = os.path.dirname(os.path.abspath(__file__))
CONF_PATH = os.environ.get('L4D2PANEL_CONFIG') or (sys.argv[sys.argv.index('--config') + 1] if '--config' in sys.argv else os.path.join(DIR, 'panel.json'))
DEFAULTS = {
    'password': '', 'port': 8080, 'bind': '127.0.0.1', 'tls': False, 'cert': 'cert.pem', 'key': 'key.pem', 'session_days': 7,
    'rcon_host': '127.0.0.1', 'rcon_port': 27015, 'rcon_password': '',          # empty rcon_password -> read <game_dir>/cfg/server.cfg
    'game_dir': '/home/l4d2server/serverfiles/left4dead2',
    'lgsm_script': '/home/l4d2server/l4d2server',                             # '' = no server control buttons
    'console_log': '/home/l4d2server/log/console/l4d2server-console.log',
    'perf_csv': '/home/l4d2server/log/perf-samples.csv',
    'depotdownloader': '/home/l4d2server/tools/depotdownloader/DepotDownloader',
    'panel_title': 'L4D2 运维面板', 'display_host': '', 'max_upload_mb': 3072,
    'protected_addons': ['admin_system.vpk'],
    'db': 'panel.db', 'bootstrap_user': 'admin',
    'protected_plugins': ['sourcemod', 'basecommands', 'basetriggers', 'basechat', 'admin-flatfile', 'adminmenu',
                          'sm_whitelist', 'sipreset', 'ps_mapreset', 'l4d2_points_system'],
    'steam_api_base': 'https://api.steampowered.com', 'workshop_connections': 8, 'workshop_retries': 8,   # workshop downloads (ranged, parallel)
    'steam_api_key': '',                                                       # Steam Web API key: enables the workshop search card ('' = hidden)
}
CONF = dict(DEFAULTS)
try:
    CONF.update(json.load(open(CONF_PATH, encoding='utf-8')))
except FileNotFoundError:
    sys.exit(f'config not found: {CONF_PATH} (copy panel.example.json to panel.json or run install.sh)')
# "password" may be empty: the owner account is then created from the first visit (setup page) instead of being seeded here.
def _abs(p): return p if (not p or os.path.isabs(p)) else os.path.join(DIR, p)
GAME = CONF['game_dir']
CONSOLE_LOG = CONF['console_log']; PERF_CSV = CONF['perf_csv']
WHITELIST = os.path.join(GAME, 'addons', 'sourcemod', 'configs', 'whitelist.txt')
SM_LOGS = os.path.join(GAME, 'addons', 'sourcemod', 'logs')
SM_PLUGINS = os.path.join(GAME, 'addons', 'sourcemod', 'plugins')
SM_DISABLED = os.path.join(SM_PLUGINS, 'disabled')
ADMINS_INI = os.path.join(GAME, 'addons', 'sourcemod', 'configs', 'admins_simple.ini')
DB_PATH = _abs(CONF.get('db', 'panel.db'))
DL_DIR = os.path.join(DIR, 'downloads')
PROTECT_PLUGINS = set(CONF.get('protected_plugins', []))
ANSI = re.compile(r'\x1b\[[0-9;]*m')
MAPS = [('c1m1_hotel','1 死亡中心'),('c2m1_highway','2 黑色狂欢节'),('c3m1_plankcountry','3 沼泽激战'),('c4m1_milltown_a','4 暴风骤雨'),
        ('c5m1_waterfront','5 教区'),('c6m1_riverbank','6 牺牲'),('c7m1_docks','7 短暂时刻'),('c8m1_apartment','8 毫不留情'),
        ('c9m1_alleys','9 坠机险途'),('c10m1_caves','10 死亡丧钟'),('c11m1_greenhouse','11 寂静时分'),('c12m1_hilltop','12 血腥收获'),
        ('c13m1_alpinecreek','13 寒冷溪流'),('c14m1_junkyard','14 最后一战')]

def rcon_password():
    if CONF['rcon_password']: return CONF['rcon_password']
    try:
        m = re.search(r'rcon_password\s+"([^"]+)"', open(os.path.join(GAME, 'cfg', 'server.cfg'), encoding='utf-8', errors='replace').read())
        return m.group(1) if m else ''
    except FileNotFoundError:
        return ''

class Rcon:
    lock = threading.Lock()
    @staticmethod
    def _pkt(i, t, body):
        d = struct.pack('<ii', i, t) + body.encode() + b'\x00\x00'
        return struct.pack('<i', len(d)) + d
    @staticmethod
    def _recv(s):
        raw = b''
        while len(raw) < 4:
            c = s.recv(4 - len(raw))
            if not c: raise ConnectionError('RCON connection closed')   # (2026-09-19) was an infinite spin holding the lock when the peer closed
            raw += c
        n = struct.unpack('<i', raw)[0]; d = b''
        while len(d) < n:
            c = s.recv(n - len(d))
            if not c: raise ConnectionError('RCON connection closed')
            d += c
        i, t = struct.unpack('<ii', d[:8]); return i, t, d[8:-2].decode('utf-8', 'replace')
    @classmethod
    def run(cls, cmd, timeout=6):
        with cls.lock:
            s = socket.create_connection((CONF['rcon_host'], int(CONF['rcon_port'])), timeout=timeout)
            try:
                s.sendall(cls._pkt(1, 3, rcon_password()))
                i, t, _ = cls._recv(s)
                if t == 0: i, t, _ = cls._recv(s)          # servers send an empty RESPONSE_VALUE before the auth reply
                if i == -1: raise RuntimeError('RCON 密码错误')
                s.sendall(cls._pkt(2, 2, cmd)); s.sendall(cls._pkt(3, 2, ''))   # empty EXEC as terminator: replies come back in order
                out = ''
                while True:
                    i, t, b = cls._recv(s)
                    if i == 3: break
                    out += b
            finally:
                s.close()
        # drop server-log echo and cvar-change chatter; keep the actual command output
        noise = re.compile(r'^(L \d\d/\d\d/\d{4} - [\d:]+:|\[SM\] (更改|Changed) cvar|server_cvar:)')
        lines = [l for l in out.splitlines() if l.strip() and not noise.match(l.strip())]
        return '\n'.join(lines).strip()

def _a2s_once(timeout=1.5):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.settimeout(timeout)
    req = b'\xFF\xFF\xFF\xFFTSource Engine Query\x00'
    try:
        addr = (CONF['rcon_host'], int(CONF['rcon_port']))
        s.sendto(req, addr); d, _ = s.recvfrom(4096)
        if d[4:5] == b'A': s.sendto(req + d[5:9], addr); d, _ = s.recvfrom(4096)
        p = 6; f = []
        for _ in range(4):
            e = d.index(b'\x00', p); f.append(d[p:e].decode('utf-8', 'replace')); p = e + 1
        A2S_CACHE.update(name=f[0], map=f[1], max=d[p+3])
        return {'online': True, 'name': f[0], 'map': f[1], 'players': d[p+2], 'max': d[p+3], 'bots': d[p+4]}
    finally:
        s.close()

A2S_CACHE = {}
def a2s():
    # (2026-09-19) L4D2 rate-limits A2S; a public server is scanned constantly, so a single
    # query often lands in a throttled window and times out -> the panel used to cry
    # "游戏未响应" while the game was fine. Retry a few times; the status handler additionally
    # falls back to RCON when this still fails.
    for i in range(3):
        try:
            return _a2s_once(1.5)
        except Exception:
            if i < 2: time.sleep(0.35)
    return {'online': False}

def tail(path, n):
    try:
        with open(path, 'rb') as f:
            f.seek(0, 2); size = f.tell(); block = min(size, 65536 * max(1, n // 200))
            f.seek(size - block); data = f.read().decode('utf-8', 'replace')
        return [ANSI.sub('', l) for l in data.splitlines()[-n:]]
    except FileNotFoundError:
        return []

def sysinfo():
    try:
        load = open('/proc/loadavg').read().split()[:3]
        mem = {}
        for l in open('/proc/meminfo'):
            k, v = l.split(':'); mem[k] = int(v.split()[0])
        up = float(open('/proc/uptime').read().split()[0])
        return {'load': ' '.join(load), 'mem_used_mb': (mem['MemTotal'] - mem['MemAvailable']) // 1024, 'mem_total_mb': mem['MemTotal'] // 1024, 'uptime_h': round(up / 3600, 1)}
    except Exception:
        return {}

ACTION = {'running': None, 'last': ''}
def lgsm(action):
    def work():
        ACTION['running'] = action
        try:
            env = dict(os.environ, TERM='screen', PATH='/usr/local/bin:/usr/bin:/bin')
            script = CONF['lgsm_script']; r = subprocess.run([script, action], cwd=os.path.dirname(script), env=env, capture_output=True, text=True, timeout=240)
            ACTION['last'] = f'{time.strftime("%H:%M:%S")} {action}: ' + ANSI.sub('', (r.stdout + r.stderr)).strip().splitlines()[-1:][0] if (r.stdout + r.stderr).strip() else f'{action} done'
        except Exception as e:
            ACTION['last'] = f'{action} 失败: {e}'
        finally:
            ACTION['running'] = None
    if ACTION['running']: return False
    threading.Thread(target=work, daemon=True).start(); return True

def players():
    out = Rcon.run('status'); res = []
    for l in out.splitlines():
        m = re.match(r'^#\s*(\d+)\s+"(.*)"\s+(STEAM_\S+|BOT)\s+(\S+)\s+(\d+)\s+(\d+)\s+(\w+)', l)
        if m: res.append({'userid': m.group(1), 'name': m.group(2), 'steamid': m.group(3), 'time': m.group(4), 'ping': m.group(5), 'loss': m.group(6), 'state': m.group(7)})
    return res, out

def read_whitelist():
    try: return [l.rstrip('\n') for l in open(WHITELIST, encoding='utf-8', errors='replace') if l.strip() and not l.strip().startswith('//')]
    except FileNotFoundError: return []


ADDONS = os.path.join(GAME, 'addons')
PROTECTED = set(CONF['protected_addons'])
JOBS = {}   # workshop download jobs: id -> {state, msg, files, name, done, total, speed}

def vpk_entries(path):
    """Return list of file paths inside a VPK directory (v1/v2), best effort."""
    out = []
    try:
        with open(path, 'rb') as f:
            sig, ver, tree = struct.unpack('<III', f.read(12))
            if sig != 0x55aa1234: return out
            f.seek(12 if ver == 1 else 28)
            def cstr():
                b = bytearray()
                while True:
                    c = f.read(1)
                    if not c or c == b'\x00': return b.decode('utf-8', 'replace')
                    b += c
            while True:
                ext = cstr()
                if not ext: break
                while True:
                    d = cstr()
                    if not d: break
                    while True:
                        n = cstr()
                        if not n: break
                        crc, pre, ai, off, ln, term = struct.unpack('<IHHIIH', f.read(18)); f.read(pre)
                        out.append((d + '/' if d != ' ' else '') + n + '.' + ext)
    except Exception:
        pass
    return out

VPK_MAGIC = b'\x34\x12\xaa\x55'
def vpk_summary(path):
    """What a vpk holds: its campaign maps, its mission file, and a one-line description of the contents for the 'not a map' message."""
    ents = vpk_entries(path)
    maps = sorted(e.split('/')[-1][:-4] for e in ents if e.startswith('maps/') and e.endswith('.bsp'))
    mission = next((e.split('/')[-1][:-4] for e in ents if e.startswith('missions/') and e.endswith('.txt')), '')
    tops = sorted(set(e.split('/')[0] + '/' if '/' in e else e for e in ents))
    kind = f'{len(ents)} 个文件：' + '、'.join(tops[:5]) + ('…' if len(tops) > 5 else '') if ents else '解析不到任何文件'
    return {'maps': maps, 'mission': mission, 'kind': kind}

def addon_info(name):
    path = os.path.join(ADDONS, name); s = vpk_summary(path)
    return {'name': name, 'size_mb': round(os.path.getsize(path) / 1048576, 1), 'maps': s['maps'], 'mission': s['mission'], 'protected': name in PROTECTED}

def list_addons():
    return [addon_info(n) for n in sorted(os.listdir(ADDONS)) if n.lower().endswith('.vpk')]

def safe_vpk_name(n, exts=('.vpk',)):
    n = os.path.basename(n).strip()
    n = re.sub(r'[^\w.\-一-鿿 ]', '_', n)
    return n if n.lower().endswith(exts) and len(n) > 4 else None

def install_vpk(src, name):
    """The one gate every install path goes through (upload, zip, workshop, DepotDownloader): move src to addons/<name>
    only if it is a VPK that actually contains maps. Anything else (skins, sounds, scripts, junk) is deleted and reported."""
    try:
        if name in PROTECTED: raise ValueError(f'{name} 是受保护的文件，不能覆盖')
        with open(src, 'rb') as f: magic = f.read(4)
        if magic != VPK_MAGIC: raise ValueError(f'{name} 不是有效的 VPK 文件')
        s = vpk_summary(src)
        if not s['maps']: raise ValueError(f'{name} 里没有地图（maps/*.bsp），不是战役文件，已丢弃。内容：{s["kind"]}')
    except ValueError:
        os.remove(src); raise
    final = os.path.join(ADDONS, name)
    try: os.replace(src, final)
    except OSError: shutil.move(src, final)
    return addon_info(name)

def install_zip(path):
    """Install every campaign vpk inside a zip (what gamemaps.com serves), ignore the rest. Returns {'installed': [addon_info], 'skipped': [{'name', 'reason'}]}."""
    installed, skipped, seen = [], [], []
    try:
        with zipfile.ZipFile(path) as z:
            for zi in z.infolist():
                base = os.path.basename(zi.filename)
                if zi.is_dir() or not base or zi.filename.startswith('__MACOSX/'): continue
                seen.append(base)
                if not base.lower().endswith('.vpk'): continue
                if zi.file_size > int(CONF['max_upload_mb']) * 1048576: skipped.append({'name': base, 'reason': f'超过 {CONF["max_upload_mb"]}MB'}); continue
                name = safe_vpk_name(base)
                if not name: continue
                tmp = os.path.join(ADDONS, name + '.uploading')
                try:
                    with z.open(zi) as src, open(tmp, 'wb') as dst: shutil.copyfileobj(src, dst, 1048576)
                    installed.append(install_vpk(tmp, name))
                except ValueError as e: skipped.append({'name': base, 'reason': str(e)})
                except Exception as e:
                    if os.path.exists(tmp): os.remove(tmp)
                    skipped.append({'name': base, 'reason': f'解压失败: {e}'})
    except zipfile.BadZipFile:
        raise ValueError('不是有效的 zip 文件（rar / 7z 请先解压出 .vpk 再上传）')
    finally:
        os.remove(path)
    if not installed:
        if skipped: raise ValueError('压缩包里的 vpk 都不能安装：' + '；'.join(s['reason'] for s in skipped))
        raise ValueError('压缩包里没有 .vpk 文件' + ('（内容：' + '、'.join(seen[:8]) + ('…' if len(seen) > 8 else '') + '）' if seen else '（空压缩包）'))
    return {'installed': installed, 'skipped': skipped}

def refresh_addons():
    try: return Rcon.run('update_addon_paths') + '\n' + Rcon.run('mission_reload')
    except Exception as e: return f'(热加载失败: {e}，重启服务器后生效)'

# ---- Steam Workshop download (2026-09-22): Web API -> file_url -> parallel ranged HTTP, resumable ----
# L4D2 workshop items are plain UGC files on an Akamai CDN. From a Chinese cloud host one connection gets anywhere
# between ~1 and 20 Mbps depending on the edge DNS hands out, and DepotDownloader fetched the whole file with ONE GET
# (no retry, no resume), so 800 MB campaigns kept dying at the old 30-minute cap. This downloads 8 MB ranges over
# several connections, retries each range on its own and keeps finished ranges on disk, so a failed or cancelled job
# continues where it stopped. DepotDownloader is only used for depot-based items (no file_url).
WS_TMP = os.path.join(DIR, 'workshop_tmp')
WS_CHUNK = 8 * 1048576
def _wslog(pubid, msg):
    try:
        os.makedirs(WS_TMP, exist_ok=True)
        with open(os.path.join(WS_TMP, pubid + '.log'), 'a', encoding='utf-8') as f: f.write(time.strftime('%Y-%m-%d %H:%M:%S ') + msg + '\n')
    except Exception: pass

def steam_pubfile_details(pubid):
    import urllib.request, urllib.parse
    req = urllib.request.Request(CONF['steam_api_base'].rstrip('/') + '/ISteamRemoteStorage/GetPublishedFileDetails/v1/',
                                 data=urllib.parse.urlencode({'itemcount': 1, 'publishedfileids[0]': pubid}).encode(), headers={'User-Agent': 'l4d2panel'})
    with urllib.request.urlopen(req, timeout=20) as r:
        lst = json.loads(r.read().decode('utf-8', 'replace'))['response'].get('publishedfiledetails') or []
    if not lst: raise RuntimeError('Steam 没有返回这个物品')
    return lst[0]

def _range_get(url, start, end, fd, stop, bump, min_rate=0):
    """GET one byte range straight into fd at its offset; bump(n) reports bytes as they land. Raises unless the whole range arrived."""
    import urllib.request
    req = urllib.request.Request(url, headers={'Range': f'bytes={start}-{end}', 'User-Agent': 'l4d2panel'})
    with urllib.request.urlopen(req, timeout=30) as r:
        if r.status != 206: raise RuntimeError(f'HTTP {r.status}（CDN 不支持 Range）')
        want = end - start + 1; got = 0; t0 = time.time()
        while got < want:
            if stop(): raise RuntimeError('已取消')
            piece = r.read(min(262144, want - got))
            if not piece: raise RuntimeError(f'连接提前断开（{got}/{want} 字节）')
            os.pwrite(fd, piece, start + got); got += len(piece); bump(len(piece))
            el = time.time() - t0
            if min_rate and el > 15 and got / el < min_rate: raise RuntimeError(f'太慢（{got / el / 1024:.0f} KB/s），换个连接重试')

def download_ranged(pubid, url, size, dest, job):
    """Parallel ranged download of url into dest, progress in job. Finished ranges are recorded in dest + '.parts.json' so a rerun resumes."""
    from concurrent.futures import ThreadPoolExecutor
    state_path = dest + '.parts.json'; n = (size + WS_CHUNK - 1) // WS_CHUNK
    def csize(i): return min(size, (i + 1) * WS_CHUNK) - i * WS_CHUNK
    done = set()
    try:
        st = json.load(open(state_path))
        if st.get('url') == url and st.get('size') == size and os.path.getsize(dest) == size: done = set(int(i) for i in st['done'])
    except Exception: pass
    if not done:
        with open(dest, 'wb') as f: f.truncate(size)
    job.update(total=size, done=sum(csize(i) for i in done), speed=0.0)
    lock = threading.Lock(); hist = [(time.time(), job['done'])]; meta = {'t': 0.0, 'err': ''}
    def stop(): return bool(job.get('cancel') or meta['err'])
    def bump(nb):
        with lock:
            job['done'] += nb; now = time.time(); hist.append((now, job['done']))
            while len(hist) > 2 and now - hist[0][0] > 15: hist.pop(0)
            if now - meta['t'] >= 0.5:
                meta['t'] = now; job['speed'] = max(0.0, (job['done'] - hist[0][1]) / max(0.001, now - hist[0][0]))
                job['msg'] = f"{job['name']} {job['done'] / 1048576:.1f}/{size / 1048576:.1f} MB ({100 * job['done'] // size}%) {job['speed'] / 1048576:.1f} MB/s"
    fd = os.open(dest, os.O_RDWR)
    try:
        def fetch(i):
            s = i * WS_CHUNK; e = s + csize(i) - 1; last = ''
            for attempt in range(1, int(CONF['workshop_retries']) + 1):
                if stop(): return
                acc = {'n': 0}
                def bump_acc(nb): acc['n'] += nb; bump(nb)
                try:
                    _range_get(url, s, e, fd, stop, bump_acc, min_rate=150 * 1024 if attempt <= 2 else 0)
                    with lock:
                        done.add(i); tmp_ = state_path + '.tmp'
                        with open(tmp_, 'w') as f: json.dump({'url': url, 'size': size, 'done': sorted(done)}, f)
                        os.replace(tmp_, state_path)
                    return
                except Exception as ex:
                    last = str(ex); bump(-acc['n'])   # this range will be fetched again from its start
                    if last == '已取消' or stop(): return
                    _wslog(pubid, f'块 {i + 1}/{n} 第 {attempt} 次失败: {last}')
                    time.sleep(min(15, 2 * attempt))
            meta['err'] = meta['err'] or f'块 {i + 1}/{n} 重试 {CONF["workshop_retries"]} 次仍失败（{last}）'
        with ThreadPoolExecutor(max_workers=max(1, int(CONF['workshop_connections']))) as ex:
            list(ex.map(fetch, [i for i in range(n) if i not in done]))
    finally:
        os.close(fd)
    if job.get('cancel'): raise RuntimeError('已取消')
    if meta['err']: raise RuntimeError(meta['err'])
    if len(done) != n: raise RuntimeError('下载不完整')
    os.remove(state_path)

def _depot_job(pubid, job, t0):
    """Fallback for items without a direct file_url: DepotDownloader into workshop_tmp/depot_<id> (kept on failure so it can resume)."""
    tmp = os.path.join(WS_TMP, 'depot_' + pubid); os.makedirs(tmp, exist_ok=True)
    job['msg'] = '通过 DepotDownloader 下载中（这条路径没有进度显示）…'
    with open(os.path.join(WS_TMP, pubid + '.log'), 'a', encoding='utf-8') as lf:
        r = subprocess.run([CONF['depotdownloader'], '-app', '550', '-pubfile', pubid, '-dir', tmp], stdout=lf, stderr=subprocess.STDOUT, text=True, timeout=6 * 3600)
    found, bad = [], []
    for root, _, files in os.walk(tmp):
        for fn in files:
            if fn.lower().endswith('.vpk'):
                try: found.append(install_vpk(os.path.join(root, fn), safe_vpk_name(fn) or f'workshop_{pubid}.vpk')['name'])
                except ValueError as e: bad.append(str(e))
    if not found: raise RuntimeError('；'.join(bad) or f'DepotDownloader 没有下载到 vpk（退出码 {r.returncode}，详见 workshop_tmp/{pubid}.log）')
    shutil.rmtree(tmp, ignore_errors=True); el = int(time.time() - t0)
    job.update(state='done', files=found, msg=f'已安装: {", ".join(found)}（用时 {el // 60} 分 {el % 60} 秒） ' + refresh_addons())

def workshop_job(pubid):
    job = JOBS[pubid] = {'state': 'running', 'msg': '正在查询创意工坊…', 'files': [], 'name': '', 'done': 0, 'total': 0, 'speed': 0.0}
    t0 = time.time(); _wslog(pubid, '开始'); dest = os.path.join(WS_TMP, pubid + '.part')
    has_depot = bool(CONF['depotdownloader']) and os.path.exists(CONF['depotdownloader'])
    try:
        try: d = steam_pubfile_details(pubid)
        except Exception as e:
            _wslog(pubid, f'Steam Web API 失败: {e}')
            if has_depot: return _depot_job(pubid, job, t0)
            raise RuntimeError(f'查询 Steam Web API 失败（{e}），且没有 DepotDownloader 可回退')
        if int(d.get('result', 0)) != 1: raise RuntimeError(f'创意工坊没有这个物品（result={d.get("result")}，可能已删除或设为私有）')
        if int(d.get('consumer_app_id', 550)) != 550: raise RuntimeError('这不是 Left 4 Dead 2 的创意工坊物品')
        if int(d.get('file_type', 0)) == 2: raise RuntimeError('这是一个合集，请分别下载里面的每个物品')
        url = d.get('file_url') or ''; size = int(d.get('file_size') or 0)
        job['name'] = safe_vpk_name(d.get('filename') or '') or f'workshop_{pubid}.vpk'; job['title'] = d.get('title', '')
        if not url or not size:
            if int(d.get('hcontent_file') or 0) and has_depot: return _depot_job(pubid, job, t0)
            raise RuntimeError('这个物品没有可直接下载的文件' + ('，需要 DepotDownloader 才能下载' if int(d.get('hcontent_file') or 0) else ''))
        _wslog(pubid, f'{job["title"]} -> {job["name"]} {size} 字节 {url}')
        os.makedirs(WS_TMP, exist_ok=True); job['msg'] = f'开始下载 {job["name"]}（{size / 1048576:.1f} MB）'
        download_ranged(pubid, url, size, dest, job)
        try: install_vpk(dest, job['name'])   # deletes dest when the item is not a campaign
        except ValueError as e: raise RuntimeError(str(e))
        el = int(time.time() - t0)
        job.update(state='done', files=[job['name']], msg=f'已安装: {job["name"]}（{size / 1048576:.1f} MB，用时 {el // 60} 分 {el % 60} 秒） ' + refresh_addons())
        _wslog(pubid, job['msg'])
    except Exception as e:
        kept = os.path.exists(dest)
        job.update(state='error', msg=('已取消' if str(e) == '已取消' else f'下载失败: {e}') + ('；已下载的部分已保留，再点一次“下载安装”会接着下' if kept else ''))
        _wslog(pubid, job['msg'])

def steam_query_files(q, page=1, per=20):
    """Search L4D2 workshop campaigns (IPublishedFileService/QueryFiles, tag 'Campaigns'): text search when q is given,
    else most-subscribed. Needs a Steam Web API key (free, https://steamcommunity.com/dev/apikey); the key never leaves the server."""
    import urllib.request, urllib.parse, urllib.error
    if not CONF['steam_api_key']: raise ValueError('没有配置 steam_api_key（panel.json），无法搜索创意工坊')
    params = {'key': CONF['steam_api_key'], 'appid': 550, 'creator_appid': 550, 'requiredtags[0]': 'Campaigns', 'page': page, 'numperpage': per,
              'query_type': 12 if q else 9, 'return_metadata': 1, 'return_tags': 1, 'return_vote_data': 1, 'return_short_description': 1}
    if q: params['search_text'] = q
    req = urllib.request.Request(CONF['steam_api_base'].rstrip('/') + '/IPublishedFileService/QueryFiles/v1/?' + urllib.parse.urlencode(params), headers={'User-Agent': 'l4d2panel'})
    try:
        with urllib.request.urlopen(req, timeout=20) as r: resp = json.loads(r.read().decode('utf-8', 'replace')).get('response') or {}
    except urllib.error.HTTPError as e:
        if e.code in (401, 403): raise RuntimeError('Steam 拒绝了这个 API Key（检查 panel.json 里的 steam_api_key）')
        raise RuntimeError(f'Steam Web API 返回 HTTP {e.code}')
    except ValueError:
        raise RuntimeError('Steam Web API 返回了无法解析的内容')
    items = []
    for d in resp.get('publishedfiledetails') or []:
        if int(d.get('result', 1)) != 1: continue
        items.append({'id': str(d.get('publishedfileid', '')), 'title': d.get('title', ''), 'size_mb': round(int(d.get('file_size') or 0) / 1048576, 1),
                      'subs': int(d.get('subscriptions') or 0), 'updated': int(d.get('time_updated') or 0), 'preview': d.get('preview_url', ''),
                      'tags': [t.get('tag', '') for t in d.get('tags') or [] if t.get('tag') != 'Campaigns'],
                      'score': round(float((d.get('vote_data') or {}).get('score') or 0), 2), 'desc': (d.get('short_description') or '')[:200]})
    return {'items': items, 'total': int(resp.get('total') or 0), 'page': page}

FEAT = {'t': 0, 'v': {}}
def features(online):
    """Which optional parts are available: detected from installed SourceMod plugins + local tools (cached 120 s)."""
    now = time.time()
    if now - FEAT['t'] < 120 and FEAT['v']: return FEAT['v']
    f = {'lgsm': bool(CONF['lgsm_script']) and os.path.exists(CONF['lgsm_script']),
         'workshop': True,   # Web API + ranged HTTP download; DepotDownloader is only a fallback
         'workshop_search': bool(CONF['steam_api_key']),
         'console_log': bool(CONSOLE_LOG) and os.path.exists(CONSOLE_LOG), 'perf': bool(PERF_CSV) and os.path.exists(PERF_CSV),
         'sourcemod': False, 'whitelist': False, 'preset': False, 'points': False}
    if online:
        try:
            names = Rcon.run('sm plugins list').lower()
            f['sourcemod'] = 'listing' in names or 'plugins' in names
            f['whitelist'] = 'private whitelist' in names; f['preset'] = 'si preset' in names; f['points'] = 'points system' in names
        except Exception:
            pass
        FEAT['t'] = now; FEAT['v'] = f
    return f

# ---- SQLite: panel accounts / sessions / audit (2026-09-19) ----
DB_LOCK = threading.Lock()
def db():
    c = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)   # autocommit; DB_LOCK serialises writers
    c.row_factory = sqlite3.Row
    try: c.execute('PRAGMA journal_mode=WAL')
    except Exception: pass
    return c
def hash_pw(pw, salt=None, it=200000):
    salt = salt or secrets.token_hex(16)
    return f'pbkdf2${it}${salt}$' + hashlib.pbkdf2_hmac('sha256', pw.encode(), bytes.fromhex(salt), it).hex()
def verify_pw(pw, stored):
    try:
        _a, it, salt, h = stored.split('$')
        return hmac.compare_digest(hashlib.pbkdf2_hmac('sha256', pw.encode(), bytes.fromhex(salt), int(it)).hex(), h)
    except Exception:
        return False
def db_init():
    with DB_LOCK, closing(db()) as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS accounts(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, pass TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'admin', steamid TEXT, flags TEXT DEFAULT '99:z', note TEXT, created INTEGER, last_login INTEGER);
        CREATE TABLE IF NOT EXISTS sessions(sid TEXT PRIMARY KEY, account_id INTEGER, expires INTEGER);
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, ts INTEGER, who TEXT, action TEXT, detail TEXT);''')
        if not c.execute('SELECT COUNT(*) FROM accounts').fetchone()[0]:
            u = CONF.get('bootstrap_user', 'admin')
            if CONF['password']:
                c.execute('INSERT INTO accounts(username,pass,role,created) VALUES(?,?,?,?)', (u, hash_pw(CONF['password']), 'owner', int(time.time())))
                print(f'[panel] seeded owner account "{u}" from panel.json password (change it in the 账号 tab)', flush=True)
            else:
                print(f'[panel] no accounts yet: the first visit to the panel sets the password of "{u}"', flush=True)
        c.execute('DELETE FROM sessions WHERE expires<?', (int(time.time()),))
    try: os.chmod(DB_PATH, 0o600)
    except Exception: pass
def setup_needed():
    with DB_LOCK, closing(db()) as c: return c.execute('SELECT COUNT(*) FROM accounts').fetchone()[0] == 0
def audit(who, action, detail=''):
    try:
        with DB_LOCK, closing(db()) as c: c.execute('INSERT INTO audit(ts,who,action,detail) VALUES(?,?,?,?)', (int(time.time()), who, action, str(detail)[:400]))
    except Exception: pass
def sess_new(account_id):
    sid = secrets.token_urlsafe(32)
    with DB_LOCK, closing(db()) as c: c.execute('INSERT INTO sessions(sid,account_id,expires) VALUES(?,?,?)', (sid, account_id, int(time.time()) + int(CONF['session_days']) * 86400))
    return sid
def cookie_sid(h):
    m = re.search(r'(?:^|;\s*)l4d2panel=([A-Za-z0-9_-]+)', h.headers.get('Cookie', ''))
    return m.group(1) if m else None
def sess_get(h):
    sid = cookie_sid(h)
    if not sid: return None
    with DB_LOCK, closing(db()) as c:
        return c.execute('SELECT a.* FROM sessions s JOIN accounts a ON a.id=s.account_id WHERE s.sid=? AND s.expires>?', (sid, int(time.time()))).fetchone()
def sess_del(h):
    sid = cookie_sid(h)
    if sid:
        with DB_LOCK, closing(db()) as c: c.execute('DELETE FROM sessions WHERE sid=?', (sid,))
db_init(); FAILS = {}
def client_ip(h):
    return (h.headers.get('X-Real-IP', '').strip() or h.client_address[0])   # X-Real-IP is set by nginx from $remote_addr

def check_session(h): return sess_get(h) is not None

def q(s): return '"' + s.replace('"', '') + '"'

# ---- Steam identity parsing: accept SteamID / SteamID3 / SteamID64 / profile URL / vanity ----
STEAMID64_BASE = 76561197960265728
def _from_accountid(acc):
    if acc < 0: raise ValueError('不是有效的 Steam 账号')
    return f'STEAM_1:{acc & 1}:{acc >> 1}'   # L4D2 reports universe 1; match that
def resolve_vanity(vanity):
    import urllib.request
    try:
        with urllib.request.urlopen('https://steamcommunity.com/id/' + quote(vanity) + '/?xml=1', timeout=6) as r:
            m = re.search(r'<steamID64>(\d{17})</steamID64>', r.read().decode('utf-8', 'replace'))
            return m.group(1) if m else None
    except Exception:
        return None
def parse_steamid(raw):
    """Return a canonical STEAM_1:Y:Z, or '' for blank input; raise ValueError with a helpful message."""
    s = str(raw or '').strip()
    if not s: return ''
    m = re.fullmatch(r'STEAM_[0-5]:([01]):(\d+)', s, re.I)
    if m: return f'STEAM_1:{m.group(1)}:{m.group(2)}'
    m = re.fullmatch(r'\[?U:1:(\d+)\]?', s, re.I)
    if m: return _from_accountid(int(m.group(1)))
    u = re.search(r'/profiles/(\d{17})', s)
    if u: s = u.group(1)
    if re.fullmatch(r'\d{17}', s): return _from_accountid(int(s) - STEAMID64_BASE)
    v = re.search(r'/id/([^/?#]+)', s)
    vanity = v.group(1) if v else (s if re.fullmatch(r'[A-Za-z0-9_.\-]{2,64}', s) else None)
    if vanity:
        id64 = resolve_vanity(vanity)
        if id64: return _from_accountid(int(id64) - STEAMID64_BASE)
        raise ValueError('无法解析自定义主页链接（服务器可能连不上 steamcommunity.com）；请改用 SteamID、17 位好友码，或 /profiles/数字 链接')
    raise ValueError('无法识别的 Steam 标识')

# ---- SourceMod admin binding: maintain a panel-owned block in admins_simple.ini ----
# Markers use // (SourceMod's SMC/KeyValues line-comment); the regex also matches a legacy ; block.
ADM_BEGIN = '// ==== panel-managed BEGIN (the web panel maintains this block; do not edit inside) ===='
ADM_END = '// ==== panel-managed END ===='
ADM_BLOCK_RE = re.compile(r'(?://|;) ==== panel-managed BEGIN.*?(?://|;) ==== panel-managed END[^\n]*', re.S)
def sync_sm_admins():
    with DB_LOCK, closing(db()) as c:
        rows = c.execute("SELECT id,username,steamid,flags FROM accounts WHERE steamid IS NOT NULL AND steamid<>''").fetchall()
    lines = [ADM_BEGIN]
    for r in rows:
        cmt = re.sub(r'[^\x20-\x7e]', '?', r['username'] or '').replace('\\', '')
        lines.append(f'"{r["steamid"]}" "{r["flags"] or "99:z"}"    // panel#{r["id"]} {cmt}')
    lines.append(ADM_END)
    block = '\n'.join(lines)
    try: txt = open(ADMINS_INI, encoding='utf-8', errors='replace').read()
    except FileNotFoundError: txt = ''
    if ADM_BLOCK_RE.search(txt):
        txt = ADM_BLOCK_RE.sub(lambda _: block, txt, count=1)
    else:
        txt = (txt.rstrip() + '\n\n' + block + '\n') if txt.strip() else (block + '\n')
    tmp = ADMINS_INI + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f: f.write(txt)
    os.replace(tmp, ADMINS_INI)
    try: return Rcon.run('sm_reloadadmins') or 'admin cache reloaded'
    except Exception as e: return f'(已写入，reload 失败: {e})'

# ---- SourceMod plugin manager ----
def plugin_name(n):
    n = os.path.basename(str(n)).strip()
    if n.endswith('.smx'): n = n[:-4]
    return n if re.match(r'^[\w.\-]+$', n) else None
def list_plugins():
    def scan(d):
        try: return sorted(f for f in os.listdir(d) if f.endswith('.smx'))
        except FileNotFoundError: return []
    raw = ''
    try: raw = Rcon.run('sm plugins list')
    except Exception: pass
    return {'enabled': [{'file': f, 'protected': f[:-4] in PROTECT_PLUGINS} for f in scan(SM_PLUGINS)],
            'disabled': [{'file': f} for f in scan(SM_DISABLED)], 'raw': raw}
def plugin_action(op, file):
    nm = plugin_name(file)
    if not nm: raise ValueError('无效的插件名')
    fn = nm + '.smx'; en = os.path.join(SM_PLUGINS, fn); di = os.path.join(SM_DISABLED, fn)
    if op == 'reload':
        return Rcon.run('sm plugins reload ' + nm)
    if op == 'disable':
        if nm in PROTECT_PLUGINS: raise ValueError('该插件受保护，不能禁用')
        if not os.path.exists(en): raise ValueError('插件不在启用目录')
        os.makedirs(SM_DISABLED, exist_ok=True)
        out = ''
        try: out = Rcon.run('sm plugins unload ' + nm)
        except Exception: pass
        os.replace(en, di); return (out + ' — 已移入 disabled/').strip()
    if op == 'enable':
        if not os.path.exists(di): raise ValueError('插件不在禁用目录')
        os.replace(di, en)
        try: return Rcon.run('sm plugins load ' + nm) + ' — 已启用'
        except Exception as e: return f'已移入 plugins/，加载失败（换图或重启后生效）: {e}'
    if op == 'delete':
        if nm in PROTECT_PLUGINS: raise ValueError('该插件受保护，不能删除')
        if os.path.exists(di): os.remove(di); return '已删除禁用的插件 ' + fn
        raise ValueError('只能删除已禁用的插件（先禁用再删）')
    raise ValueError('bad op')

# ---- addon -> downloadable zip ----
ZIPS = {}   # token -> {state, msg, ...}
DLS = {}    # token -> {path, name, expires}
INSTALL_NOTE = ('把压缩包里的 .vpk 放到 Left 4 Dead 2\\left4dead2\\addons\\ 目录，重启游戏后在“附加组件”里启用即可。\n'
                '服务器和所有玩家需要装同一个战役才能一起玩。\n')
def _clean_downloads():
    now = time.time()
    for t, v in list(DLS.items()):
        if v['expires'] < now:
            try: os.remove(v['path'])
            except Exception: pass
            DLS.pop(t, None)
def zip_job(token, names):
    ZIPS[token] = {'state': 'running', 'msg': '打包中…'}
    try:
        os.makedirs(DL_DIR, exist_ok=True); _clean_downloads()
        paths = []
        for n in names:
            s = safe_vpk_name(n)
            if s and os.path.isfile(os.path.join(ADDONS, s)): paths.append(os.path.join(ADDONS, s))
        if not paths: raise RuntimeError('没有有效的 vpk 文件')
        out = os.path.join(DL_DIR, token + '.zip')
        with zipfile.ZipFile(out, 'w', zipfile.ZIP_STORED, allowZip64=True) as z:
            for pth in paths: z.write(pth, os.path.basename(pth))
            z.writestr('安装说明.txt', INSTALL_NOTE)
        dlname = (os.path.basename(paths[0])[:-4] if len(paths) == 1 else 'l4d2_addons') + '.zip'
        DLS[token] = {'path': out, 'name': dlname, 'expires': time.time() + 3600}
        ZIPS[token] = {'state': 'done', 'msg': '打包完成', 'token': token, 'name': dlname, 'size_mb': round(os.path.getsize(out) / 1048576, 1)}
    except Exception as e:
        ZIPS[token] = {'state': 'error', 'msg': str(e)}

# ---- cached game flags (preset / whitelist / difficulty): 15s cache cuts RCON churn and,
#      crucially, keeps last-good values so one flaky RCON call doesn't blank the tiles ----
GS = {'t': 0, 'preset': '', 'whitelist': None, 'difficulty': '', 'ff': None, 'burn': None}
def game_flags(online, fe):
    if online and time.time() - GS['t'] >= 15:
        if fe.get('preset'):
            try:
                m = re.search(r'当前: (\w+)', Rcon.run('sm_preset'))
                if m: GS['preset'] = m.group(1)
            except Exception: pass
        if fe.get('whitelist'):
            try:
                w = re.search(r'"sm_whitelist_enable"[^"]*"(\d)"', Rcon.run('sm_cvar sm_whitelist_enable'))
                if w: GS['whitelist'] = (w.group(1) == '1')
            except Exception: pass
        try:
            dd = re.search(r'"z_difficulty" = "(\w+)"', Rcon.run('z_difficulty'))
            if dd: GS['difficulty'] = dd.group(1).lower()
        except Exception: pass
        # damage factors: all four difficulty variants are kept equal by /api/damage,
        # so the expert one is representative whatever the current difficulty is
        for key, cv in (('ff', 'survivor_friendly_fire_factor_expert'), ('burn', 'survivor_burn_factor_expert')):
            try:
                m = re.search(r'"%s" = "([0-9.]+)"' % cv, Rcon.run(cv))
                if m: GS[key] = float(m.group(1))
            except Exception: pass
        GS['t'] = time.time()
    return {'preset': GS['preset'], 'whitelist': GS['whitelist'], 'difficulty': GS['difficulty'], 'ff': GS['ff'], 'burn': GS['burn']}

DAMAGE_CVARS = {
    'ff':   ['survivor_friendly_fire_factor_' + d for d in ('easy', 'normal', 'hard', 'expert')],
    'burn': ['survivor_burn_factor_' + d          for d in ('easy', 'normal', 'hard', 'expert')],
}

def persist_cvars(pairs):
    """Write name/value pairs into <game>/cfg/server.cfg so a restart keeps them.
    Replaces an existing line (with or without the sm_cvar prefix), otherwise appends.
    Read/written as latin-1 so the round trip is byte-exact whatever the file holds;
    the lines this adds are pure ASCII (the engine chokes on multibyte characters)."""
    cfg = os.path.join(GAME, 'cfg', 'server.cfg')
    text = open(cfg, encoding='latin-1').read()
    shutil.copy(cfg, cfg + '.bak-panel-' + time.strftime('%Y%m%d-%H%M%S'))
    for name, val in pairs:
        line = f'sm_cvar {name} {val}'
        pat = re.compile(r'^[ \t]*(?:sm_cvar[ \t]+)?' + re.escape(name) + r'[ \t]+\S.*$', re.M)
        text, n = pat.subn(line, text, count=1)
        if n == 0:
            text = text.rstrip('\n') + '\n' + line + '\n'
    open(cfg, 'w', encoding='latin-1').write(text)

class H(BaseHTTPRequestHandler):
    server_version = 'l4d2panel/1.0'
    def log_message(self, fmt, *a):
        if '/api/status' not in (a[0] if a else ''): super().log_message(fmt, *a)
    def send_json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code); self.send_header('Content-Type', 'application/json; charset=utf-8'); self.send_header('Cache-Control', 'no-store'); self.send_header('Content-Length', len(b)); self.end_headers(); self.wfile.write(b)
    def send_login(self, sid):
        secure = '; Secure' if self.headers.get('X-Forwarded-Proto', '') == 'https' else ''
        self.send_response(200); self.send_header('Set-Cookie', f'l4d2panel={sid}; Path=/; HttpOnly{secure}; SameSite=Lax; Max-Age={int(CONF["session_days"]) * 86400}')
        self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', '11'); self.end_headers(); self.wfile.write(b'{"ok":true}')
    def body(self):
        n = int(self.headers.get('Content-Length', 0) or 0)
        try: return json.loads(self.rfile.read(n) or b'{}')
        except Exception: return {}
    def do_GET(self):
        p = urlparse(self.path).path
        if p == '/':
            b = PAGE.encode(); self.send_response(200); self.send_header('Content-Type', 'text/html; charset=utf-8'); self.send_header('Cache-Control', 'no-store'); self.send_header('Content-Length', len(b)); self.end_headers(); self.wfile.write(b); return
        if p == '/api/setup': return self.send_json({'needed': setup_needed(), 'username': CONF.get('bootstrap_user', 'admin')})
        if not check_session(self): return self.send_json({'error': 'auth'}, 401)
        try:
            if p == '/api/status':
                st = a2s(); st['srcds'] = subprocess.run(['pgrep', '-f', 'srcds_linux'], capture_output=True).returncode == 0
                if not st['online'] and st['srcds']:   # (2026-09-19) A2S throttled but process is up: confirm via RCON instead of reporting "not responding"
                    try:
                        pl, raw = players(); humans = [x for x in pl if x['steamid'] != 'BOT']; mm = re.search(r'^map\s*:\s*(\S+)', raw, re.M)
                        st.update(online=True, degraded=True, name=A2S_CACHE.get('name', CONF['panel_title']), map=(A2S_CACHE.get('map') or (mm.group(1) if mm else '?')), players=len(humans), bots=len(pl) - len(humans), max=A2S_CACHE.get('max', len(pl) or 8))
                    except Exception: pass
                st['sys'] = sysinfo(); st['action'] = ACTION
                ac = sess_get(self); st['account'] = ({'user': ac['username'], 'role': ac['role']} if ac else None)
                st['features'] = fe = features(st['online']); st['title'] = CONF['panel_title']; st['display_host'] = CONF['display_host']
                rows = tail(PERF_CSV, 2); c = rows[-1].split(',') if len(rows) > 1 else []
                st['perf'] = {'t': c[0], 'fps': c[5], 'out_kb': round(float(c[4]) / 1024, 1)} if len(c) >= 7 else None
                st.update(game_flags(st['online'], fe))
                return self.send_json(st)
            if p == '/api/players':
                pl, raw = players(); return self.send_json({'players': pl, 'raw': raw})
            if p == '/api/whitelist': return self.send_json({'list': read_whitelist()})
            if p == '/api/addons': return self.send_json({'addons': list_addons(), 'jobs': JOBS, 'zips': ZIPS})
            if p == '/api/workshop_search':
                qs = dict(parse_qsl(urlparse(self.path).query))
                try: return self.send_json(steam_query_files(qs.get('q', '').strip()[:100], max(1, min(1000, int(qs.get('page') or 1)))))
                except ValueError as e: return self.send_json({'error': str(e)}, 400)
            if p == '/api/plugins': return self.send_json(list_plugins())
            if p == '/api/me':
                ac = sess_get(self)
                if not ac: return self.send_json({'error': 'auth'}, 401)
                return self.send_json({k: ac[k] for k in ('username', 'role', 'steamid', 'flags', 'created', 'last_login')})
            if p == '/api/accounts':
                ac = sess_get(self)
                if not ac or ac['role'] != 'owner': return self.send_json({'error': '需要 owner 权限'}, 403)
                with DB_LOCK, closing(db()) as c:
                    rows = c.execute('SELECT id,username,role,steamid,flags,note,created,last_login FROM accounts ORDER BY id').fetchall()
                return self.send_json({'accounts': [dict(r) for r in rows], 'me': ac['username']})
            if p == '/api/download':
                _clean_downloads(); tok = urlparse(self.path).query.replace('token=', '')
                info = DLS.get(tok)
                if not info or not os.path.isfile(info['path']): return self.send_json({'error': '下载链接已过期，请重新打包'}, 404)
                self.send_response(200); self.send_header('Content-Type', 'application/zip')
                self.send_header('Content-Length', str(os.path.getsize(info['path'])))
                self.send_header('Content-Disposition', "attachment; filename*=UTF-8''" + quote(info['name']))
                self.end_headers()
                with open(info['path'], 'rb') as f:
                    while True:
                        chunk = f.read(262144)
                        if not chunk: break
                        try: self.wfile.write(chunk)
                        except Exception: break
                return
            if p == '/api/logs':
                kind = urlparse(self.path).query
                if kind == 'errors':
                    files = sorted(glob.glob(os.path.join(SM_LOGS, 'errors_*.log'))); return self.send_json({'lines': tail(files[-1], 120) if files else []})
                if kind == 'perf': return self.send_json({'lines': tail(PERF_CSV, 60)})
                if kind == 'perfjson':
                    rows = []
                    for l in tail(PERF_CSV, 120):
                        c = l.split(',')
                        if len(c) >= 7 and c[0] != 'time':
                            try: rows.append({'t': c[0], 'humans': int(c[1]), 'cpu': float(c[2]), 'out_kb': round(float(c[4]) / 1024, 1), 'fps': float(c[5])})
                            except ValueError: pass
                    return self.send_json({'rows': rows})
                return self.send_json({'lines': tail(CONSOLE_LOG, 150)})
            return self.send_json({'error': 'not found'}, 404)
        except Exception as e:
            return self.send_json({'error': str(e)}, 500)
    def do_POST(self):
        p = urlparse(self.path).path; d = {} if p in ('/api/upload', '/api/plugin_upload') else self.body(); ip = client_ip(self)
        if p == '/api/setup':   # first run: create the owner account; only possible while there is no account at all
            pw = str(d.get('password', ''))
            if len(pw) < 4: return self.send_json({'error': '密码至少 4 位'}, 400)
            u = CONF.get('bootstrap_user', 'admin'); now = int(time.time())
            with DB_LOCK, closing(db()) as c:
                if c.execute('SELECT COUNT(*) FROM accounts').fetchone()[0]: return self.send_json({'error': '面板已经初始化过了，请直接登录'}, 409)
                aid = c.execute('INSERT INTO accounts(username,pass,role,created,last_login) VALUES(?,?,?,?,?)', (u, hash_pw(pw), 'owner', now, now)).lastrowid
            audit(u, 'setup', ip); print(f'[panel] owner account "{u}" created from {ip}', flush=True)
            return self.send_login(sess_new(aid))
        if p == '/api/login':
            f = FAILS.get(ip, [0, 0])
            if f[0] >= 6 and time.time() - f[1] < 60: return self.send_json({'error': '失败太多，1 分钟后再试'}, 429)
            u = str(d.get('username', '')).strip(); pw = str(d.get('password', ''))
            with DB_LOCK, closing(db()) as c:
                row = c.execute('SELECT * FROM accounts WHERE username=?', (u,)).fetchone()
            if row and verify_pw(pw, row['pass']):
                sid = sess_new(row['id']); FAILS.pop(ip, None)
                with DB_LOCK, closing(db()) as c: c.execute('UPDATE accounts SET last_login=? WHERE id=?', (int(time.time()), row['id']))
                audit(u, 'login', ip)
                return self.send_login(sid)
            FAILS[ip] = [f[0] + 1, time.time()]; time.sleep(1)
            return self.send_json({'error': '面板还没有初始化，请先设置管理员密码' if not row and setup_needed() else '用户名或密码错误'}, 403)
        if not check_session(self): return self.send_json({'error': 'auth'}, 401)
        try:
            if p == '/api/logout':
                sess_del(self); return self.send_json({'ok': True})
            if p == '/api/rcon':
                cmd = str(d.get('cmd', '')).strip()
                if not cmd: return self.send_json({'error': 'empty'}, 400)
                return self.send_json({'out': Rcon.run(cmd)})
            if p == '/api/action':
                if not features(True)['lgsm']: return self.send_json({'error': '未配置 LinuxGSM 脚本'}, 400)
                a = d.get('name')
                if a not in ('start', 'stop', 'restart', 'monitor'): return self.send_json({'error': 'bad action'}, 400)
                return self.send_json({'ok': lgsm(a), 'running': ACTION['running']})
            if p == '/api/preset':
                n = d.get('name'); assert n in ('auto', 'te8', 'te12', 'te16')
                out = Rcon.run('sm_preset ' + n); GS['t'] = 0
                return self.send_json({'out': out})
            if p == '/api/difficulty':
                n = d.get('level'); assert n in ('easy', 'normal', 'hard', 'impossible'); cap = n.capitalize()
                try: Rcon.run('l4d2_force_difficulty ' + cap)   # plugin locks z_difficulty to this; survives map/campaign resets
                except Exception: pass
                out = Rcon.run('z_difficulty ' + cap); GS['t'] = 0
                return self.send_json({'out': out})
            if p == '/api/damage':
                pairs = []
                for key in ('ff', 'burn'):
                    if d.get(key) is None: continue
                    v = max(0.0, min(1.0, float(d[key])))
                    pairs += [(cv, f'{v:g}') for cv in DAMAGE_CVARS[key]]
                if not pairs: return self.send_json({'error': 'nothing to set'}, 400)
                out = '\n'.join(Rcon.run(f'sm_cvar {n} {v}') for n, v in pairs)
                persisted = True
                try: persist_cvars(pairs)
                except Exception as e: persisted = False; out += f'\n(server.cfg not updated: {e})'
                GS['t'] = 0
                return self.send_json({'out': out, 'persisted': persisted})
            if p == '/api/map':
                m = str(d.get('map', '')); assert re.match(r'^[a-z0-9_]+$', m); return self.send_json({'out': Rcon.run('changelevel ' + m)})
            if p == '/api/points':
                amt = int(d.get('amount', 0)); tgt = str(d.get('target', '@all')).strip() or '@all'
                tgt = tgt if tgt.startswith('@') or tgt.startswith('#') else q(tgt)
                return self.send_json({'out': Rcon.run(f'sm_givepoints {tgt} {amt}')})
            if p == '/api/kick':
                uid = int(d.get('userid')); return self.send_json({'out': Rcon.run(f'kickid {uid} {q(str(d.get("reason", "由管理面板踢出")))}')})
            if p == '/api/whitelist':
                op = d.get('op')
                try: sid = parse_steamid(d.get('steamid', ''))
                except ValueError as e: return self.send_json({'error': str(e)}, 400)
                assert sid, '无效 SteamID'
                if op == 'add': out = Rcon.run(f'sm_wl_addid {sid} {q(str(d.get("note", "")))}')
                elif op == 'del': out = Rcon.run(f'sm_wl_del {sid}')
                else: return self.send_json({'error': 'bad op'}, 400)
                return self.send_json({'out': out, 'list': read_whitelist()})
            if p == '/api/upload':
                qs = urlparse(self.path).query; name = safe_vpk_name(unquote(qs.split('name=', 1)[1]), ('.vpk', '.zip')) if 'name=' in qs else None
                if not name: return self.send_json({'error': '只接受 .vpk 或 .zip 文件'}, 400)
                n = int(self.headers.get('Content-Length', 0) or 0)
                if n <= 0 or n > int(CONF['max_upload_mb']) * 1048576: return self.send_json({'error': f'文件为空或超过 {CONF["max_upload_mb"]}MB'}, 400)
                tmp = os.path.join(ADDONS, name + '.uploading'); got = 0
                with open(tmp, 'wb') as f:
                    while got < n:
                        chunk = self.rfile.read(min(1048576, n - got))
                        if not chunk: break
                        f.write(chunk); got += len(chunk)
                if got != n: os.remove(tmp); return self.send_json({'error': f'上传中断 ({got}/{n})'}, 400)
                try: res = install_zip(tmp) if name.lower().endswith('.zip') else {'installed': [install_vpk(tmp, name)], 'skipped': []}
                except ValueError as e: return self.send_json({'error': str(e)}, 400)
                return self.send_json({'ok': True, **res, 'out': refresh_addons()})
            if p == '/api/addons':
                op = d.get('op'); name = safe_vpk_name(str(d.get('name', '')))
                if op == 'delete':
                    if not name or name in PROTECTED or not os.path.exists(os.path.join(ADDONS, name)): return self.send_json({'error': '不能删除该文件'}, 400)
                    os.remove(os.path.join(ADDONS, name)); return self.send_json({'ok': True, 'out': refresh_addons(), 'addons': list_addons()})
                if op == 'workshop':
                    m = re.search(r'(\d{6,12})', str(d.get('id', '')))
                    if not m: return self.send_json({'error': '请输入创意工坊 ID 或链接'}, 400)
                    pubid = m.group(1)
                    if JOBS.get(pubid, {}).get('state') == 'running': return self.send_json({'error': '已经在下载了'}, 400)
                    threading.Thread(target=workshop_job, args=(pubid,), daemon=True).start()
                    return self.send_json({'ok': True, 'id': pubid})
                if op == 'workshop_cancel':
                    j = JOBS.get(str(d.get('id', '')))
                    if not j or j.get('state') != 'running': return self.send_json({'error': '没有进行中的下载'}, 400)
                    j['cancel'] = True; return self.send_json({'ok': True})
                if op == 'zip':
                    names = d.get('names') or ([d.get('name')] if d.get('name') else [])
                    names = [n for n in names if n]
                    if not names: return self.send_json({'error': '请选择要打包的战役'}, 400)
                    token = secrets.token_urlsafe(12)
                    threading.Thread(target=zip_job, args=(token, names), daemon=True).start()
                    return self.send_json({'ok': True, 'token': token})
                return self.send_json({'error': 'bad op'}, 400)
            if p == '/api/whitelist_enable':
                v = 1 if d.get('enable') else 0; out = Rcon.run(f'sm_cvar sm_whitelist_enable {v}'); GS['t'] = 0
                return self.send_json({'out': out})
            if p == '/api/plugins':
                acc = sess_get(self); out = plugin_action(d.get('op'), str(d.get('file', '')))
                audit(acc['username'] if acc else '?', 'plugin.' + str(d.get('op')), str(d.get('file', '')))
                return self.send_json({'out': out, **list_plugins()})
            if p == '/api/plugin_upload':
                qs = urlparse(self.path).query; nm = plugin_name(unquote(qs.split('name=', 1)[1])) if 'name=' in qs else None
                if not nm: return self.send_json({'error': '只接受 .smx 文件'}, 400)
                n = int(self.headers.get('Content-Length', 0) or 0)
                if n <= 0 or n > 20 * 1048576: return self.send_json({'error': '文件为空或过大（>20MB）'}, 400)
                data = b''
                while len(data) < n:
                    chunk = self.rfile.read(min(1048576, n - len(data)))
                    if not chunk: break
                    data += chunk
                if len(data) != n or data[:4] != b'FFPS': return self.send_json({'error': '不是有效的 .smx 插件文件'}, 400)
                dst = os.path.join(SM_PLUGINS, nm + '.smx')
                with open(dst + '.tmp', 'wb') as f: f.write(data)
                os.replace(dst + '.tmp', dst)
                acc = sess_get(self); audit(acc['username'] if acc else '?', 'plugin.upload', nm)
                try: out = Rcon.run('sm plugins load ' + nm)
                except Exception as e: out = f'已上传，加载失败（换图或重启后生效）: {e}'
                return self.send_json({'ok': True, 'out': out, **list_plugins()})
            if p == '/api/me':
                ac = sess_get(self); op = d.get('op')
                if not ac: return self.send_json({'error': 'auth'}, 401)
                if op == 'password':
                    new = str(d.get('password', ''))
                    if not verify_pw(str(d.get('current', '')), ac['pass']): return self.send_json({'error': '当前密码不对'}, 403)
                    if len(new) < 4: return self.send_json({'error': '新密码至少 4 位'}, 400)
                    with DB_LOCK, closing(db()) as c:
                        c.execute('UPDATE accounts SET pass=? WHERE id=?', (hash_pw(new), ac['id']))
                        c.execute('DELETE FROM sessions WHERE account_id=? AND sid<>?', (ac['id'], cookie_sid(self) or ''))   # other devices must log in again
                    audit(ac['username'], 'account.password', 'self'); return self.send_json({'ok': True})
                if op == 'steamid':
                    try: sid_ = parse_steamid(d.get('steamid', ''))
                    except ValueError as e: return self.send_json({'error': str(e)}, 400)
                    with DB_LOCK, closing(db()) as c: c.execute('UPDATE accounts SET steamid=? WHERE id=?', (sid_ or None, ac['id']))
                    audit(ac['username'], 'account.steamid', sid_ or '(unbound)'); return self.send_json({'ok': True, 'steamid': sid_, 'out': sync_sm_admins()})
                return self.send_json({'error': 'bad op'}, 400)
            if p == '/api/accounts':
                ac = sess_get(self)
                if not ac or ac['role'] != 'owner': return self.send_json({'error': '需要 owner 权限'}, 403)
                op = d.get('op'); uname = str(d.get('username', '')).strip()
                if op == 'create':
                    if not re.match(r'^[\w.\-]{2,32}$', uname): return self.send_json({'error': '用户名 2-32 位（字母数字 . _ -）'}, 400)
                    pw = str(d.get('password', ''))
                    if len(pw) < 4: return self.send_json({'error': '密码至少 4 位'}, 400)
                    try: sid_ = parse_steamid(d.get('steamid', ''))
                    except ValueError as e: return self.send_json({'error': str(e)}, 400)
                    try:
                        with DB_LOCK, closing(db()) as c:
                            c.execute('INSERT INTO accounts(username,pass,role,steamid,flags,note,created) VALUES(?,?,?,?,?,?,?)',
                                      (uname, hash_pw(pw), 'owner' if d.get('role') == 'owner' else 'admin', sid_ or None, str(d.get('flags', '99:z')).strip() or '99:z', str(d.get('note', '')).strip(), int(time.time())))
                    except sqlite3.IntegrityError: return self.send_json({'error': '用户名已存在'}, 400)
                    audit(ac['username'], 'account.create', uname); msg = sync_sm_admins() if sid_ else ''
                    return self.send_json({'ok': True, 'out': msg})
                aid = int(d.get('id', 0))
                if op == 'delete':
                    if aid == ac['id']: return self.send_json({'error': '不能删除自己'}, 400)
                    with DB_LOCK, closing(db()) as c:
                        tgt = c.execute('SELECT role FROM accounts WHERE id=?', (aid,)).fetchone()
                        if tgt and tgt['role'] == 'owner' and c.execute("SELECT COUNT(*) FROM accounts WHERE role='owner'").fetchone()[0] <= 1:
                            return self.send_json({'error': '至少保留一个 owner'}, 400)
                        c.execute('DELETE FROM accounts WHERE id=?', (aid,)); c.execute('DELETE FROM sessions WHERE account_id=?', (aid,))
                    audit(ac['username'], 'account.delete', str(aid)); return self.send_json({'ok': True, 'out': sync_sm_admins()})
                if op == 'update':
                    sets, vals = [], []
                    if d.get('password'): sets.append('pass=?'); vals.append(hash_pw(str(d['password'])))
                    if 'role' in d: sets.append('role=?'); vals.append('owner' if d['role'] == 'owner' else 'admin')
                    if 'steamid' in d:
                        try: sid_ = parse_steamid(d.get('steamid', ''))
                        except ValueError as e: return self.send_json({'error': str(e)}, 400)
                        sets.append('steamid=?'); vals.append(sid_ or None)
                    if 'flags' in d: sets.append('flags=?'); vals.append(str(d['flags']).strip() or '99:z')
                    if 'note' in d: sets.append('note=?'); vals.append(str(d['note']).strip())
                    if not sets: return self.send_json({'error': '没有要修改的字段'}, 400)
                    vals.append(aid)
                    with DB_LOCK, closing(db()) as c: c.execute('UPDATE accounts SET ' + ','.join(sets) + ' WHERE id=?', vals)
                    audit(ac['username'], 'account.update', str(aid)); return self.send_json({'ok': True, 'out': sync_sm_admins()})
                return self.send_json({'error': 'bad op'}, 400)
            return self.send_json({'error': 'not found'}, 404)
        except AssertionError as e:
            return self.send_json({'error': str(e) or 'bad request'}, 400)
        except Exception as e:
            return self.send_json({'error': str(e)}, 500)

# ---- web UI: one page. CSS / markup / script are separate strings so the design canvas and the panel share them ----
MARK = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><circle cx="16" cy="16" r="9" fill="none" stroke="#f0a13a" stroke-width="2.6"/><path d="M16 2.5v6M16 23.5v6M2.5 16h6M23.5 16h6" stroke="#f0a13a" stroke-width="2.6" stroke-linecap="round"/><circle cx="16" cy="16" r="2.6" fill="#f0a13a"/></svg>'
CSS = r"""
:root{--bg:#161311;--sur:#1e1a17;--sur2:#292420;--inp:#110e0c;--bd:#372f29;--bd2:#4b4139;--tx:#f2ece3;--mu:#a89e91;--ac:#f0a13a;--ac-ink:#1b1208;--ac2:#ffbe62;--ok:#5ed389;--ok-ink:#08170d;--warn:#f4cf5e;--bad:#bf3a31;--bad2:#ff8078;--r:10px;--r2:6px;
--fd:"Barlow Condensed","Bahnschrift SemiCondensed","Avenir Next Condensed","Roboto Condensed","Arial Narrow",sans-serif;
--fb:-apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB","Microsoft YaHei","Noto Sans CJK SC","Segoe UI",sans-serif;
--fm:"IBM Plex Mono",ui-monospace,"SF Mono",Menlo,Consolas,"Liberation Mono",monospace;
--tape:repeating-linear-gradient(135deg,#f0a13a 0 14px,#2b241e 14px 28px);color-scheme:dark}
*{box-sizing:border-box}html,body{height:100%}
body{margin:0;background:var(--bg);color:var(--tx);font:14px/1.5 var(--fb);-webkit-font-smoothing:antialiased}
a{color:var(--ac2)}a:hover{color:var(--ac)}
.eyebrow{font-family:var(--fd);font-weight:600;font-size:12px;line-height:1;letter-spacing:.16em;text-transform:uppercase;color:var(--ac)}
.k{font-family:var(--fd);font-weight:600;font-size:11px;line-height:1;letter-spacing:.14em;text-transform:uppercase;color:var(--mu)}
.mu{color:var(--mu);font-size:12px}.hint{color:var(--mu);font-size:12px;line-height:1.6;margin-top:8px}.sp{flex:1}
.tape{height:3px;background:var(--tape);flex:none}
code{font-family:var(--fm);font-size:12px;background:var(--sur2);padding:2px 6px;border-radius:4px;color:var(--tx)}code.mu{color:var(--mu)}
/* shell + rail */
#shell{min-height:100%;container:shell/inline-size;display:flex;flex-direction:column;background:radial-gradient(1100px 520px at 12% -8%,#2a2119 0%,rgba(42,33,25,0) 62%),var(--bg)}
#app{display:flex;flex:1}
#side{width:236px;flex:none;background:var(--sur);border-right:1px solid var(--bd);display:flex;flex-direction:column;gap:12px;padding:16px 12px 14px}
.brand{display:flex;align-items:center;gap:10px;padding:0 4px 14px;border-bottom:1px solid var(--bd)}
.brand .mark{width:34px;height:34px;flex:none;color:var(--ac)}.brand .min{min-width:0}
.brand .name{font-size:14px;font-weight:600;line-height:1.25;margin-top:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.srv{background:var(--inp);border:1px solid var(--bd);border-radius:var(--r2);padding:10px 12px;display:flex;flex-direction:column;gap:7px}
.kv{display:flex;justify-content:space-between;align-items:baseline;gap:8px;font-size:12px;min-width:0}
.kv code{background:none;padding:0;font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.kv b{font-family:var(--fd);font-size:17px;font-weight:700;line-height:1;font-variant-numeric:tabular-nums}
.pill{display:inline-flex;align-items:center;gap:8px;font-size:12.5px;font-weight:600;color:var(--mu)}
.pill i{width:9px;height:9px;border-radius:50%;background:var(--mu);flex:none}
.pill.on{color:var(--ok)}.pill.on i{background:var(--ok);animation:pulse 2.2s ease-out infinite}.pill.off{color:var(--bad2)}.pill.off i{background:var(--bad2)}
@keyframes pulse{0%{box-shadow:0 0 0 0 rgba(94,211,137,.45)}100%{box-shadow:0 0 0 8px rgba(94,211,137,0)}}
#side nav{display:flex;flex-direction:column;gap:2px}
#side nav button{display:flex;justify-content:flex-start;align-items:center;gap:10px;width:100%;background:transparent;color:var(--mu);text-align:left;padding:0 10px;height:38px;border:0;border-radius:var(--r2);font-size:13.5px;font-weight:500}
#side nav button svg{width:18px;height:18px;flex:none;opacity:.75}
#side nav button:hover{background:var(--sur2);color:var(--tx)}
#side nav button.on{background:#2e2620;color:var(--ac2);box-shadow:inset 3px 0 0 var(--ac)}#side nav button.on svg{opacity:1;color:var(--ac)}
/* main + header */
#main{flex:1;min-width:0;display:flex;flex-direction:column;padding:22px 28px 0;max-width:1240px}
header{display:flex;align-items:flex-end;gap:14px;padding:0 0 16px;border-bottom:1px solid var(--bd);margin-bottom:18px;flex-wrap:wrap}
header .ttl{display:flex;flex-direction:column;gap:5px}
header h1{font-size:24px;margin:0;font-weight:700;line-height:1.15}
header .meta{display:flex;align-items:center;gap:10px;color:var(--mu);font-size:12px;flex-wrap:wrap}
header .meta svg{width:14px;height:14px}
.view{display:none}.view.on{display:block;padding-bottom:14px}
@keyframes rise{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
.view.on>*{animation:rise .32s ease both}.view.on>*:nth-child(2){animation-delay:.05s}.view.on>*:nth-child(3){animation-delay:.1s}.view.on>*:nth-child(4){animation-delay:.15s}
/* status band + cards */
.band{display:grid;grid-template-columns:1fr 1.55fr 1fr 1fr 1.05fr 1.1fr;gap:1px;background:var(--bd);border:1px solid var(--bd);border-radius:var(--r);overflow:hidden;margin-bottom:16px}.band.sys{grid-template-columns:repeat(4,minmax(0,1fr))}
.tile{background:var(--sur);padding:14px 16px 13px;min-width:0}
.tile .v{font-family:var(--fd);font-weight:700;font-size:30px;line-height:1.1;margin-top:9px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-variant-numeric:tabular-nums}
.tile .v.mono{font-family:var(--fm);font-weight:500;font-size:15px;line-height:1.35;margin-top:11px}.tile .v.cn{font-family:var(--fb);font-size:22px;margin-top:11px}
.tile .s{font-size:11.5px;color:var(--mu);margin-top:5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;margin-bottom:16px}.grid>.card{margin-bottom:0}.grid>div>.card{margin-bottom:16px}.grid>div>.card:last-child{margin-bottom:0}
.grid.pl{grid-template-columns:minmax(0,1.55fr) minmax(0,1fr);align-items:start}.grid.pl.nowl{grid-template-columns:minmax(0,1fr)}
.grid.pg{grid-template-columns:minmax(0,1.5fr) minmax(0,1fr);align-items:start}.grid.acct{grid-template-columns:repeat(auto-fit,minmax(min(100%,420px),1fr))}
.card{background:var(--sur);border:1px solid var(--bd);border-radius:var(--r);padding:16px 18px;margin-bottom:16px}div.card{display:flex;flex-direction:column}
.card.tool{flex-direction:row;flex-wrap:wrap;align-items:center;gap:10px 14px}.card.tool h2{margin:0}.card.tool select{flex:1;min-width:220px}.card.tool .mu{flex:1 0 auto}
.mt{display:none}.mt.on{display:block}
.card h2{font-size:15px;margin:0 0 12px;display:flex;align-items:center;gap:10px;font-weight:600;flex-wrap:wrap}
.card h2::before{content:"";width:4px;height:15px;background:var(--ac);border-radius:1px;flex:none}
.row{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:6px 0}.lbl{color:var(--mu);font-size:12px;min-width:44px}
/* note tray: a card's closing remarks, one band across the bottom of the card */
.note{--ng:14px;position:relative;margin:auto -18px -16px;padding:calc(var(--ng) + 11px) 18px 11px 40px;border-radius:0 0 var(--r) var(--r);background:linear-gradient(to bottom,transparent var(--ng),var(--bd) var(--ng),var(--bd) calc(var(--ng) + 1px),rgba(0,0,0,.14) calc(var(--ng) + 1px));color:var(--mu);font-size:12px;line-height:1.6}
.note::before{content:"";position:absolute;left:18px;top:calc(var(--ng) + 13px);width:14px;height:14px;background:var(--ac);opacity:.85;-webkit-mask:url('data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 24 24%22 fill=%22none%22 stroke=%22%23000%22 stroke-width=%222.2%22 stroke-linecap=%22round%22%3E%3Ccircle cx=%2212%22 cy=%2212%22 r=%229%22/%3E%3Cpath d=%22M12 11v5M12 7.6h.01%22/%3E%3C/svg%3E') center/contain no-repeat;mask:url('data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 24 24%22 fill=%22none%22 stroke=%22%23000%22 stroke-width=%222.2%22 stroke-linecap=%22round%22%3E%3Ccircle cx=%2212%22 cy=%2212%22 r=%229%22/%3E%3Cpath d=%22M12 11v5M12 7.6h.01%22/%3E%3C/svg%3E') center/contain no-repeat}
.note p{margin:0}.note p+p{margin-top:3px}.note b{color:var(--tx);font-weight:600}.note code{font-size:11.5px;padding:1px 5px}
/* collapsible card (raw plugin list) */
details.card summary{list-style:none;cursor:pointer;display:flex;align-items:center;gap:10px}details.card summary::-webkit-details-marker{display:none}
details.card summary h2{margin:0;flex:1}details.card summary::after{content:"";width:8px;height:8px;margin:0 6px 4px 0;border-right:1.5px solid var(--mu);border-bottom:1.5px solid var(--mu);transform:rotate(45deg);transition:transform .15s}
details.card[open] summary::after{transform:rotate(-135deg);margin:4px 6px 0 0}details.card[open] summary{margin-bottom:12px}
/* page footer: connect address + vitals, pinned to the bottom when a page is short */
#pfoot{margin-top:auto;display:flex;align-items:center;flex-wrap:wrap;gap:10px 28px;padding:16px 0 20px;border-top:1px solid var(--bd)}
.fs{display:flex;align-items:center;gap:9px;min-width:0}.fs b{font-family:var(--fd);font-size:17px;font-weight:700;line-height:1;font-variant-numeric:tabular-nums;white-space:nowrap}
.fs code{background:none;padding:0;font-size:12.5px;color:var(--tx);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}#f-conn{gap:10px}
label{display:inline-flex;align-items:center;gap:6px;font-size:13px;color:var(--mu)}
.sl{display:flex;flex-direction:column;gap:4px;margin-top:8px}.spark{width:100%;height:64px;display:block}
.spark .ln{fill:none;stroke-width:2;stroke-linejoin:round;stroke-linecap:round}.spark .ar{opacity:.14}.spark text{font-family:var(--fm);font-size:10px;fill:var(--mu)}.spark .last{font-weight:700;font-size:11px}
/* controls */
button{background:var(--ac);color:var(--ac-ink);border:1px solid transparent;border-radius:var(--r2);padding:0 14px;height:36px;font-family:inherit;font-size:13px;font-weight:600;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;gap:6px;white-space:nowrap;transition:background .15s,border-color .15s,transform .05s}
button:hover{background:var(--ac2)}button:active{transform:translateY(1px)}button:disabled{opacity:.45;cursor:default}button:focus-visible{outline:2px solid var(--ac2);outline-offset:2px}
button.g{background:transparent;border-color:var(--bd2);color:var(--tx)}button.g:hover{background:var(--sur2);border-color:var(--mu)}
button.d{background:var(--bad);color:#fff}button.d:hover{background:#ad332b}
button.sm{height:30px;padding:0 10px;font-size:12px;font-weight:500}
.seg{display:inline-flex;background:var(--inp);border:1px solid var(--bd);border-radius:var(--r2);padding:3px;gap:2px}
.seg button{background:transparent;color:var(--mu);height:30px;padding:0 14px;font-weight:500;border-radius:4px}.seg button:hover{color:var(--tx);background:var(--sur2)}.seg button.on{background:var(--ac);color:var(--ac-ink);font-weight:600}
.tabs{display:flex;gap:2px;background:var(--inp);border:1px solid var(--bd);border-radius:var(--r2);padding:3px}
.tabs button{background:transparent;color:var(--mu);height:28px;padding:0 12px;font-size:12px;font-weight:500;border-radius:4px}.tabs button:hover{color:var(--tx)}.tabs button.on{background:var(--sur2);color:var(--tx)}
input,select{background:var(--inp);color:var(--tx);border:1px solid var(--bd);border-radius:var(--r2);padding:0 11px;height:36px;font-size:13px;font-family:inherit;min-width:0}
input:focus,select:focus{outline:2px solid var(--ac);outline-offset:-1px;border-color:var(--ac)}input::placeholder{color:#75695d}input[type=number]{font-family:var(--fm)}
input[type=file]{padding:0;height:auto;border:1px dashed var(--bd2);background:transparent;color:var(--mu);font-size:12px;line-height:34px}
input[type=file]::file-selector-button{background:var(--sur2);color:var(--tx);border:0;border-right:1px solid var(--bd);padding:0 12px;height:34px;margin-right:10px;font-family:inherit;font-size:12px;cursor:pointer}
button.sw{position:relative;width:44px;height:24px;padding:0;background:var(--bd2);border:0;border-radius:999px;flex:none;transition:background .2s}
button.sw::after{content:'';position:absolute;top:3px;left:3px;width:18px;height:18px;border-radius:50%;background:#fff;transition:left .2s}
button.sw.on{background:var(--ok)}button.sw.on::after{left:23px;background:var(--ok-ink)}button.sw.dis{opacity:.4;cursor:default}
/* tables, lists, output */
.tw{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:13px}.thumb{display:block;width:72px;height:40px;object-fit:cover;border-radius:3px;background:var(--inp)}
th{font-family:var(--fd);font-weight:600;font-size:12px;letter-spacing:.1em;text-transform:uppercase;color:var(--mu);text-align:left;padding:6px 8px;border-bottom:1px solid var(--bd2);white-space:nowrap}
td{padding:9px 8px;border-bottom:1px solid var(--bd);vertical-align:middle}tr:last-child td{border-bottom:0}tr:hover td{background:#221e1a}td.act{white-space:nowrap;text-align:right}
.wl{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:8px 6px;border-bottom:1px solid var(--bd);font-size:13px}.wl:last-child{border:0}.wl>span{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.job{display:flex;flex-direction:column;gap:5px;font-size:12.5px;color:var(--mu);padding:5px 0}.jr{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.jr i{width:8px;height:8px;border-radius:50%;background:var(--bad2);flex:none}.job.running .jr i{background:var(--warn);animation:blink 1.2s ease-in-out infinite}.job.done .jr i{background:var(--ok)}.bar{height:6px;max-width:460px;background:var(--inp);border:1px solid var(--bd);border-radius:3px;overflow:hidden}.bar span{display:block;height:100%;background:var(--ac);transition:width .5s}
@keyframes blink{50%{opacity:.35}}
pre{background:var(--inp);border:1px solid var(--bd);padding:12px 14px;border-radius:var(--r2);max-height:340px;overflow:auto;font-family:var(--fm);font-size:12px;line-height:1.55;white-space:pre-wrap;margin:0;color:#d9d1c5}
#toast{position:fixed;left:50%;bottom:28px;transform:translateX(-50%) translateY(8px);background:#241f1b;border:1px solid var(--bd2);border-left:3px solid var(--ok);color:var(--tx);padding:11px 16px;border-radius:var(--r2);font-size:13px;box-shadow:0 12px 40px rgba(0,0,0,.5);opacity:0;pointer-events:none;transition:.2s;max-width:90vw;z-index:20}
#toast.show{opacity:1;transform:translateX(-50%)}#toast.bad{border-left-color:var(--bad2)}
/* login */
#login,#setup{min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px;background:radial-gradient(800px 480px at 50% 0%,#2a2119 0%,rgba(42,33,25,0) 70%),var(--bg)}
#login .box,#setup .box{width:100%;max-width:380px;background:var(--sur);border:1px solid var(--bd);border-radius:var(--r);overflow:hidden;box-shadow:0 30px 80px rgba(0,0,0,.45)}
#login .in,#setup .in{padding:26px 28px 24px;display:flex;flex-direction:column;gap:10px}#login .mark,#setup .mark{width:44px;height:44px;color:var(--ac);margin-bottom:6px}
#login h2,#setup h2{margin:4px 0 2px;font-size:22px;font-weight:700}#login label,#setup label{margin-top:8px;font-size:12px}
#login input,#setup input{height:42px;font-size:15px}#login button,#setup button{height:42px;font-size:15px;margin-top:10px}#lmsg,#sumsg{color:var(--bad2);font-size:12.5px;min-height:18px}
/* phone / narrow */
@container shell (max-width:860px){
#app{flex-direction:column}
#side{width:auto;border-right:0;border-bottom:1px solid var(--bd);flex-direction:row;flex-wrap:wrap;align-items:center;gap:8px 12px;padding:10px 12px 0;position:sticky;top:0;z-index:5}
.brand{padding:0;border:0;flex:1;min-width:0}.brand .mark{width:28px;height:28px}.brand .name{margin-top:2px}
.srv{flex-direction:row;align-items:center;gap:12px;padding:6px 10px}.srv .kv .k,.srv .kv code{display:none}.kv b{font-size:15px}
#side nav{flex-direction:row;overflow-x:auto;flex-basis:100%;gap:2px;scrollbar-width:none;padding-bottom:8px}#side nav::-webkit-scrollbar{display:none}
#side nav button{width:auto;height:34px;padding:0 10px;font-size:13px;gap:7px}#side nav button svg{width:16px;height:16px}#side nav button.on{box-shadow:inset 0 -2px 0 var(--ac)}
#main{padding:14px 14px 0}header{margin-bottom:14px;padding-bottom:12px}header h1{font-size:21px}
.band{grid-template-columns:repeat(3,minmax(0,1fr))}.band.sys{grid-template-columns:repeat(2,minmax(0,1fr))}.tile{padding:12px 12px 11px}.tile .v{font-size:24px}.tile .v.cn{font-size:19px}.grid,.grid.pl,.grid.pg,.grid.acct{grid-template-columns:minmax(0,1fr)}.card{padding:14px}
.note{--ng:12px;margin:auto -14px -14px;padding:calc(var(--ng) + 10px) 14px 10px 34px}.note::before{left:14px;top:calc(var(--ng) + 12px)}
#pfoot{gap:8px 18px;padding:14px 0 18px}#f-conn{flex-basis:100%}#f-conn code{flex:1}
button.sm{height:34px}
}
@container shell (max-width:480px){.band{grid-template-columns:repeat(2,minmax(0,1fr))}header .meta{width:100%}}
@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
"""
BODY = r"""
<div id="login"><div class="box"><div class="tape"></div><div class="in">
<svg class="mark" viewBox="0 0 32 32" aria-hidden="true"><circle cx="16" cy="16" r="9" fill="none" stroke="currentColor" stroke-width="2.6"/><path d="M16 2.5v6M16 23.5v6M2.5 16h6M23.5 16h6" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"/><circle cx="16" cy="16" r="2.6" fill="currentColor"/></svg>
<div class="eyebrow">L4D2 Ops Panel</div><h2>登录面板</h2><div class="mu">Left 4 Dead 2 服务器运维面板</div>
<label for="user">用户名</label><input id="user" placeholder="用户名" autocomplete="username" onkeydown="if(event.key==='Enter')login()">
<label for="pw">密码</label><input id="pw" type="password" placeholder="密码" autocomplete="current-password" onkeydown="if(event.key==='Enter')login()">
<button onclick="login()">登录</button><div id="lmsg"></div>
</div></div></div>
<div id="setup" style="display:none"><div class="box"><div class="tape"></div><div class="in">
<svg class="mark" viewBox="0 0 32 32" aria-hidden="true"><circle cx="16" cy="16" r="9" fill="none" stroke="currentColor" stroke-width="2.6"/><path d="M16 2.5v6M16 23.5v6M2.5 16h6M23.5 16h6" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"/><circle cx="16" cy="16" r="2.6" fill="currentColor"/></svg>
<div class="eyebrow">L4D2 Ops Panel</div><h2>首次使用：设置管理员密码</h2><div class="mu">账号 <code id="su-user">admin</code> 是 owner，之后可以在“账号”页改密码、加其他账号。</div>
<label for="su-pw">密码（至少 4 位）</label><input id="su-pw" type="password" placeholder="设置密码" autocomplete="new-password" onkeydown="if(event.key==='Enter')setup()">
<label for="su-pw2">再输一次</label><input id="su-pw2" type="password" placeholder="再输一次" autocomplete="new-password" onkeydown="if(event.key==='Enter')setup()">
<button onclick="setup()">设置并进入面板</button><div id="sumsg"></div>
</div></div></div>
<div id="shell" style="display:none"><div class="tape"></div><div id="app">
<aside id="side">
<div class="brand"><svg class="mark" viewBox="0 0 32 32" aria-hidden="true"><circle cx="16" cy="16" r="9" fill="none" stroke="currentColor" stroke-width="2.6"/><path d="M16 2.5v6M16 23.5v6M2.5 16h6M23.5 16h6" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"/><circle cx="16" cy="16" r="2.6" fill="currentColor"/></svg><div class="min"><div class="eyebrow">L4D2 Ops</div><div class="name" id="brand">L4D2 面板</div></div></div>
<div class="srv"><span id="pill" class="pill"><i></i><span>连接中</span></span><div class="kv"><span class="k">地图</span><code id="side-map">—</code></div><div class="kv"><span class="k">玩家</span><b id="side-players">—</b></div></div>
<nav>
<button data-v="overview" onclick="nav('overview')"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/></svg>概览</button>
<button data-v="players" onclick="nav('players')"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="8" r="3.5"/><path d="M3 20c0-3.3 2.7-6 6-6s6 2.7 6 6"/><circle cx="17" cy="9" r="2.5"/><path d="M21 19c0-2.5-1.8-4.5-4-4.5"/></svg>玩家 / 白名单</button>
<button data-v="game" onclick="nav('game')"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7h9M19 7h1M4 17h3M13 17h7"/><circle cx="16" cy="7" r="2.5"/><circle cx="10" cy="17" r="2.5"/></svg>游戏设置</button>
<button data-v="maps" onclick="nav('maps')"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6l6-2 6 2 6-2v14l-6 2-6-2-6 2z"/><path d="M9 4v14M15 6v14"/></svg>地图 / 战役</button>
<button data-v="plugins" onclick="nav('plugins')"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M10 4a2 2 0 1 1 4 0v1h4a1 1 0 0 1 1 1v4h-1a2 2 0 1 0 0 4h1v4a1 1 0 0 1-1 1h-4v-1a2 2 0 1 0-4 0v1H6a1 1 0 0 1-1-1v-4h1a2 2 0 1 0 0-4H5V6a1 1 0 0 1 1-1h4z"/></svg>插件</button>
<button data-v="console" onclick="nav('console')"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 9l3 3-3 3M13 15h4"/></svg>控制台</button>
<button data-v="logs" onclick="nav('logs')"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M5 4h10l4 4v12H5z"/><path d="M15 4v4h4M8 12h8M8 16h8"/></svg>日志 / 性能</button>
<button data-v="server" onclick="nav('server')"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="6" rx="1.5"/><rect x="3" y="14" width="18" height="6" rx="1.5"/><path d="M7 7h.01M7 17h.01"/></svg>服务器</button>
<button data-v="accounts" onclick="nav('accounts')"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="8" cy="12" r="4"/><path d="M12 12h9M18 12v3M15 12v2"/></svg>账号</button>
</nav>
</aside>
<div id="main">
<header><div class="ttl"><div class="eyebrow" id="veyebrow">Overview</div><h1 id="vtitle">概览</h1></div><span class="sp"></span><div class="meta"><span>刷新于 <span id="ts">—</span></span><button id="who" class="g sm" title="我的账号" onclick="nav('accounts')"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 3.6-7 8-7s8 3 8 7"/></svg><span id="who-name"></span></button><button class="g sm" onclick="logout()">退出</button></div></header>

<section class="view" id="v-overview">
<div class="band">
<div class="tile"><div class="k">玩家</div><div class="v" id="t-players">-</div><div class="s" id="t-bots"></div></div>
<div class="tile"><div class="k">地图</div><div class="v mono" id="t-map">-</div><div class="s" id="t-name"></div></div>
<div class="tile"><div class="k">特感预设</div><div class="v" id="t-preset">-</div><div class="s" id="t-diff"></div></div>
<div class="tile"><div class="k">Server FPS</div><div class="v" id="t-fps">-</div><div class="s">≥ 29 正常（有人时采样）</div></div>
<div class="tile"><div class="k">出流量</div><div class="v" id="t-out">-</div><div class="s">5M 带宽上限 ≈ 625 KB/s</div></div>
<div class="tile"><div class="k">系统负载</div><div class="v" id="t-load">-</div><div class="s" id="t-mem"></div></div>
</div>
<div class="grid"><div class="card"><h2>性能<span class="sp"></span><span class="mu">最近 120 次采样</span></h2><div class="sl"><span class="k">Server FPS</span><svg class="spark" id="c-fps"></svg></div><div class="sl"><span class="k">出流量 KB/s</span><svg class="spark" id="c-out"></svg></div></div>
<div class="card"><h2>在线玩家<span class="sp"></span><button class="g sm" onclick="nav('players')">管理</button></h2><div class="tw"><table id="players-mini"></table></div></div></div>
</section>

<section class="view" id="v-players"><div class="grid pl" id="pl-grid">
<div class="card"><h2>在线玩家<span class="sp"></span><button class="g sm" onclick="loadPlayers()">刷新</button></h2><div class="tw"><table id="players"></table></div></div>
<div class="card" data-f="whitelist"><h2>白名单<span class="sp"></span><span id="wlcount" class="mu"></span></h2>
<div class="row" style="margin-bottom:6px"><button type="button" id="sw-wl" class="sw dis" aria-label="白名单开关" onclick="wlToggle()"></button><span id="wl-state" class="mu">读取中…</span></div>
<div class="hint" style="margin:0 0 12px">开启 = 只有名单里的人和管理员能进；关闭 = 任何人都能进（临时给朋友开门时用，加完人记得开回来）。</div>
<div class="row"><input id="wlid" placeholder="SteamID / 主页链接 / 17位好友码" style="flex:1;min-width:150px"><input id="wlnote" placeholder="备注" style="width:90px"><button onclick="wl('add')">添加</button></div><div id="wllist"></div></div>
</div></section>

<section class="view" id="v-game"><div class="grid">
<div class="card" data-f="preset"><h2>特感强度</h2><div class="row"><span class="seg" id="seg-preset"><button onclick="preset('auto')">auto</button><button onclick="preset('te8')">te8</button><button onclick="preset('te12')">te12</button><button onclick="preset('te16')">te16</button></span></div><div class="note">auto = 按存活人数 4→16 只自动缩放；te8 / te12 / te16 = 固定数量。切换立即生效并保存，换图、重启都保持。</div></div>
<div class="card"><h2>难度</h2><div class="row"><span class="seg" id="seg-diff"><button data-v="easy" onclick="diff('easy')">简单</button><button data-v="normal" onclick="diff('normal')">普通</button><button data-v="hard" onclick="diff('hard')">高级</button><button data-v="impossible" onclick="diff('impossible')">专家</button></span></div><div class="note">即时生效，并跨换图保持（默认专家，由 Force Difficulty 插件维持）；已刷出的 Tank 血量不变。</div></div>
<div class="card"><h2>伤害</h2><div class="row"><label>友伤 <input id="dmg-ff" type="number" min="0" max="1" step="0.05" style="width:86px"></label><label>火焰伤害 <input id="dmg-burn" type="number" min="0" max="1" step="0.05" style="width:86px"></label><button onclick="damage()">应用</button></div><div class="note"><p>0 = 无伤害，1 = 全额；即时生效并写入 server.cfg，重启保持。</p><p>四个难度档位统一设为同一值，投票换难度后也不变；游戏默认友伤 0.1 / 0.3 / 0.5，火焰 0.2 / 0.2 / 0.4 / 1。</p></div></div>
<div class="card" data-f="points"><h2>发放积分</h2><div class="row"><select id="ptarget" style="flex:1;min-width:0" onchange="document.getElementById('pcustom').style.display=this.value==='__custom'?'':'none'"><option value="@all">全体在线玩家</option></select><input id="pcustom" placeholder="玩家名 / #userid" style="width:140px;display:none"><input id="pamount" type="number" value="300" style="width:96px"><button onclick="points()">发放</button></div><div class="note">通过 Points System 的 <code>sm_givepoints</code> 发放。</div></div>
</div></section>

<section class="view" id="v-maps">
<div class="card tool"><h2>切换地图</h2><select id="map"></select><button onclick="changemap()">切换</button><span class="mu">官方 14 个战役 + 已安装的自定义战役；切换会丢失当前进度</span></div>
<div class="card"><h2>安装新战役<span class="sp"></span><span class="tabs" id="mtabs"><button class="on" onclick="mtab('ws',this)" data-f="workshop">工坊 ID / 链接</button><button onclick="mtab('up',this)">上传 vpk / zip</button><button onclick="mtab('search',this)" data-f="workshop_search">搜索创意工坊</button></span></h2>
<div class="mt on" id="mt-ws"><div class="row"><input id="wsid" placeholder="创意工坊 ID 或链接" style="flex:1;min-width:0" onkeydown="if(event.key==='Enter')workshop()"><button onclick="workshop()">下载安装</button></div><div class="note">直连 Steam CDN 分块下载，完成后自动安装、热加载，不用重启；玩家客户端也要订阅同一个创意工坊物品，否则进不了自定义战役。</div></div>
<div class="mt" id="mt-up"><div class="row"><input type="file" id="vpkfile" accept=".vpk,.zip" style="flex:1;min-width:0"><button onclick="upload()">上传</button></div><div id="upmsg" class="mu"></div><div class="note">zip（例如 gamemaps.com 下载的压缩包）会自动解压出里面的 vpk；不含地图（maps/*.bsp）的 vpk 一律拒收。</div></div>
<div class="mt" id="mt-search"><div class="row"><input id="wsq" placeholder="战役名或关键字，留空 = 订阅最多的战役" style="flex:1;min-width:0" onkeydown="if(event.key==='Enter')wsSearch()"><button onclick="wsSearch()">搜索</button></div><div id="wsres" style="margin-top:8px"></div><div class="note">只列出带 Campaigns 标签的物品；点“安装”走工坊下载通道，装前同样检查 vpk 里有没有地图。</div></div></div>
<div class="card"><h2>已安装的自定义战役<span class="sp"></span><button class="g sm" onclick="loadAddons()">刷新</button></h2><div id="addons"></div>
<div class="note">切到第一章会丢失当前进度；打包下载 = 把 vpk 压成 zip 给玩家手动安装；受保护的 vpk 不提供删除。</div></div>
</section>

<section class="view" id="v-console">
<div class="card"><h2>RCON 控制台</h2><div class="row"><input id="cmd" placeholder="status · sm plugins list · sm_cvar z_difficulty · sm_wl_list …" style="flex:1;font-family:var(--fm)" onkeydown="if(event.key==='Enter')rcon();if(event.key==='ArrowUp'&&hist.length){this.value=hist[hist.length-1]}"><button onclick="rcon()">发送</button></div><pre id="rout" style="max-height:60vh">(输出显示在这里)</pre>
<div class="note">隐藏 cvar（z_common_limit、nb_update_frequency、sv_airaccelerate 等）要写 <code>sm_cvar 名字 [值]</code>。↑ 取回上一条命令。</div></div>
</section>

<section class="view" id="v-logs">
<div class="card"><h2>日志<span class="sp"></span><span class="tabs"><button class="on" onclick="logs('console',this)">控制台</button><button onclick="logs('errors',this)">插件报错</button><button onclick="logs('perf',this)">采样</button></span><button class="g sm" onclick="logs(curlog)">刷新</button></h2><pre id="logs" style="max-height:70vh"></pre></div>
</section>

<section class="view" id="v-server">
<div class="card" data-f="lgsm"><h2>服务器控制<span class="sp"></span><span id="actmsg" class="mu"></span></h2><div class="row"><button onclick="act('restart')">重启</button><button class="g" onclick="act('start')">启动</button><button class="d" onclick="act('stop')">停止</button><button class="g" onclick="act('monitor')">巡检</button></div><div class="note">重启约 1 分钟；有玩家在线时会断开所有人。</div></div>
<div class="band sys">
<div class="tile"><div class="k">系统负载</div><div class="v" id="sy-load">-</div><div class="s" id="sy-load-s"></div></div>
<div class="tile"><div class="k">内存</div><div class="v" id="sy-mem">-</div><div class="s" id="sy-mem-s"></div></div>
<div class="tile"><div class="k">系统已运行</div><div class="v" id="sy-up">-</div><div class="s">自上次开机</div></div>
<div class="tile"><div class="k">游戏进程</div><div class="v cn" id="sy-proc">-</div><div class="s">srcds_linux</div></div>
</div>
</section>

<section class="view" id="v-plugins"><div class="grid pg">
<div class="card"><h2>插件列表<span class="sp"></span><button class="g sm" onclick="loadPlugins()">刷新</button></h2><div id="plugins"></div>
<div class="note">启用 / 禁用 = 移动 disabled/ 目录 + 热加载，立即生效；受保护的核心插件不可禁用、删除。删除只能删已禁用的。</div></div>
<div>
<div class="card"><h2>上传插件</h2><div class="row"><input type="file" id="smxfile" accept=".smx" style="flex:1;min-width:0"><button onclick="uploadSmx()">上传并加载</button></div><div id="smxmsg" class="mu"></div>
<div class="note">只收 .smx（20 MB 以内），写入 plugins/ 后立即 sm plugins load；同名插件会被覆盖。</div></div>
<details class="card"><summary><h2>SourceMod 运行中的插件<span class="sp"></span><span class="mu">sm plugins list 原始输出</span></h2></summary><pre id="plugins-raw" style="max-height:44vh">-</pre></details>
</div></div></section>

<section class="view" id="v-accounts"><div class="grid acct">
<div class="card"><h2>我的账号<span class="sp"></span><span id="me-info" class="mu"></span></h2>
<div class="row"><input id="me-cur" type="password" placeholder="当前密码" autocomplete="current-password" style="width:140px"><input id="me-new" type="password" placeholder="新密码" autocomplete="new-password" style="width:140px"><input id="me-new2" type="password" placeholder="再输一次新密码" autocomplete="new-password" style="width:150px"><button onclick="changePw()">修改密码</button></div>
<div class="row"><input id="me-steam" placeholder="绑定 Steam（留空 = 解绑）：SteamID / 主页链接 / 17位好友码" style="flex:1;min-width:200px"><button onclick="bindSteam()">保存绑定</button></div>
<div class="note">改密码后其他设备上的登录会失效；绑定 Steam 后会写入游戏管理员（admins_simple.ini 的面板托管块）并热重载。</div></div>
<div class="card" data-owner style="display:none"><h2>新建账号</h2>
<div class="row"><input id="na-user" placeholder="用户名" style="width:140px"><input id="na-pw" type="password" placeholder="密码" style="width:140px"><select id="na-role" style="width:96px"><option value="admin">admin</option><option value="owner">owner</option></select></div>
<div class="row"><input id="na-steam" placeholder="绑定 Steam（可空）：SteamID / 主页链接 / 17位好友码" style="flex:1;min-width:200px"><input id="na-flags" value="99:z" style="width:86px"><button onclick="createAccount()">创建</button></div>
<div class="note"><p><b>绑定 Steam</b> 支持 <code>STEAM_1:1:xxx</code>、<code>[U:1:xxx]</code>、17 位好友码、<code>steamcommunity.com/profiles/…</code> 或 <code>/id/自定义名</code>（自定义名需服务器能连 steamcommunity）。</p><p><b>权限位</b> <code>z</code> = 全部管理员权限，前面的数字是免疫等级；留空默认 <code>99:z</code>。</p></div></div>
</div>
<div class="card" data-owner style="display:none"><h2>面板账号<span class="sp"></span><button class="g sm" onclick="loadAccounts()">刷新</button></h2>
<div class="hint" style="margin:0 0 10px">owner 可管理账号。绑定 SteamID 后，该账号会自动写入游戏管理员（admins_simple.ini 的面板托管块）并热重载，一处管两边。</div>
<div class="tw"><table id="accounts"></table></div></div>
</section>
<footer id="pfoot">
<div class="fs" id="f-conn" style="display:none"><span class="k">连接地址</span><code id="f-host"></code><button class="g sm" onclick="copyConn()">复制</button></div>
<span class="sp"></span>
<div class="fs"><span class="k">负载</span><b id="f-load">-</b></div>
<div class="fs"><span class="k">内存</span><b id="f-mem">-</b></div>
<div class="fs"><span class="k">游戏进程</span><b id="f-proc">-</b></div>
</footer>
</div></div></div>
<div id="toast"></div>
"""
JS = r"""
const MAPS=%MAPS%;let curlog='console',hist=[];
const TITLES={overview:'概览',players:'玩家 / 白名单',game:'游戏设置',maps:'地图 / 战役',plugins:'插件',console:'控制台',logs:'日志 / 性能',server:'服务器',accounts:'账号'};
const EYEBROW={overview:'Overview',players:'Players · Whitelist',game:'Game settings',maps:'Maps · Campaigns',plugins:'SourceMod plugins',console:'RCON console',logs:'Logs · Perf',server:'Server',accounts:'Accounts'};
const DIFF={easy:'简单',normal:'普通',hard:'高级',impossible:'专家'};
let myRole='admin';
function nav(v){if(!TITLES[v])v='overview';document.querySelectorAll('.view').forEach(e=>e.classList.toggle('on',e.id==='v-'+v));document.querySelectorAll('#side nav button').forEach(b=>{const on=b.dataset.v===v;b.classList.toggle('on',on);if(on)b.scrollIntoView({block:'nearest',inline:'nearest'})});set('vtitle',TITLES[v]);set('veyebrow',EYEBROW[v]);try{localStorage.setItem('l4d2view',v)}catch(e){}try{history.replaceState(null,'','#'+v)}catch(e){}if(v==='logs')logs(curlog);if(v==='overview')perf();if(v==='maps')loadAddons();if(v==='plugins')loadPlugins();if(v==='accounts'){loadMe();if(myRole==='owner')loadAccounts()}}
addEventListener('hashchange',()=>{const v=location.hash.slice(1);if(TITLES[v]&&!document.getElementById('v-'+v).classList.contains('on'))nav(v)});

function toast(t,bad){const e=document.getElementById('toast');e.textContent=t;e.classList.toggle('bad',!!bad);e.classList.add('show');clearTimeout(e._t);e._t=setTimeout(()=>e.classList.remove('show'),2800)}
async function api(p,o){const r=await fetch(p,o?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(o)}:{});if(r.status===401){show(false);throw new Error('未登录')}const j=await r.json();if(j.error)throw new Error(j.error);return j}
function short(t){t=String(t||'').replace(/\s+/g,' ').trim();return t.length>140?t.slice(0,140)+'…':t}
async function run(p,o,okmsg){try{const j=await api(p,o);toast(okmsg||short(j.out)||'完成');return j}catch(e){toast(e.message,true);throw e}}
function show(on){document.getElementById('login').style.display=on?'none':'';document.getElementById('shell').style.display=on?'':'none';document.getElementById('setup').style.display='none'}
function showSetup(u){document.getElementById('login').style.display='none';document.getElementById('shell').style.display='none';document.getElementById('setup').style.display='';document.getElementById('su-user').textContent=u||'admin'}
async function setup(){const pw=document.getElementById('su-pw').value,pw2=document.getElementById('su-pw2').value,m=document.getElementById('sumsg');if(pw.length<4){m.textContent='密码至少 4 位';return}if(pw!==pw2){m.textContent='两次输入不一致';return}try{await api('/api/setup',{password:pw});show(true);boot()}catch(e){m.textContent=e.message}}
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
async function login(){try{await api('/api/login',{username:document.getElementById('user').value.trim(),password:document.getElementById('pw').value});try{await api('/api/status')}catch(e){document.getElementById('lmsg').textContent='登录成功，但浏览器没有保存登录状态：请清除本站 cookie 后重试';return}show(true);boot()}catch(e){document.getElementById('lmsg').textContent=e.message}}
async function logout(){await api('/api/logout',{});show(false)}
function set(id,v){document.getElementById(id).textContent=v}
async function status(){try{const s=await api('/api/status');const sys=s.sys||{};const pill=document.getElementById('pill');pill.className='pill '+(s.online?'on':'off');pill.lastElementChild.textContent=s.online?'在线':(s.srcds?'进程在，游戏未响应':'离线');
set('side-map',s.online?s.map:'—');set('side-players',s.online?`${s.players} / ${s.max}`:'—');
set('t-players',s.online?`${s.players} / ${s.max}`:'-');set('t-bots',s.online?`bot ${s.bots}`:'');set('t-map',s.online?s.map:'-');set('t-name',s.online?s.name:'');set('t-preset',s.preset||'-');set('t-diff','难度 '+(DIFF[s.difficulty]||'-')+' · 白名单'+(s.whitelist===null?'?':s.whitelist?'开':'关'));const load=sys.load?sys.load.split(' '):[],memPct=sys.mem_total_mb?Math.round(100*sys.mem_used_mb/sys.mem_total_mb)+'%':'-',proc=s.srcds?'运行中':'未运行';
set('f-load',load[0]||'-');set('f-mem',memPct);set('f-proc',proc);set('sy-load',load[0]||'-');set('sy-load-s',load.length>2?`5 分钟 ${load[1]} · 15 分钟 ${load[2]}`:'');set('sy-mem',memPct);set('sy-mem-s',sys.mem_total_mb?`${sys.mem_used_mb} / ${sys.mem_total_mb} MB`:'');set('sy-up',sys.uptime_h!=null?fmtUp(sys.uptime_h):'-');set('sy-proc',proc);
document.querySelectorAll('#seg-preset button').forEach(b=>b.classList.toggle('on',b.textContent===s.preset));document.querySelectorAll('#seg-diff button').forEach(b=>b.classList.toggle('on',b.dataset.v===s.difficulty));for(const [id,k] of [['dmg-ff','ff'],['dmg-burn','burn']]){const e=document.getElementById(id);if(e&&document.activeElement!==e&&s[k]!=null)e.value=s[k]}
set('t-fps',s.perf?s.perf.fps:'-');set('t-out',s.perf?s.perf.out_kb+' KB/s':'-');set('t-load',sys.load?sys.load.split(' ')[0]:'-');set('t-mem',sys.mem_used_mb?`内存 ${sys.mem_used_mb}/${sys.mem_total_mb} MB · 已运行 ${sys.uptime_h} h`:'');
if(s.whitelist!==undefined){wlOn=s.whitelist;renderSw()}if(s.features){document.querySelectorAll('[data-f]').forEach(e=>e.style.display=s.features[e.dataset.f]?'':'none');document.getElementById('pl-grid').classList.toggle('nowl',!s.features.whitelist)}if(s.title){set('brand',s.title);document.title=s.title}if(s.display_host){set('f-host','connect '+s.display_host);document.getElementById('f-conn').style.display=''}if(s.account){const wasOwner=myRole==='owner';myRole=s.account.role;set('who-name',s.account.user+(myRole==='owner'?' · owner':''));document.querySelectorAll('[data-owner]').forEach(e=>e.style.display=myRole==='owner'?'':'none');if(myRole==='owner'&&!wasOwner&&document.getElementById('v-accounts').classList.contains('on'))loadAccounts()}set('ts',new Date().toLocaleTimeString());set('actmsg',(s.action.running?'正在执行 '+s.action.running+'… ':'')+(s.action.last||''))}catch(e){}}
function mtab(k,btn){document.querySelectorAll('#mtabs button').forEach(b=>b.classList.toggle('on',b===btn));document.querySelectorAll('.mt').forEach(e=>e.classList.toggle('on',e.id==='mt-'+k))}
function fmtUp(h){const t=Math.round(h);return t>=48?Math.floor(t/24)+' d '+(t%24)+' h':h+' h'}
async function copyConn(){const t=document.getElementById('f-host').textContent;try{if(navigator.clipboard&&window.isSecureContext)await navigator.clipboard.writeText(t);else{const ta=document.createElement('textarea');ta.value=t;ta.style.cssText='position:fixed;opacity:0';document.body.appendChild(ta);ta.select();document.execCommand('copy');ta.remove()}toast('已复制：'+t)}catch(e){toast('复制失败，请手动选中文本复制',true)}}
async function act(n){const names={restart:'重启',start:'启动',stop:'停止',monitor:'巡检'};if(n!=='monitor'&&!confirm('确定'+names[n]+'服务器？'))return;await run('/api/action',{name:n},'已开始'+names[n]);setTimeout(status,2000);setTimeout(status,20000)}
async function preset(n){await run('/api/preset',{name:n},'特感预设已切换为 '+n);status()}
async function damage(){const o={};for(const [id,k] of [['dmg-ff','ff'],['dmg-burn','burn']]){const v=document.getElementById(id).value;if(v!=='')o[k]=+v}if(!Object.keys(o).length){toast('请填写至少一项',true);return}const j=await run('/api/damage',o,'伤害已更新'+(o.ff!=null?'：友伤 '+o.ff:'')+(o.burn!=null?'，火焰 '+o.burn:''));if(j&&j.persisted===false)toast('已生效，但 server.cfg 未写入（看控制台输出）',true);status()}
async function diff(l){await run('/api/difficulty',{level:l},'难度已设为 '+DIFF[l]+'，即时生效');status()}
async function changemap(){const m=document.getElementById('map').value;if(!confirm('切换到 '+m+'？当前进度会丢失'))return;await run('/api/map',{map:m},'切换中…');setTimeout(status,8000)}
function renderTargets(pl){const sel=document.getElementById('ptarget'),cur=sel.value;sel.innerHTML='<option value="@all">全体在线玩家'+(pl.length?'（'+pl.length+' 人）':'')+'</option>'+pl.map(p=>`<option value="#${p.userid}">${esc(p.name)}</option>`).join('')+'<option value="__custom">手动输入…</option>';if([...sel.options].some(o=>o.value===cur))sel.value=cur}
async function points(){const sel=document.getElementById('ptarget');let t=sel.value,label=sel.options[sel.selectedIndex].textContent;if(t==='__custom'){t=document.getElementById('pcustom').value.trim();label=t;if(!t){toast('请输入玩家名或 #userid',true);return}}const a=+document.getElementById('pamount').value;if(!a){toast('请输入分数',true);return}await run('/api/points',{target:t,amount:a},`已给 ${label} 发 ${a} 分`)}
let wlOn=null;function renderSw(){const sw=document.getElementById('sw-wl');sw.className='sw'+(wlOn===null?' dis':wlOn?' on':'');sw.setAttribute('aria-pressed',wlOn?'true':'false');set('wl-state',wlOn===null?'未知（服务器离线）':wlOn?'已开启：仅名单内可进':'已关闭：所有人可进')}
async function wlToggle(){if(wlOn===null)return;const v=!wlOn;if(!v&&!confirm('关闭白名单后任何人都能进服，确定？'))return;await run('/api/whitelist_enable',{enable:v},v?'白名单已开启':'白名单已关闭，现在所有人可进');wlOn=v;renderSw()}
async function loadPlayers(){try{const d=await api('/api/players');renderTargets(d.players);const mini=document.getElementById('players-mini');mini.innerHTML='<tr><th>名字</th><th>在线</th><th>延迟</th></tr>'+(d.players.length?d.players.map(p=>`<tr><td>${esc(p.name)}</td><td class="mu">${esc(p.time)}</td><td class="mu">${esc(p.ping)} ms</td></tr>`).join(''):'<tr><td colspan=3 class="mu">当前没有玩家</td></tr>');const t=document.getElementById('players');t.innerHTML='<tr><th>名字</th><th>在线</th><th>延迟</th><th></th></tr>'+(d.players.length?d.players.map(p=>`<tr><td><b>${esc(p.name)}</b><div><code class="mu">${esc(p.steamid)}</code></div></td><td class="mu">${esc(p.time)}</td><td class="mu">${esc(p.ping)} ms</td><td class="act">
<button class="g sm" onclick="givep('${esc(p.name)}')">发分</button> <button class="g sm" onclick="wladd('${esc(p.steamid)}','${esc(p.name)}')">加白</button> <button class="d sm" onclick="kick(${p.userid},'${esc(p.name)}')">踢</button></td></tr>`).join(''):'<tr><td colspan=4 class="mu">当前没有玩家</td></tr>')}catch(e){}}
async function givep(n){const a=prompt('给 '+n+' 发多少分？','200');if(a)await run('/api/points',{target:n,amount:+a},'已发放')}
async function wladd(id,n){await run('/api/whitelist',{op:'add',steamid:id,note:n},'已加入白名单：'+n);loadWl()}
async function kick(u,n){if(!confirm('踢出 '+n+'？'))return;await run('/api/kick',{userid:u},'已踢出');setTimeout(loadPlayers,1500)}
async function wl(op,id){id=id||document.getElementById('wlid').value.trim();const note=document.getElementById('wlnote').value;if(op==='del'&&!confirm('从白名单删除 '+id+'？'))return;try{const d=await run('/api/whitelist',{op,steamid:id,note});renderWl(d.list);if(op==='add')document.getElementById('wlid').value=''}catch(e){}}
function renderWl(l){set('wlcount',l.length?l.length+' 人':'空 = 对所有人开放');document.getElementById('wllist').innerHTML=l.map(x=>{const [id,...rest]=x.split(/\s+/);const note=rest.join(' ').replace(/^\/\/\s*/,'');return `<div class="wl"><span><code>${esc(id)}</code> <span class="mu">${esc(note)}</span></span><button class="g sm" onclick="wl('del','${esc(id)}')">删除</button></div>`}).join('')}
async function loadWl(){try{renderWl((await api('/api/whitelist')).list)}catch(e){}}
async function rcon(){const i=document.getElementById('cmd'),c=i.value.trim();if(!c)return;hist.push(c);i.value='';try{document.getElementById('rout').textContent='> '+c+'\n'+((await api('/api/rcon',{cmd:c})).out||'(无输出)')}catch(e){document.getElementById('rout').textContent='错误: '+e.message}}
async function logs(k,btn){curlog=k;if(btn){document.querySelectorAll('.tabs button').forEach(b=>b.classList.remove('on'));btn.classList.add('on')}try{const d=await api('/api/logs?'+k);const p=document.getElementById('logs');p.textContent=d.lines.join('\n')||'(空)';p.scrollTop=p.scrollHeight}catch(e){}}
function spark(id,vals,color,min,max){const el=document.getElementById(id),w=el.clientWidth||600,h=64;if(!vals.length){el.setAttribute('viewBox',`0 0 ${w} ${h}`);el.innerHTML='<text x="6" y="36">暂无采样（有玩家在线时每 15 秒记录一次）</text>';return}
const lo=min??Math.min(...vals),hi=max??Math.max(...vals),rng=(hi-lo)||1,L=44,R=50,px=i=>L+i/(vals.length-1||1)*(w-L-R),py=v=>h-8-(v-lo)/rng*(h-18);const pts=vals.map((v,i)=>px(i).toFixed(1)+','+py(v).toFixed(1)).join(' '),last=vals[vals.length-1];
el.setAttribute('viewBox',`0 0 ${w} ${h}`);el.innerHTML=`<polygon class="ar" fill="${color}" points="${px(0).toFixed(1)},${h-8} ${pts} ${px(vals.length-1).toFixed(1)},${h-8}"/><polyline class="ln" stroke="${color}" points="${pts}"/><text x="${L-6}" y="12" text-anchor="end">${hi.toFixed(1)}</text><text x="${L-6}" y="${h-4}" text-anchor="end">${lo.toFixed(1)}</text><text class="last" x="${w-R+6}" y="${(py(last)+4).toFixed(1)}" style="fill:${color}">${last.toFixed(1)}</text>`}
let perfRows=[],perfT;function drawPerf(){spark('c-fps',perfRows.map(r=>r.fps),'#5ed389',0,32);spark('c-out',perfRows.map(r=>r.out_kb),'#f0a13a',0,null)}
async function perf(){try{perfRows=(await api('/api/logs?perfjson')).rows;drawPerf()}catch(e){}}
addEventListener('resize',()=>{clearTimeout(perfT);perfT=setTimeout(drawPerf,150)});   // sparklines are sized to the card: redraw when the layout changes

function jobRow(label,j,extra,bar){return `<div class="job ${esc(j.state)}"><div class="jr"><i></i><span>${label}：${esc(j.msg)}</span>${extra||''}</div>${bar||''}</div>`}
async function loadAddons(){try{const d=await api('/api/addons');const el=document.getElementById('addons');
const jobs=Object.entries(d.jobs||{}).map(([id,j])=>jobRow('工坊 '+id,j,j.state==='running'?`<button class="g sm" onclick="wsCancel('${id}')">取消</button>`:'',j.state==='running'&&j.total?`<div class="bar"><span style="width:${Math.min(100,Math.round(100*(j.done||0)/j.total))}%"></span></div>`:'')).join('')+Object.entries(d.zips||{}).map(([t,j])=>jobRow('打包',j,j.state==='done'?` — <a href="/api/download?token=${t}">下载 ${esc(j.name)}（${j.size_mb} MB）</a>`:'')).join('');
el.innerHTML=jobs+(d.addons.length?'<div class="tw"><table><tr><th>文件</th><th>地图</th><th>大小</th><th></th></tr>'+d.addons.map(a=>`<tr><td><b>${esc(a.name)}</b>${a.mission?'<div class="mu">'+esc(a.mission)+'</div>':''}</td><td class="mu">${a.maps.length?a.maps.length+' 张：'+esc(a.maps.slice(0,3).join(', '))+(a.maps.length>3?'…':''):'—'}</td><td class="mu">${a.size_mb} MB</td><td class="act">${a.maps.length?`<button class="sm" onclick="gomap('${esc(a.maps[0])}')">切到第一章</button> `:''}<button class="g sm" onclick="zipAddon('${esc(a.name)}')">打包下载</button> ${a.protected?'':`<button class="d sm" onclick="delAddon('${esc(a.name)}')">删除</button>`}</td></tr>`).join('')+'</table></div>':'<div class="mu">还没有自定义战役</div>');
const sel=document.getElementById('map');const cur=sel.value;sel.innerHTML=MAPS.map(m=>`<option value="${m[0]}">${m[1]} · ${m[0]}</option>`).join('')+d.addons.filter(a=>a.maps.length).map(a=>`<optgroup label="${esc(a.name)}">`+a.maps.map(m=>`<option value="${esc(m)}">${esc(m)}</option>`).join('')+'</optgroup>').join('');if([...sel.options].some(o=>o.value===cur))sel.value=cur;
if(Object.values(d.jobs||{}).some(j=>j.state==='running')||Object.values(d.zips||{}).some(j=>j.state==='running'))setTimeout(loadAddons,3000)}catch(e){}}
async function gomap(m){if(!confirm('切换到 '+m+'？当前进度会丢失'))return;await run('/api/map',{map:m},'切换中…');setTimeout(status,8000)}
async function delAddon(n){if(!confirm('删除 '+n+'？'))return;await run('/api/addons',{op:'delete',name:n},'已删除 '+n);loadAddons()}
async function zipAddon(name){try{const r=await api('/api/addons',{op:'zip',name});toast('开始打包 '+name+'…');loadAddons();pollZip(r.token)}catch(e){toast(e.message,true)}}
async function pollZip(token){for(let i=0;i<200;i++){await new Promise(r=>setTimeout(r,1500));let d;try{d=await api('/api/addons')}catch(e){return}const j=(d.zips||{})[token];if(!j||j.state==='running')continue;loadAddons();if(j.state==='done'){toast('打包完成，开始下载');window.location='/api/download?token='+token}else toast('打包失败: '+j.msg,true);return}}
async function loadPlugins(){try{renderPlugins(await api('/api/plugins'))}catch(e){}}
function renderPlugins(d){const el=document.getElementById('plugins');
el.innerHTML='<div class="tw"><table><tr><th>启用中（plugins/）</th><th></th></tr>'+(d.enabled.length?d.enabled.map(p=>`<tr><td><code>${esc(p.file)}</code>${p.protected?' <span class="mu">受保护</span>':''}</td><td class="act"><button class="g sm" data-a="reload" data-f="${esc(p.file)}">重载</button> ${p.protected?'':`<button class="d sm" data-a="disable" data-f="${esc(p.file)}">禁用</button>`}</td></tr>`).join(''):'<tr><td colspan=2 class="mu">没有启用的插件</td></tr>')+'</table></div>'+(d.disabled.length?'<div class="k" style="margin:16px 0 6px">已禁用（disabled/）</div><div class="tw"><table>'+d.disabled.map(p=>`<tr><td><code class="mu">${esc(p.file)}</code></td><td class="act"><button class="sm" data-a="enable" data-f="${esc(p.file)}">启用</button> <button class="d sm" data-a="delete" data-f="${esc(p.file)}">删除</button></td></tr>`).join('')+'</table></div>':'');
document.getElementById('plugins-raw').textContent=d.raw||'(服务器离线或无输出)';
el.querySelectorAll('button[data-a]').forEach(b=>b.onclick=()=>pluginAct(b.dataset.a,b.dataset.f));}
async function pluginAct(op,file){const names={reload:'重载',disable:'禁用',enable:'启用',delete:'删除'};if((op==='disable'||op==='delete')&&!confirm(names[op]+'插件 '+file+'？'))return;try{const d=await api('/api/plugins',{op,file});toast(short(d.out)||names[op]+'完成');renderPlugins(d)}catch(e){toast(e.message,true)}}
async function uploadSmx(){const f=document.getElementById('smxfile').files[0];if(!f){toast('先选择一个 .smx 文件',true);return}const m=document.getElementById('smxmsg');m.textContent='上传中 '+f.name+'…';try{const r=await new Promise((res,rej)=>{const x=new XMLHttpRequest();x.open('POST','/api/plugin_upload?name='+encodeURIComponent(f.name));x.onload=()=>res(JSON.parse(x.responseText));x.onerror=()=>rej(new Error('网络错误'));x.send(f)});if(r.error)throw new Error(r.error);m.textContent='';toast('已上传并加载：'+short(r.out));renderPlugins(r)}catch(e){m.textContent='失败: '+e.message}}
async function loadAccounts(){try{renderAccounts(await api('/api/accounts'))}catch(e){toast(e.message,true)}}
async function loadMe(){try{const m=await api('/api/me');set('me-info',m.username+' · '+m.role+(m.steamid?' · '+m.steamid:''));document.getElementById('me-steam').value=m.steamid||''}catch(e){}}
async function changePw(){const cur=document.getElementById('me-cur').value,nw=document.getElementById('me-new').value,nw2=document.getElementById('me-new2').value;if(!cur||!nw){toast('填写当前密码和新密码',true);return}if(nw!==nw2){toast('两次输入的新密码不一致',true);return}try{await run('/api/me',{op:'password',current:cur,password:nw},'密码已修改');for(const id of ['me-cur','me-new','me-new2'])document.getElementById(id).value=''}catch(e){}}
async function bindSteam(){const v=document.getElementById('me-steam').value.trim();try{await run('/api/me',{op:'steamid',steamid:v},v?'已绑定 Steam':'已解绑');loadMe();if(myRole==='owner')loadAccounts()}catch(e){}}
function renderAccounts(d){const t=document.getElementById('accounts');t.innerHTML='<tr><th>用户名</th><th>角色</th><th>绑定 SteamID</th><th>权限</th><th>最近登录</th><th></th></tr>'+d.accounts.map(a=>{const last=a.last_login?new Date(a.last_login*1000).toLocaleString():'—';return `<tr><td><b>${esc(a.username)}</b>${a.username===d.me?' <span class="mu">(我)</span>':''}</td><td>${esc(a.role)}</td><td><code class="mu">${esc(a.steamid||'—')}</code></td><td class="mu">${esc(a.flags||'')}</td><td class="mu">${esc(last)}</td><td class="act"><button class="g sm" data-e="${a.id}">编辑</button> ${a.username===d.me?'':`<button class="d sm" data-x="${a.id}" data-u="${esc(a.username)}">删除</button>`}</td></tr>`}).join('');
window._accts=d.accounts;t.querySelectorAll('button[data-e]').forEach(b=>b.onclick=()=>editAccount(window._accts.find(a=>a.id==b.dataset.e)));t.querySelectorAll('button[data-x]').forEach(b=>b.onclick=()=>delAccount(b.dataset.x,b.dataset.u));}
async function createAccount(){const u=document.getElementById('na-user').value.trim(),pw=document.getElementById('na-pw').value,role=document.getElementById('na-role').value,steamid=document.getElementById('na-steam').value.trim(),flags=document.getElementById('na-flags').value.trim();if(!u||!pw){toast('填写用户名和密码',true);return}try{await run('/api/accounts',{op:'create',username:u,password:pw,role,steamid,flags},'已创建账号 '+u);document.getElementById('na-user').value='';document.getElementById('na-pw').value='';document.getElementById('na-steam').value='';loadAccounts()}catch(e){}}
async function delAccount(id,u){if(!confirm('删除账号 '+u+'？'))return;try{await run('/api/accounts',{op:'delete',id:+id},'已删除 '+u);loadAccounts()}catch(e){}}
async function editAccount(a){const steamid=prompt('绑定 Steam（留空 = 解绑；绑定后写入游戏管理员）\n支持 SteamID / 主页链接 / 17位好友码：',a.steamid||'');if(steamid===null)return;const pw=prompt('设置新密码（留空 = 不改）：','');if(pw===null)return;const body={op:'update',id:a.id,steamid:steamid.trim()};if(pw)body.password=pw;try{await run('/api/accounts',body,'已保存 '+a.username);loadAccounts()}catch(e){}}
async function wsCancel(id){try{await run('/api/addons',{op:'workshop_cancel',id},'正在取消…');setTimeout(loadAddons,1500)}catch(e){}}
async function workshop(){const id=document.getElementById('wsid').value.trim();if(!id)return;await run('/api/addons',{op:'workshop',id},'开始下载，完成后自动安装');document.getElementById('wsid').value='';setTimeout(loadAddons,1500)}
async function upload(){const f=document.getElementById('vpkfile').files[0];if(!f){toast('先选择一个 .vpk 或 .zip 文件',true);return}const m=document.getElementById('upmsg');m.textContent='上传中 '+f.name+' ('+(f.size/1048576).toFixed(1)+' MB)…';
try{const r=await new Promise((res,rej)=>{const x=new XMLHttpRequest();x.open('POST','/api/upload?name='+encodeURIComponent(f.name));x.upload.onprogress=e=>{if(e.lengthComputable)m.textContent=e.loaded<e.total?'上传中 '+Math.round(e.loaded/e.total*100)+'% · '+f.name:'已上传，正在检查并安装 '+f.name+'…'};x.onload=()=>res(JSON.parse(x.responseText));x.onerror=()=>rej(new Error('网络错误'));x.send(f)});if(r.error)throw new Error(r.error);
m.textContent='已安装 '+r.installed.map(a=>a.name+'（'+a.maps.length+' 张地图）').join('、')+(r.skipped.length?'；跳过：'+r.skipped.map(s=>s.reason).join('；'):'');toast('上传完成'+(r.skipped.length?'，有 '+r.skipped.length+' 个文件被拒收':''),!!r.skipped.length);loadAddons()}catch(e){m.textContent='失败: '+e.message;toast(e.message,true)}}
let wsQ='',wsPage=1,wsTotal=0,wsItems=[];
function wsRender(){const el=document.getElementById('wsres');if(!wsItems.length){el.innerHTML='<div class="mu">没有找到相关战役</div>';return}
el.innerHTML='<div class="tw"><table><tr><th></th><th>战役</th><th>大小</th><th>订阅</th><th>更新</th><th></th></tr>'+wsItems.map(i=>`<tr><td>${i.preview?`<img class="thumb" src="${esc(i.preview)}" alt="" loading="lazy" onerror="this.style.display='none'">`:''}</td><td><b>${esc(i.title)}</b><div class="mu">${esc(i.tags.join(' · '))}${i.desc?(i.tags.length?' — ':'')+esc(i.desc):''}</div><code class="mu">${esc(i.id)}</code></td><td class="mu">${i.size_mb} MB</td><td class="mu">${i.subs.toLocaleString()}</td><td class="mu">${i.updated?new Date(i.updated*1000).toLocaleDateString():'—'}</td><td class="act"><button class="sm" onclick="wsInstall('${esc(i.id)}',this)">安装</button></td></tr>`).join('')+'</table></div>'+(wsItems.length<wsTotal?`<div class="row"><button class="g sm" onclick="wsSearch(true)">加载更多</button><span class="mu">已显示 ${wsItems.length} / ${wsTotal}</span></div>`:'')}
async function wsSearch(more){const el=document.getElementById('wsres');if(more)wsPage++;else{wsQ=document.getElementById('wsq').value.trim();wsPage=1;wsItems=[];el.innerHTML='<div class="mu">搜索中…</div>'}
try{const d=await api('/api/workshop_search?q='+encodeURIComponent(wsQ)+'&page='+wsPage);wsItems=wsItems.concat(d.items);wsTotal=d.total;wsRender()}catch(e){if(!more)el.innerHTML='<div class="mu">'+esc(e.message)+'</div>';toast(e.message,true)}}
async function wsInstall(id,btn){btn.disabled=true;btn.textContent='已开始下载';try{await run('/api/addons',{op:'workshop',id},'开始下载，完成后自动安装');setTimeout(loadAddons,1500)}catch(e){btn.disabled=false;btn.textContent='安装'}}
function boot(){document.getElementById('map').innerHTML=MAPS.map(m=>`<option value="${m[0]}">${m[1]} · ${m[0]}</option>`).join('');let v=location.hash.slice(1);if(!TITLES[v]){v='overview';try{v=localStorage.getItem('l4d2view')||v}catch(e){}}nav(v);status();loadPlayers();loadWl();loadAddons();logs('console');perf();setInterval(status,10000);setInterval(loadPlayers,30000);setInterval(perf,60000)}
(async()=>{try{await api('/api/status');show(true);boot()}catch(e){try{const s=await (await fetch('/api/setup')).json();if(s.needed){showSetup(s.username);return}}catch(e2){}show(false)}})();
"""
PAGE = ('<!doctype html><html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>L4D2 Ops Panel</title>'
        '<link rel="icon" href="data:image/svg+xml,' + quote(MARK) + '">'
        # webfonts are progressive enhancement: loaded without blocking rendering, the CSS font stacks cover the rest
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap" media="print" onload="this.media=\'all\'">'
        '<style>' + CSS + '</style></head><body>' + BODY + '<script>' + JS + '</script></body></html>').replace('%MAPS%', json.dumps(MAPS, ensure_ascii=False))

if __name__ == '__main__':
    port = int(CONF['port']); bind = CONF['bind']
    srv = ThreadingHTTPServer((bind, port), H)
    if CONF['tls']:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); ctx.load_cert_chain(_abs(CONF['cert']), _abs(CONF['key']))
        srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    print(f'L4D2 panel listening on {bind}:{port} tls={bool(CONF["tls"])} config={CONF_PATH}', flush=True)
    srv.serve_forever()
