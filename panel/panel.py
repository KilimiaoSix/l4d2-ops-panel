#!/usr/bin/env python3
"""L4D2 Ops Panel — a single-file web panel for Left 4 Dead 2 dedicated servers (Python 3 stdlib only).

Talks to the game over RCON / A2S, optionally drives LinuxGSM for start/stop, reads logs and a perf CSV,
manages custom campaigns (upload / Steam Workshop download) and integrates with a few SourceMod plugins
when they are present (Private Whitelist, SI Preset, Points System). Everything is configured in panel.json.
"""
import json, os, re, ssl, socket, struct, subprocess, threading, time, secrets, sys, glob
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, unquote

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
}
CONF = dict(DEFAULTS)
try:
    CONF.update(json.load(open(CONF_PATH, encoding='utf-8')))
except FileNotFoundError:
    sys.exit(f'config not found: {CONF_PATH} (copy panel.example.json to panel.json or run install.sh)')
if not CONF['password']:
    sys.exit('panel.json: "password" must be set')
def _abs(p): return p if (not p or os.path.isabs(p)) else os.path.join(DIR, p)
GAME = CONF['game_dir']
CONSOLE_LOG = CONF['console_log']; PERF_CSV = CONF['perf_csv']
WHITELIST = os.path.join(GAME, 'addons', 'sourcemod', 'configs', 'whitelist.txt')
SM_LOGS = os.path.join(GAME, 'addons', 'sourcemod', 'logs')
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
        while len(raw) < 4: raw += s.recv(4 - len(raw))
        n = struct.unpack('<i', raw)[0]; d = b''
        while len(d) < n: d += s.recv(n - len(d))
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

def a2s():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.settimeout(2)
    req = b'\xFF\xFF\xFF\xFFTSource Engine Query\x00'
    try:
        addr = (CONF['rcon_host'], int(CONF['rcon_port']))
        s.sendto(req, addr); d, _ = s.recvfrom(4096)
        if d[4:5] == b'A': s.sendto(req + d[5:9], addr); d, _ = s.recvfrom(4096)
        p = 6; f = []
        for _ in range(4):
            e = d.index(b'\x00', p); f.append(d[p:e].decode('utf-8', 'replace')); p = e + 1
        return {'online': True, 'name': f[0], 'map': f[1], 'players': d[p+2], 'max': d[p+3], 'bots': d[p+4]}
    except Exception:
        return {'online': False}
    finally:
        s.close()

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
JOBS = {}   # workshop download jobs: id -> {state, msg, files}

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

def addon_info(name):
    path = os.path.join(ADDONS, name)
    ents = vpk_entries(path)
    maps = sorted(e.split('/')[-1][:-4] for e in ents if e.startswith('maps/') and e.endswith('.bsp'))
    title = ''
    for e in ents:
        if e.startswith('missions/') and e.endswith('.txt'):
            title = e.split('/')[-1][:-4]; break
    return {'name': name, 'size_mb': round(os.path.getsize(path) / 1048576, 1), 'maps': maps, 'mission': title, 'protected': name in PROTECTED}

def list_addons():
    return [addon_info(n) for n in sorted(os.listdir(ADDONS)) if n.lower().endswith('.vpk')]

def safe_vpk_name(n):
    n = os.path.basename(n).strip()
    n = re.sub(r'[^\w.\-一-鿿 ]', '_', n)
    return n if n.lower().endswith('.vpk') and len(n) > 4 else None

def refresh_addons():
    try: return Rcon.run('update_addon_paths') + '\n' + Rcon.run('mission_reload')
    except Exception as e: return f'(热加载失败: {e}，重启服务器后生效)'

def workshop_job(pubid):
    JOBS[pubid] = {'state': 'running', 'msg': '正在从创意工坊下载…', 'files': []}
    tmp = os.path.join(DIR, 'workshop_tmp', pubid)
    try:
        subprocess.run(['rm', '-rf', tmp]); os.makedirs(tmp, exist_ok=True)
        r = subprocess.run([CONF['depotdownloader'], '-app', '550', '-pubfile', pubid, '-dir', tmp], capture_output=True, text=True, timeout=1800)
        found = []
        for root, _, files in os.walk(tmp):
            for fn in files:
                if fn.lower().endswith('.vpk'):
                    dst = os.path.join(ADDONS, safe_vpk_name(fn) or f'workshop_{pubid}.vpk')
                    os.replace(os.path.join(root, fn), dst); found.append(os.path.basename(dst))
        if found:
            JOBS[pubid] = {'state': 'done', 'msg': '已安装: ' + ', '.join(found) + ' ' + refresh_addons(), 'files': found}
        else:
            tail_ = '\n'.join(r.stdout.strip().splitlines()[-3:])
            JOBS[pubid] = {'state': 'error', 'msg': '没有下载到 vpk（ID 错误、物品被删除或需要登录）: ' + tail_, 'files': []}
    except Exception as e:
        JOBS[pubid] = {'state': 'error', 'msg': f'下载失败: {e}', 'files': []}
    finally:
        subprocess.run(['rm', '-rf', tmp])


