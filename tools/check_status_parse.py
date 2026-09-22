#!/usr/bin/env python3
"""Regression check for the RCON `status` parser in panel/panel.py (no game server needed).

L4D2 prints one extra number between userid and name on human rows, and bot rows have no
connected/ping/loss columns at all (captured from the live server on 2026-09-19/22):

    # userid name uniqueid connected ping loss state rate adr
    # 26 1 "桐喵Six" STEAM_1:0:xxxx 05:40 99 0 active 30000 1.2.3.4:44563
    #27 "Coach" BOT active

The original regex expected `# 26 "name" ...`, so /api/players was always an empty list and the
A2S-throttled fallback of /api/status reported 0 humans even with a full server.

Part 1 feeds captured replies straight into parse_status().  Part 2 starts the real panel on 127.0.0.1
with a throwaway config against a fake RCON + A2S server, logs in and reads /api/players and
/api/status over HTTP — first with A2S answering, then with A2S silent (the RCON fallback path).

用法: python3 tools/check_status_parse.py   （退出码 0 = 全部通过）
"""
import contextlib, importlib.util, io, json, os, re, socket, struct, subprocess, sys, tempfile, threading, time, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PANEL = os.path.join(ROOT, 'panel', 'panel.py')

# Real reply of a live 2.2.4.3 server (SteamIDs / addresses masked), plus one boundary row:
# a name containing quotes, an hours-long session and a non-"active" state.
STATUS_BUSY = '''hostname: 求生之路2 - 10人合作服
version : 2.2.4.3 10097 secure  (unknown)
udp/ip  : 10.0.0.4:27015 [ public 124.222.200.66:27015 ]
os      : Linux Dedicated
map     : c2m1_highway
players : 2 humans, 5 bots (12 max) (not hibernating) (unreserved)
# userid name uniqueid connected ping loss state rate adr
# 26 1 "桐喵Six" STEAM_1:0:12345678 05:40 99 0 active 30000 1.2.3.4:44563
#27 "Coach" BOT active
#28 "Ellis" BOT active
#29 "Rochelle" BOT active
#45 "Spitter Bot" BOT active
#75 "Tank" BOT active
# 116 1 "a "quoted" name" STEAM_1:1:87654321 1:02:33 45 2 spawning 30000 5.6.7.8:27005
#end'''
STATUS_IDLE = '''hostname: 求生之路2 - 10人合作服
version : 2.2.4.3 10097 secure  (unknown)
udp/ip  : 10.0.0.4:27015 [ public 124.222.200.66:27015 ]
os      : Linux Dedicated
map     : c2m1_highway
players : 0 humans, 0 bots (12 max) (hibernating) (unreserved)
# userid name uniqueid connected ping loss state rate adr
#end'''
HUMANS = [{'userid': '26', 'name': '桐喵Six', 'steamid': 'STEAM_1:0:12345678', 'time': '05:40', 'ping': '99', 'loss': '0', 'state': 'active'},
          {'userid': '116', 'name': 'a "quoted" name', 'steamid': 'STEAM_1:1:87654321', 'time': '1:02:33', 'ping': '45', 'loss': '2', 'state': 'spawning'}]
A2S = {'name': '求生之路2 - 10人合作服', 'map': 'c2m1_highway', 'players': 2, 'max': 12, 'bots': 5}

failures = []
def check(name, fn):
    """fn() returns (ok, detail); an exception counts as a failure (e.g. parse_status missing)."""
    try: ok, detail = fn()
    except Exception as e: ok, detail = False, f'{type(e).__name__}: {e}'
    print(('PASS  ' if ok else 'FAIL  ') + name + ('' if ok else f'\n      -> {detail}'))
    if not ok: failures.append(name)

def load_panel(tmp):
    conf = os.path.join(tmp, 'panel.json')
    with open(conf, 'w', encoding='utf-8') as f:
        json.dump({'password': 'check-only', 'db': os.path.join(tmp, 'panel.db')}, f)
    os.environ['L4D2PANEL_CONFIG'] = conf
    spec = importlib.util.spec_from_file_location('panel_under_test', PANEL); mod = importlib.util.module_from_spec(spec)
    with contextlib.redirect_stdout(io.StringIO()):      # hides the "[panel] seeded owner account" line
        spec.loader.exec_module(mod)
    return mod

# ---- part 1: parser on captured text ----
def part1(mod):
    parse = lambda text: mod.parse_status(text)          # missing function -> AttributeError -> reported as FAIL
    check('busy server: both humans parsed with userid/name/steamid/time/ping/loss/state',
          lambda: (parse(STATUS_BUSY)[0] == HUMANS, parse(STATUS_BUSY)[0]))
    check('busy server: bot rows, the column header and #end are not players',
          lambda: (all(r['steamid'].startswith('STEAM_') for r in parse(STATUS_BUSY)[0]) and len(parse(STATUS_BUSY)[0]) == 2, parse(STATUS_BUSY)[0]))
    check('busy server: summary counts come from the "players :" line',
          lambda: (parse(STATUS_BUSY)[1] == {'humans': 2, 'bots': 5, 'max': 12, 'map': 'c2m1_highway'}, parse(STATUS_BUSY)[1]))
    check('hibernating server: no rows, counts 0/0 of 12',
          lambda: (parse(STATUS_IDLE) == ([], {'humans': 0, 'bots': 0, 'max': 12, 'map': 'c2m1_highway'}), parse(STATUS_IDLE)))
    trunc = '\n'.join(STATUS_BUSY.splitlines()[6:])      # reply cut before the header lines
    check('reply without header lines: humans counted from the rows, unknown bots/max are 0',
          lambda: (parse(trunc) == (HUMANS, {'humans': 2, 'bots': 0, 'max': 0, 'map': ''}), parse(trunc)[1]))

# ---- part 2: the real panel over HTTP against a fake game server ----
def pkt(i, t, body): d = struct.pack('<ii', i, t) + body + b'\x00\x00'; return struct.pack('<i', len(d)) + d
def read_pkt(s):
    raw = b''
    while len(raw) < 4:
        c = s.recv(4 - len(raw))
        if not c: return None
        raw += c
    n = struct.unpack('<i', raw)[0]; d = b''
    while len(d) < n: d += s.recv(n - len(d))
    return struct.unpack('<ii', d[:8]) + (d[8:-2].decode(),)

class FakeGame:
    """RCON (TCP) + A2S_INFO (UDP) on one port, the way srcds does it; `status` answers with STATUS_BUSY."""
    def __init__(self):
        for _ in range(20):
            t = socket.socket(); t.bind(('127.0.0.1', 0)); port = t.getsockname()[1]
            u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try: u.bind(('127.0.0.1', port)); break
            except OSError: t.close(); u.close()
        self.port, self.tcp, self.udp, self.a2s_on, self.commands = port, t, u, True, []
        t.listen(5); threading.Thread(target=self.rcon, daemon=True).start(); threading.Thread(target=self.a2s, daemon=True).start()
    def rcon(self):
        while True:
            c, _ = self.tcp.accept(); threading.Thread(target=self.conn, args=(c,), daemon=True).start()
    def conn(self, c):
        with c:
            while True:
                p = read_pkt(c)
                if not p: return
                i, t, body = p
                if t == 3: c.sendall(pkt(i, 0, b'') + pkt(i, 2, b''))          # empty RESPONSE_VALUE, then AUTH_RESPONSE
                else:
                    self.commands.append(body)
                    c.sendall(pkt(i, 0, STATUS_BUSY.encode() if body == 'status' else b''))
    def a2s(self):
        info = (b'\xFF\xFF\xFF\xFFI\x11' + A2S['name'].encode() + b'\x00' + A2S['map'].encode() + b'\x00left4dead2\x00Left 4 Dead 2\x00'
                + struct.pack('<H', 550) + bytes([A2S['players'], A2S['max'], A2S['bots']]) + b'dl\x00\x01')
        while True:
            d, addr = self.udp.recvfrom(4096)
            if self.a2s_on and d.startswith(b'\xFF\xFF\xFF\xFFT'): self.udp.sendto(info, addr)

def free_port():
    with socket.socket() as s: s.bind(('127.0.0.1', 0)); return s.getsockname()[1]

def part2(tmp):
    game = FakeGame(); port = free_port(); conf = os.path.join(tmp, 'panel-http.json')
    with open(conf, 'w', encoding='utf-8') as f:
        json.dump({'password': 'check-only', 'port': port, 'bind': '127.0.0.1', 'db': os.path.join(tmp, 'panel-http.db'),
                   'rcon_host': '127.0.0.1', 'rcon_port': game.port, 'rcon_password': 'fake',
                   'game_dir': os.path.join(tmp, 'game'), 'lgsm_script': '', 'console_log': '', 'perf_csv': ''}, f)
    proc = subprocess.Popen([sys.executable, PANEL], env=dict(os.environ, L4D2PANEL_CONFIG=conf), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f'http://127.0.0.1:{port}'
    def call(path, data=None, cookie=''):
        req = urllib.request.Request(base + path, data=json.dumps(data).encode() if data is not None else None, headers={'Cookie': cookie, 'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=30) as r: return r.headers, json.loads(r.read())
    srcds = None
    try:
        for _ in range(100):
            try: socket.create_connection(('127.0.0.1', port), timeout=0.2).close(); break
            except OSError: time.sleep(0.1)
        hdr, _ = call('/api/login', {'username': 'admin', 'password': 'check-only'})
        cookie = 'l4d2panel=' + re.search(r'l4d2panel=([^;]+)', hdr.get('Set-Cookie', '')).group(1)
        _, d = call('/api/players', cookie=cookie)
        check('HTTP /api/players lists the humans of the RCON status reply',
              lambda: (d.get('players') == HUMANS and '#end' in d.get('raw', ''), d))
        check('the panel asked the game for "status" over RCON', lambda: ('status' in game.commands, game.commands))
        _, st = call('/api/status', cookie=cookie)
        check('HTTP /api/status with A2S answering: counts from A2S, not degraded',
              lambda: ({k: st.get(k) for k in ('online', 'players', 'bots', 'max', 'map')} == {'online': True, 'players': 2, 'bots': 5, 'max': 12, 'map': 'c2m1_highway'} and not st.get('degraded'), st))
        # A2S goes silent (rate-limited) while the process is up -> the handler must fall back to RCON status
        game.a2s_on = False
        srcds = subprocess.Popen(['bash', '-c', 'exec -a srcds_linux sleep 120'])   # makes `pgrep -f srcds_linux` succeed off the game host
        _, st = call('/api/status', cookie=cookie)
        check('HTTP /api/status with A2S silent: degraded, counts from the RCON status summary',
              lambda: ({k: st.get(k) for k in ('online', 'degraded', 'players', 'bots', 'max', 'map')} == {'online': True, 'degraded': True, 'players': 2, 'bots': 5, 'max': 12, 'map': 'c2m1_highway'}, st))
    finally:
        proc.terminate(); proc.wait(timeout=10)
        if srcds: srcds.terminate(); srcds.wait(timeout=10)

def main():
    with tempfile.TemporaryDirectory() as tmp:
        part1(load_panel(tmp))
        part2(tmp)
    if failures:
        print(f'{len(failures)} check(s) FAILED'); return 1
    print('all checks passed'); return 0

if __name__ == '__main__':
    sys.exit(main())