FEAT = {'t': 0, 'v': {}}
def features(online):
    """Which optional parts are available: detected from installed SourceMod plugins + local tools (cached 120 s)."""
    now = time.time()
    if now - FEAT['t'] < 120 and FEAT['v']: return FEAT['v']
    f = {'lgsm': bool(CONF['lgsm_script']) and os.path.exists(CONF['lgsm_script']),
         'workshop': bool(CONF['depotdownloader']) and os.path.exists(CONF['depotdownloader']),
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

SESS_PATH = os.path.join(DIR, 'sessions.json')
def _load_sessions():
    try:
        d = json.load(open(SESS_PATH)); now = time.time()
        return {k: v for k, v in d.items() if v > now}
    except Exception:
        return {}
def _save_sessions():
    try:
        tmp = SESS_PATH + '.tmp'
        with open(tmp, 'w') as f: json.dump(SESSIONS, f)
        os.chmod(tmp, 0o600); os.replace(tmp, SESS_PATH)
    except Exception:
        pass
SESSIONS = _load_sessions(); FAILS = {}
def client_ip(h):
    return (h.headers.get('X-Forwarded-For', '').split(',')[0].strip() or h.client_address[0])

def check_session(h):
    c = h.headers.get('Cookie', '')
    m = re.search(r'(?:^|;\s*)l4d2panel=([A-Za-z0-9_-]+)', c)
    return bool(m and SESSIONS.get(m.group(1), 0) > time.time())

def q(s): return '"' + s.replace('"', '') + '"'

class H(BaseHTTPRequestHandler):
    server_version = 'l4d2panel/1.0'
    def log_message(self, fmt, *a):
        if '/api/status' not in (a[0] if a else ''): super().log_message(fmt, *a)
    def send_json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code); self.send_header('Content-Type', 'application/json; charset=utf-8'); self.send_header('Cache-Control', 'no-store'); self.send_header('Content-Length', len(b)); self.end_headers(); self.wfile.write(b)
    def body(self):
        n = int(self.headers.get('Content-Length', 0) or 0)
        try: return json.loads(self.rfile.read(n) or b'{}')
        except Exception: return {}
    def do_GET(self):
        p = urlparse(self.path).path
        if p == '/':
            b = PAGE.encode(); self.send_response(200); self.send_header('Content-Type', 'text/html; charset=utf-8'); self.send_header('Cache-Control', 'no-store'); self.send_header('Content-Length', len(b)); self.end_headers(); self.wfile.write(b); return
        if not check_session(self): return self.send_json({'error': 'auth'}, 401)
        try:
            if p == '/api/status':
                st = a2s(); st['sys'] = sysinfo(); st['action'] = ACTION; st['srcds'] = subprocess.run(['pgrep', '-f', 'srcds_linux'], capture_output=True).returncode == 0
                st['features'] = fe = features(st['online']); st['title'] = CONF['panel_title']; st['display_host'] = CONF['display_host']
                rows = tail(PERF_CSV, 2); c = rows[-1].split(',') if len(rows) > 1 else []
                st['perf'] = {'t': c[0], 'fps': c[5], 'out_kb': round(float(c[4]) / 1024, 1)} if len(c) >= 7 else None
                try:
                    m = re.search(r'当前: (\w+)', Rcon.run('sm_preset')) if (st['online'] and fe['preset']) else None
                    st['preset'] = m.group(1) if m else ''
                    w = re.search(r'"sm_whitelist_enable"[^"]*"(\d)"', Rcon.run('sm_cvar sm_whitelist_enable')) if (st['online'] and fe['whitelist']) else None
                    st['whitelist'] = (w.group(1) == '1') if w else None
                    dd = re.search(r'"z_difficulty" = "(\w+)"', Rcon.run('z_difficulty')) if st['online'] else None
                    st['difficulty'] = dd.group(1).lower() if dd else ''
                except Exception: st['preset'] = ''; st['whitelist'] = None
                return self.send_json(st)
            if p == '/api/players':
                pl, raw = players(); return self.send_json({'players': pl, 'raw': raw})
            if p == '/api/whitelist': return self.send_json({'list': read_whitelist()})
            if p == '/api/addons': return self.send_json({'addons': list_addons(), 'jobs': JOBS})
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
        p = urlparse(self.path).path; d = {} if p == '/api/upload' else self.body(); ip = client_ip(self)
        if p == '/api/login':
            f = FAILS.get(ip, [0, 0])
            if f[0] >= 5 and time.time() - f[1] < 60: return self.send_json({'error': '失败太多，1 分钟后再试'}, 429)
            if secrets.compare_digest(str(d.get('password', '')).encode(), CONF['password'].encode()):
                sid = secrets.token_urlsafe(32); SESSIONS[sid] = time.time() + int(CONF['session_days']) * 86400; FAILS.pop(ip, None); _save_sessions()
                self.send_response(200); secure = '; Secure' if self.headers.get('X-Forwarded-Proto', '') == 'https' else ''
                self.send_header('Set-Cookie', f'l4d2panel={sid}; Path=/; HttpOnly{secure}; SameSite=Lax; Max-Age={int(CONF["session_days"]) * 86400}'); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', '11'); self.end_headers(); self.wfile.write(b'{"ok":true}'); return
            FAILS[ip] = [f[0] + 1, time.time()]; time.sleep(1); return self.send_json({'error': '密码错误'}, 403)
        if not check_session(self): return self.send_json({'error': 'auth'}, 401)
        try:
            if p == '/api/logout':
                m = re.search(r'(?:^|;\s*)l4d2panel=([A-Za-z0-9_-]+)', self.headers.get('Cookie', '')); SESSIONS.pop(m.group(1), None) if m else None; _save_sessions(); return self.send_json({'ok': True})
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
                n = d.get('name');  assert n in ('auto', 'te8', 'te12', 'te16'); return self.send_json({'out': Rcon.run('sm_preset ' + n)})
            if p == '/api/difficulty':
                n = d.get('level'); assert n in ('easy', 'normal', 'hard', 'impossible'); return self.send_json({'out': Rcon.run('z_difficulty ' + n)})
            if p == '/api/map':
                m = str(d.get('map', '')); assert re.match(r'^[a-z0-9_]+$', m); return self.send_json({'out': Rcon.run('changelevel ' + m)})
            if p == '/api/points':
                amt = int(d.get('amount', 0)); tgt = str(d.get('target', '@all')).strip() or '@all'
                tgt = tgt if tgt.startswith('@') or tgt.startswith('#') else q(tgt)
                return self.send_json({'out': Rcon.run(f'sm_givepoints {tgt} {amt}')})
            if p == '/api/kick':
                uid = int(d.get('userid')); return self.send_json({'out': Rcon.run(f'kickid {uid} {q(str(d.get("reason", "由管理面板踢出")))}')})
            if p == '/api/whitelist':
                op = d.get('op'); sid = str(d.get('steamid', '')).strip()
                assert re.match(r'^STEAM_[01]:[01]:\d+$', sid), '无效 SteamID'
                if op == 'add': out = Rcon.run(f'sm_wl_addid {sid} {q(str(d.get("note", "")))}')
                elif op == 'del': out = Rcon.run(f'sm_wl_del {sid}')
                else: return self.send_json({'error': 'bad op'}, 400)
                return self.send_json({'out': out, 'list': read_whitelist()})
            if p == '/api/upload':
                qs = urlparse(self.path).query; name = safe_vpk_name(unquote(qs.split('name=', 1)[1])) if 'name=' in qs else None
                if not name: return self.send_json({'error': '只接受 .vpk 文件'}, 400)
                n = int(self.headers.get('Content-Length', 0) or 0)
                if n <= 0 or n > int(CONF['max_upload_mb']) * 1048576: return self.send_json({'error': f'文件为空或超过 {CONF["max_upload_mb"]}MB'}, 400)
                tmp = os.path.join(ADDONS, name + '.uploading'); got = 0
                with open(tmp, 'wb') as f:
                    while got < n:
                        chunk = self.rfile.read(min(1048576, n - got))
                        if not chunk: break
                        f.write(chunk); got += len(chunk)
                if got != n: os.remove(tmp); return self.send_json({'error': f'上传中断 ({got}/{n})'}, 400)
                with open(tmp, 'rb') as f: magic = f.read(4)
                if magic != b'\x34\x12\xaa\x55': os.remove(tmp); return self.send_json({'error': '不是有效的 VPK 文件'}, 400)
                os.replace(tmp, os.path.join(ADDONS, name))
                return self.send_json({'ok': True, 'addon': addon_info(name), 'out': refresh_addons()})
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
                return self.send_json({'error': 'bad op'}, 400)
            if p == '/api/whitelist_enable':
                v = 1 if d.get('enable') else 0; return self.send_json({'out': Rcon.run(f'sm_cvar sm_whitelist_enable {v}')})
            return self.send_json({'error': 'not found'}, 404)
        except AssertionError as e:
            return self.send_json({'error': str(e) or 'bad request'}, 400)
        except Exception as e:
            return self.send_json({'error': str(e)}, 500)

PAGE = r"""<!doctype html><html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>L4D2 Ops Panel</title><link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🧟</text></svg>">
<style>
:root{--bg:#0b0f14;--sur:#121820;--sur2:#182029;--bd:#233041;--tx:#e8eef5;--mu:#8a9bb0;--ac:#4f8cff;--ok:#3ddc97;--warn:#ffb454;--bad:#ff5c5c;--r:12px}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--tx);font:14px/1.5 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei","Segoe UI",sans-serif}
a{color:var(--ac)}#app{display:flex;min-height:100vh}#side{width:210px;flex:none;background:var(--sur);border-right:1px solid var(--bd);display:flex;flex-direction:column}#side .brand{padding:16px 14px;font-weight:600;font-size:15px;border-bottom:1px solid var(--bd)}#side nav{display:flex;flex-direction:column;padding:8px}#side nav button{background:transparent;color:var(--mu);text-align:left;padding:10px 12px;border-radius:8px;font-size:13px}#side nav button:hover{background:var(--sur2);color:var(--tx)}#side nav button.on{background:var(--ac);color:#fff}#main{flex:1;min-width:0;padding:16px 20px;max-width:1200px}.view{display:none}.view.on{display:block}@media(max-width:860px){#app{flex-direction:column}#side{width:auto;border-right:0;border-bottom:1px solid var(--bd)}#side .brand{display:none}#side nav{flex-direction:row;overflow-x:auto;gap:4px}#side nav button{white-space:nowrap;padding:8px 10px}#side>div.mu{display:none}#main{padding:12px}}
header{display:flex;align-items:center;gap:12px;padding:4px 0 14px;border-bottom:1px solid var(--bd);margin-bottom:16px}
header h1{font-size:17px;margin:0;font-weight:600;white-space:nowrap}@media(max-width:480px){header h1{font-size:15px}.wrap{padding:10px}}header .sp{flex:1}
.pill{display:inline-flex;align-items:center;gap:6px;padding:4px 10px;border-radius:999px;font-size:12px;background:var(--sur2);border:1px solid var(--bd)}
.pill i{width:8px;height:8px;border-radius:50%;background:var(--mu)}.pill.on i{background:var(--ok);box-shadow:0 0 8px var(--ok)}.pill.off i{background:var(--bad)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:16px}
.tile{background:var(--sur);border:1px solid var(--bd);border-radius:var(--r);padding:12px 14px}.tile .k{font-size:12px;color:var(--mu)}.tile .v{font-size:20px;font-weight:600;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.tile .s{font-size:11px;color:var(--mu)}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}@media(max-width:860px){.grid{grid-template-columns:1fr}}
.card{background:var(--sur);border:1px solid var(--bd);border-radius:var(--r);padding:14px;margin-bottom:14px}
.card h2{font-size:14px;margin:0 0 10px;display:flex;align-items:center;gap:8px}.card h2 .sp{flex:1}
.row{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:6px 0}.lbl{color:var(--mu);font-size:12px;min-width:48px}
button{background:var(--ac);color:#fff;border:0;border-radius:8px;padding:8px 13px;font-size:13px;cursor:pointer;transition:.15s;font-family:inherit}button:hover{filter:brightness(1.1)}button:disabled{opacity:.5;cursor:default}
button.g{background:var(--sur2);border:1px solid var(--bd);color:var(--tx)}button.d{background:var(--bad)}button.sm{padding:5px 9px;font-size:12px}
.seg{display:inline-flex;background:var(--sur2);border:1px solid var(--bd);border-radius:8px;overflow:hidden}.seg button{background:transparent;color:var(--mu);border-radius:0;padding:7px 12px}.seg button.on{background:var(--ac);color:#fff}
input,select{background:#0d1219;color:var(--tx);border:1px solid var(--bd);border-radius:8px;padding:8px 10px;font-size:13px;font-family:inherit}input:focus,select:focus{outline:1px solid var(--ac)}input[type=file]{color:var(--mu)}input[type=file]::file-selector-button{background:var(--sur2);color:var(--tx);border:1px solid var(--bd);border-radius:6px;padding:5px 10px;margin-right:8px;font-family:inherit;cursor:pointer}
table{width:100%;border-collapse:collapse;font-size:13px}th{color:var(--mu);font-weight:500;font-size:12px;text-align:left;padding:6px 8px;border-bottom:1px solid var(--bd)}td{padding:8px;border-bottom:1px solid #1b2530;vertical-align:middle}tr:last-child td{border-bottom:0}
pre{background:#0d1219;border:1px solid var(--bd);padding:10px;border-radius:8px;max-height:340px;overflow:auto;font:12px/1.45 ui-monospace,Menlo,Consolas,monospace;white-space:pre-wrap;margin:0}
.mu{color:var(--mu);font-size:12px}.tabs{display:flex;gap:6px}.tabs button{background:var(--sur2);border:1px solid var(--bd);color:var(--mu);padding:5px 10px;font-size:12px}.tabs button.on{background:var(--ac);color:#fff;border-color:var(--ac)}
#toast{position:fixed;left:50%;bottom:24px;transform:translateX(-50%);background:#1d2733;border:1px solid var(--bd);padding:10px 16px;border-radius:10px;font-size:13px;box-shadow:0 8px 30px #0008;opacity:0;pointer-events:none;transition:.2s;max-width:90vw}#toast.show{opacity:1}
#login{max-width:360px;margin:12vh auto;text-align:center}body{padding:0}code{background:var(--sur2);padding:1px 5px;border-radius:4px;font-size:12px}#login input{width:100%;margin:12px 0;font-size:15px;padding:11px}#login button{width:100%;padding:11px;font-size:15px}
.sw{position:relative;width:46px;height:26px;background:#3a4250;border-radius:999px;cursor:pointer;transition:.2s;flex:none}.sw::after{content:'';position:absolute;top:3px;left:3px;width:20px;height:20px;border-radius:50%;background:#fff;transition:.2s}.sw.on{background:var(--ok)}.sw.on::after{left:23px}.sw.dis{opacity:.4;cursor:default}
canvas{width:100%;height:56px;display:block}.wl{display:flex;justify-content:space-between;align-items:center;padding:6px 8px;border-bottom:1px solid #1b2530;font-size:13px}.wl:last-child{border:0}.wl code{color:var(--mu)}
</style></head><body>
<div id="login" class="card"><div style="font-size:40px">🧟</div><h2 style="margin:6px 0">L4D2 Ops Panel</h2><div class="mu">Left 4 Dead 2 服务器运维面板</div><input id="pw" type="password" placeholder="密码" onkeydown="if(event.key==='Enter')login()"><button onclick="login()">登录</button><div id="lmsg" class="mu" style="margin-top:8px;color:var(--bad)"></div></div>
<div id="app" style="display:none">
<aside id="side"><div class="brand" id="brand">🧟 L4D2 面板</div>
<nav>
<button data-v="overview" onclick="nav('overview')">📊 概览</button>
<button data-v="players" onclick="nav('players')">👥 玩家 / 白名单</button>
<button data-v="game" onclick="nav('game')">🎮 游戏设置</button>
<button data-v="maps" onclick="nav('maps')">🗺️ 地图 / 战役</button>
<button data-v="console" onclick="nav('console')">⌨️ 控制台</button>
<button data-v="logs" onclick="nav('logs')">📜 日志 / 性能</button>
<button data-v="server" onclick="nav('server')">🖥️ 服务器</button>
</nav><div class="mu" id="sidehost" style="padding:12px 14px;font-size:11px"></div></aside>
<div id="main">
<header><h1 id="vtitle">概览</h1><span id="pill" class="pill"><i></i><span>连接中</span></span><span class="sp"></span><span id="ts" class="mu"></span><button class="g sm" onclick="logout()">退出</button></header>

<section class="view" id="v-overview">
<div class="tiles">
<div class="tile"><div class="k">玩家</div><div class="v" id="t-players">-</div><div class="s" id="t-bots"></div></div>
<div class="tile"><div class="k">地图</div><div class="v" id="t-map" style="font-size:16px">-</div><div class="s" id="t-name"></div></div>
<div class="tile"><div class="k">特感预设</div><div class="v" id="t-preset">-</div><div class="s" id="t-diff"></div></div>
<div class="tile"><div class="k">Server FPS</div><div class="v" id="t-fps">-</div><div class="s">≥ 29 正常（有人时采样）</div></div>
<div class="tile"><div class="k">出流量</div><div class="v" id="t-out">-</div><div class="s">5M 带宽上限 ≈ 625 KB/s</div></div>
<div class="tile"><div class="k">系统负载</div><div class="v" id="t-load">-</div><div class="s" id="t-mem"></div></div>
</div>
<div class="grid"><div class="card"><h2>性能<span class="sp"></span><span class="mu">最近 120 次采样</span></h2><div class="mu" style="margin-bottom:2px">Server FPS</div><canvas id="c-fps"></canvas><div class="mu" style="margin:8px 0 2px">出流量 KB/s</div><canvas id="c-out"></canvas></div>
<div class="card"><h2>在线玩家<span class="sp"></span><button class="g sm" onclick="nav('players')">管理</button></h2><table id="players-mini"></table></div></div>
</section>

<section class="view" id="v-players">
<div class="card"><h2>在线玩家<span class="sp"></span><button class="g sm" onclick="loadPlayers()">刷新</button></h2><table id="players"></table></div>
<div class="card" data-f="whitelist"><h2>白名单<span class="sp"></span><span id="wlcount" class="mu"></span></h2>
<div class="row" style="margin-bottom:10px"><span id="sw-wl" class="sw dis" onclick="wlToggle()"></span><span id="wl-state" class="mu">读取中…</span></div>
<div class="mu" style="margin-bottom:8px">开启 = 只有名单里的人和管理员能进；关闭 = 任何人都能进（临时给朋友开门时用，加完人记得开回来）。</div>
<div class="row"><input id="wlid" placeholder="STEAM_1:x:y" style="flex:1;min-width:150px"><input id="wlnote" placeholder="备注" style="width:110px"><button onclick="wl('add')">添加</button></div><div id="wllist"></div></div>
</section>

<section class="view" id="v-game">
<div class="card" data-f="preset"><h2>特感强度</h2><div class="row"><span class="seg" id="seg-preset"><button onclick="preset('auto')">auto</button><button onclick="preset('te8')">te8</button><button onclick="preset('te12')">te12</button><button onclick="preset('te16')">te16</button></span></div><div class="mu">auto = 按存活人数 4→16 只自动缩放；te8/te12/te16 = 固定数量。切换立即生效并保存，换图、重启都保持。</div></div>
<div class="card"><h2>难度</h2><div class="row"><span class="seg" id="seg-diff"><button data-v="easy" onclick="diff('easy')">简单</button><button data-v="normal" onclick="diff('normal')">普通</button><button data-v="hard" onclick="diff('hard')">高级</button><button data-v="impossible" onclick="diff('impossible')">专家</button></span></div><div class="mu">即时生效，已刷出的 Tank 血量不变。</div></div>
<div class="card" data-f="points"><h2>发放积分</h2><div class="row"><select id="ptarget" style="flex:1;min-width:0" onchange="document.getElementById('pcustom').style.display=this.value==='__custom'?'':'none'"><option value="@all">全体在线玩家</option></select><input id="pcustom" placeholder="玩家名 / #userid" style="width:130px;display:none"><input id="pamount" type="number" value="300" style="width:90px"><button onclick="points()">发放</button></div><div class="mu">通过 Points System 的 sm_givepoints 发放。</div></div>
</section>

<section class="view" id="v-maps">
<div class="card"><h2>切换地图</h2><div class="row"><select id="map" style="flex:1;min-width:0"></select><button onclick="changemap()">切换</button></div><div class="mu">官方 14 个战役 + 已安装的自定义战役。切换会丢失当前进度。</div></div>
<div class="card"><h2>自定义战役<span class="sp"></span><button class="g sm" onclick="loadAddons()">刷新</button></h2>
<div class="row" data-f="workshop"><span class="lbl">工坊</span><input id="wsid" placeholder="创意工坊 ID 或链接" style="flex:1;min-width:0"><button onclick="workshop()">下载安装</button></div>
<div class="row"><span class="lbl">上传</span><input type="file" id="vpkfile" accept=".vpk" style="flex:1;min-width:0;padding:6px"><button onclick="upload()">上传</button></div>
<div id="upmsg" class="mu"></div><div id="addons" style="margin-top:6px"></div>
<div class="mu" style="margin-top:8px">装完自动热加载，不用重启。玩家客户端也要订阅同一个创意工坊物品，否则进不了自定义战役。</div></div>
</section>

<section class="view" id="v-console">
<div class="card"><h2>RCON 控制台</h2><div class="row"><input id="cmd" placeholder="status · sm plugins list · sm_cvar z_difficulty · sm_wl_list …" style="flex:1" onkeydown="if(event.key==='Enter')rcon();if(event.key==='ArrowUp'&&hist.length){this.value=hist[hist.length-1]}"><button onclick="rcon()">发送</button></div><pre id="rout" style="max-height:60vh">(输出显示在这里)</pre>
<div class="mu" style="margin-top:8px">隐藏 cvar（z_common_limit、nb_update_frequency、sv_airaccelerate 等）要写 <code>sm_cvar 名字 [值]</code>。</div></div>
</section>

<section class="view" id="v-logs">
<div class="card"><h2>日志<span class="sp"></span><span class="tabs"><button class="on" onclick="logs('console',this)">控制台</button><button onclick="logs('errors',this)">插件报错</button><button onclick="logs('perf',this)">采样</button></span><button class="g sm" onclick="logs(curlog)">刷新</button></h2><pre id="logs" style="max-height:70vh"></pre></div>
</section>

<section class="view" id="v-server">
<div class="card" data-f="lgsm"><h2>服务器控制<span class="sp"></span><span id="actmsg" class="mu"></span></h2><div class="row"><button onclick="act('restart')">重启</button><button class="g" onclick="act('start')">启动</button><button class="d" onclick="act('stop')">停止</button><button class="g" onclick="act('monitor')">巡检</button></div><div class="mu">重启约 1 分钟；有玩家在线时会断开所有人。</div></div>
<div class="card"><h2>系统</h2><div id="sysinfo" class="mu">-</div></div>
<div class="card" id="conninfo" style="display:none"><h2>连接信息</h2><div class="mu">游戏：<code id="connhost"></code></div></div>
</section>
</div></div>
<div id="toast"></div>
<script>
const MAPS=%MAPS%;let curlog='console',hist=[];
const TITLES={overview:'概览',players:'玩家 / 白名单',game:'游戏设置',maps:'地图 / 战役',console:'控制台',logs:'日志 / 性能',server:'服务器'};
function nav(v){document.querySelectorAll('.view').forEach(e=>e.classList.toggle('on',e.id==='v-'+v));document.querySelectorAll('#side nav button').forEach(b=>b.classList.toggle('on',b.dataset.v===v));set('vtitle',TITLES[v]||v);try{localStorage.setItem('l4d2view',v)}catch(e){}if(v==='logs')logs(curlog);if(v==='overview')perf();if(v==='maps')loadAddons()}

function toast(t,bad){const e=document.getElementById('toast');e.textContent=t;e.style.borderColor=bad?'var(--bad)':'var(--bd)';e.classList.add('show');clearTimeout(e._t);e._t=setTimeout(()=>e.classList.remove('show'),2800)}
async function api(p,o){const r=await fetch(p,o?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(o)}:{});if(r.status===401){show(false);throw new Error('未登录')}const j=await r.json();if(j.error)throw new Error(j.error);return j}
function short(t){t=String(t||'').replace(/\s+/g,' ').trim();return t.length>140?t.slice(0,140)+'…':t}
async function run(p,o,okmsg){try{const j=await api(p,o);toast(okmsg||short(j.out)||'完成');return j}catch(e){toast(e.message,true);throw e}}
function show(on){document.getElementById('login').style.display=on?'none':'';document.getElementById('app').style.display=on?'':'none'}
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
async function login(){try{await api('/api/login',{password:document.getElementById('pw').value});try{await api('/api/status')}catch(e){document.getElementById('lmsg').textContent='密码正确，但浏览器没有保存登录状态：请清除本站 cookie 后重试';return}show(true);boot()}catch(e){document.getElementById('lmsg').textContent=e.message}}
async function logout(){await api('/api/logout',{});show(false)}
function set(id,v){document.getElementById(id).textContent=v}
async function status(){try{const s=await api('/api/status');const sys=s.sys||{};const pill=document.getElementById('pill');pill.className='pill '+(s.online?'on':'off');pill.lastElementChild.textContent=s.online?'在线':(s.srcds?'进程在，游戏未响应':'离线');
set('t-players',s.online?`${s.players} / ${s.max}`:'-');set('t-bots',s.online?`bot ${s.bots}`:'');set('t-map',s.online?s.map:'-');set('t-name',s.online?s.name:'');set('t-preset',s.preset||'-');set('t-diff','难度 '+({easy:'简单',normal:'普通',hard:'高级',impossible:'专家'}[s.difficulty]||'-')+' · 白名单'+(s.whitelist===null?'?':s.whitelist?'开':'关'));set('sysinfo',sys.load?`负载 ${sys.load} ｜ 内存 ${sys.mem_used_mb}/${sys.mem_total_mb} MB ｜ 系统已运行 ${sys.uptime_h} h ｜ 游戏进程 ${s.srcds?'运行中':'未运行'}`:'-');
document.querySelectorAll('#seg-preset button').forEach(b=>b.classList.toggle('on',b.textContent===s.preset));document.querySelectorAll('#seg-diff button').forEach(b=>b.classList.toggle('on',b.dataset.v===s.difficulty));
set('t-fps',s.perf?s.perf.fps:'-');set('t-out',s.perf?s.perf.out_kb+' KB/s':'-');set('t-load',sys.load?sys.load.split(' ')[0]:'-');set('t-mem',sys.mem_used_mb?`内存 ${sys.mem_used_mb}/${sys.mem_total_mb} MB · 已运行 ${sys.uptime_h} h`:'');
if(s.whitelist!==undefined){wlOn=s.whitelist;renderSw()}if(s.features){document.querySelectorAll('[data-f]').forEach(e=>e.style.display=s.features[e.dataset.f]?'':'none')}if(s.title){set('brand','🧟 '+s.title);document.title=s.title}if(s.display_host){set('sidehost',s.display_host);set('connhost','connect '+s.display_host);document.getElementById('conninfo').style.display=''}set('ts',new Date().toLocaleTimeString());set('actmsg',(s.action.running?'正在执行 '+s.action.running+'… ':'')+(s.action.last||''))}catch(e){}}
async function act(n){const names={restart:'重启',start:'启动',stop:'停止',monitor:'巡检'};if(n!=='monitor'&&!confirm('确定'+names[n]+'服务器？'))return;await run('/api/action',{name:n},'已开始'+names[n]);setTimeout(status,2000);setTimeout(status,20000)}
async function preset(n){await run('/api/preset',{name:n},'特感预设已切换为 '+n);status()}
async function diff(l){await run('/api/difficulty',{level:l},'难度已设为 '+({easy:'简单',normal:'普通',hard:'高级',impossible:'专家'}[l])+'，即时生效');status()}
async function changemap(){const m=document.getElementById('map').value;if(!confirm('切换到 '+m+'？当前进度会丢失'))return;await run('/api/map',{map:m},'切换中…');setTimeout(status,8000)}
function renderTargets(pl){const sel=document.getElementById('ptarget'),cur=sel.value;sel.innerHTML='<option value="@all">全体在线玩家'+(pl.length?'（'+pl.length+' 人）':'')+'</option>'+pl.map(p=>`<option value="#${p.userid}">${esc(p.name)}</option>`).join('')+'<option value="__custom">手动输入…</option>';if([...sel.options].some(o=>o.value===cur))sel.value=cur}
async function points(){const sel=document.getElementById('ptarget');let t=sel.value,label=sel.options[sel.selectedIndex].textContent;if(t==='__custom'){t=document.getElementById('pcustom').value.trim();label=t;if(!t){toast('请输入玩家名或 #userid',true);return}}const a=+document.getElementById('pamount').value;if(!a){toast('请输入分数',true);return}await run('/api/points',{target:t,amount:a},`已给 ${label} 发 ${a} 分`)}
let wlOn=null;function renderSw(){const sw=document.getElementById('sw-wl');sw.className='sw'+(wlOn===null?' dis':wlOn?' on':'');set('wl-state',wlOn===null?'未知（服务器离线）':wlOn?'已开启：仅名单内可进':'已关闭：所有人可进')}
async function wlToggle(){if(wlOn===null)return;const v=!wlOn;if(!v&&!confirm('关闭白名单后任何人都能进服，确定？'))return;await run('/api/whitelist_enable',{enable:v},v?'白名单已开启':'白名单已关闭，现在所有人可进');wlOn=v;renderSw()}
async function loadPlayers(){try{const d=await api('/api/players');renderTargets(d.players);const mini=document.getElementById('players-mini');mini.innerHTML='<tr><th>名字</th><th>在线</th><th>延迟</th></tr>'+(d.players.length?d.players.map(p=>`<tr><td>${esc(p.name)}</td><td>${esc(p.time)}</td><td>${esc(p.ping)} ms</td></tr>`).join(''):'<tr><td colspan=3 class="mu">当前没有玩家</td></tr>');const t=document.getElementById('players');t.innerHTML='<tr><th>名字</th><th>SteamID</th><th>在线</th><th>延迟</th><th></th></tr>'+(d.players.length?d.players.map(p=>`<tr><td><b>${esc(p.name)}</b></td><td><code class="mu">${esc(p.steamid)}</code></td><td>${esc(p.time)}</td><td>${esc(p.ping)} ms</td><td style="white-space:nowrap;text-align:right">
<button class="g sm" onclick="givep('${esc(p.name)}')">发分</button> <button class="g sm" onclick="wladd('${esc(p.steamid)}','${esc(p.name)}')">加白</button> <button class="d sm" onclick="kick(${p.userid},'${esc(p.name)}')">踢</button></td></tr>`).join(''):'<tr><td colspan=5 class="mu">当前没有玩家</td></tr>')}catch(e){}}
async function givep(n){const a=prompt('给 '+n+' 发多少分？','200');if(a)await run('/api/points',{target:n,amount:+a},'已发放')}
async function wladd(id,n){await run('/api/whitelist',{op:'add',steamid:id,note:n},'已加入白名单：'+n);loadWl()}
async function kick(u,n){if(!confirm('踢出 '+n+'？'))return;await run('/api/kick',{userid:u},'已踢出');setTimeout(loadPlayers,1500)}
async function wl(op,id){id=id||document.getElementById('wlid').value.trim();const note=document.getElementById('wlnote').value;if(op==='del'&&!confirm('从白名单删除 '+id+'？'))return;try{const d=await run('/api/whitelist',{op,steamid:id,note});renderWl(d.list);if(op==='add')document.getElementById('wlid').value=''}catch(e){}}
function renderWl(l){set('wlcount',l.length?l.length+' 人':'空 = 对所有人开放');document.getElementById('wllist').innerHTML=l.map(x=>{const [id,...rest]=x.split(/\s+/);const note=rest.join(' ').replace(/^\/\/\s*/,'');return `<div class="wl"><span><code>${esc(id)}</code> <span class="mu">${esc(note)}</span></span><button class="g sm" onclick="wl('del','${esc(id)}')">删除</button></div>`}).join('')}
async function loadWl(){try{renderWl((await api('/api/whitelist')).list)}catch(e){}}
async function rcon(){const i=document.getElementById('cmd'),c=i.value.trim();if(!c)return;hist.push(c);i.value='';try{document.getElementById('rout').textContent='> '+c+'\n'+((await api('/api/rcon',{cmd:c})).out||'(无输出)')}catch(e){document.getElementById('rout').textContent='错误: '+e.message}}
async function logs(k,btn){curlog=k;if(btn){document.querySelectorAll('.tabs button').forEach(b=>b.classList.remove('on'));btn.classList.add('on')}try{const d=await api('/api/logs?'+k);const p=document.getElementById('logs');p.textContent=d.lines.join('\n')||'(空)';p.scrollTop=p.scrollHeight}catch(e){}}
function spark(id,vals,color,min,max){const c=document.getElementById(id),dpr=devicePixelRatio||1;c.width=c.clientWidth*dpr;c.height=56*dpr;const x=c.getContext('2d');x.scale(dpr,dpr);const w=c.clientWidth,h=56;x.clearRect(0,0,w,h);if(!vals.length){x.fillStyle='#8a9bb0';x.font='12px sans-serif';x.fillText('暂无采样（有玩家在线时每 15 秒记录一次）',6,32);return}
const lo=min??Math.min(...vals),hi=max??Math.max(...vals),rng=(hi-lo)||1;x.beginPath();vals.forEach((v,i)=>{const px=i/(vals.length-1||1)*(w-50)+42,py=h-6-(v-lo)/rng*(h-14);i?x.lineTo(px,py):x.moveTo(px,py)});x.strokeStyle=color;x.lineWidth=2;x.stroke();x.fillStyle='#8a9bb0';x.font='11px sans-serif';x.textAlign='right';x.fillText(hi.toFixed(1),38,12);x.fillText(lo.toFixed(1),38,h-3);x.textAlign='left';x.fillStyle=color;x.font='bold 12px sans-serif';const last=vals[vals.length-1];x.fillText(last.toFixed(1),w-44,h-6-(last-lo)/rng*(h-14)+4)}
async function perf(){try{const d=await api('/api/logs?perfjson');spark('c-fps',d.rows.map(r=>r.fps),'#3ddc97',0,32);spark('c-out',d.rows.map(r=>r.out_kb),'#4f8cff',0,null)}catch(e){}}

function fmtJob(j){return j.state==='running'?'⏳ '+j.msg:j.state==='done'?'✅ '+j.msg:'❌ '+j.msg}
async function loadAddons(){try{const d=await api('/api/addons');const el=document.getElementById('addons');const jobs=Object.entries(d.jobs||{}).map(([id,j])=>`<div class="mu">工坊 ${id}: ${esc(fmtJob(j))}</div>`).join('');
el.innerHTML=jobs+(d.addons.length?'<table><tr><th>文件</th><th>地图</th><th>大小</th><th></th></tr>'+d.addons.map(a=>`<tr><td><b>${esc(a.name)}</b>${a.mission?'<div class="mu">'+esc(a.mission)+'</div>':''}</td><td class="mu">${a.maps.length?a.maps.length+' 张：'+esc(a.maps.slice(0,3).join(', '))+(a.maps.length>3?'…':''):'—'}</td><td>${a.size_mb} MB</td><td style="white-space:nowrap;text-align:right">${a.maps.length?`<button class="sm" onclick="gomap('${esc(a.maps[0])}')">切到第一章</button> `:''}${a.protected?'':`<button class="d sm" onclick="delAddon('${esc(a.name)}')">删除</button>`}</td></tr>`).join('')+'</table>':'<div class="mu">还没有自定义战役</div>');
const sel=document.getElementById('map');const cur=sel.value;sel.innerHTML=MAPS.map(m=>`<option value="${m[0]}">${m[1]} · ${m[0]}</option>`).join('')+d.addons.filter(a=>a.maps.length).map(a=>`<optgroup label="${esc(a.name)}">`+a.maps.map(m=>`<option value="${esc(m)}">${esc(m)}</option>`).join('')+'</optgroup>').join('');if([...sel.options].some(o=>o.value===cur))sel.value=cur;
if(Object.values(d.jobs||{}).some(j=>j.state==='running'))setTimeout(loadAddons,5000)}catch(e){}}
async function gomap(m){if(!confirm('切换到 '+m+'？当前进度会丢失'))return;await run('/api/map',{map:m},'切换中…');setTimeout(status,8000)}
async function delAddon(n){if(!confirm('删除 '+n+'？'))return;await run('/api/addons',{op:'delete',name:n},'已删除 '+n);loadAddons()}
async function workshop(){const id=document.getElementById('wsid').value.trim();if(!id)return;await run('/api/addons',{op:'workshop',id},'开始下载，完成后自动安装');document.getElementById('wsid').value='';setTimeout(loadAddons,1500)}
async function upload(){const f=document.getElementById('vpkfile').files[0];if(!f){toast('先选择一个 .vpk 文件',true);return}const m=document.getElementById('upmsg');m.textContent='上传中 '+f.name+' ('+(f.size/1048576).toFixed(1)+' MB)…';
try{const r=await new Promise((res,rej)=>{const x=new XMLHttpRequest();x.open('POST','/api/upload?name='+encodeURIComponent(f.name));x.upload.onprogress=e=>{if(e.lengthComputable)m.textContent='上传中 '+Math.round(e.loaded/e.total*100)+'% · '+f.name};x.onload=()=>res(JSON.parse(x.responseText));x.onerror=()=>rej(new Error('网络错误'));x.send(f)});if(r.error)throw new Error(r.error);m.textContent='已安装 '+r.addon.name+'（'+r.addon.maps.length+' 张地图）';toast('上传完成');loadAddons()}catch(e){m.textContent='失败: '+e.message;toast(e.message,true)}}
function boot(){document.getElementById('map').innerHTML=MAPS.map(m=>`<option value="${m[0]}">${m[1]} · ${m[0]}</option>`).join('');let v='overview';try{v=localStorage.getItem('l4d2view')||v}catch(e){}nav(v);status();loadPlayers();loadWl();loadAddons();logs('console');perf();setInterval(status,10000);setInterval(loadPlayers,30000);setInterval(perf,60000)}
(async()=>{try{await api('/api/status');show(true);boot()}catch(e){show(false)}})();
</script></div></body></html>""".replace('%MAPS%', json.dumps(MAPS, ensure_ascii=False))

if __name__ == '__main__':
    port = int(CONF['port']); bind = CONF['bind']
    srv = ThreadingHTTPServer((bind, port), H)
    if CONF['tls']:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); ctx.load_cert_chain(_abs(CONF['cert']), _abs(CONF['key']))
        srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    print(f'L4D2 panel listening on {bind}:{port} tls={bool(CONF["tls"])} config={CONF_PATH}', flush=True)
    srv.serve_forever()
