"""Fake L4D2 dedicated server: Source RCON over TCP and A2S_INFO over UDP on one port, the way srcds does it.

The reply table mimics what the panel parses (SourceMod `sm_cvar` / `sm_preset` / `status` output, captured from
the live 2.2.4.3 server) with just enough state that a write is visible in the next read (`sm_preset te8` ->
`sm_preset` answers `当前: te8`). Every command received is appended to `.commands` so tests can assert exactly
what the panel sent. Whitelist commands edit `whitelist_path` like the real plugin does, because the panel
re-reads that file after each command.

Runnable on its own for local development:  python3 -m tests.fakes.game [--port N] [--whitelist PATH]
"""
import argparse, re, socket, struct, sys, threading, time

# Real reply of the live server (SteamIDs / addresses masked) plus one boundary row: a name containing quotes,
# an hours-long session and a non-"active" state. Humans carry an extra number between userid and name,
# bot rows have no connected/ping/loss columns.
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
A2S_INFO = {'name': '求生之路2 - 10人合作服', 'map': 'c2m1_highway', 'players': 2, 'max': 12, 'bots': 5}
PLUGINS_LIST = '''[SM] Listing 6 plugins:
  01 "Private Whitelist" (1.2.0) by kilimiao
  02 "SI Preset" (1.0.0) by kilimiao
  03 "Points System" (1.7.7) by ...
  04 "Basic Commands" (1.12.0.7210) by AlliedModders LLC
  05 "Admin Menu" (1.12.0.7210) by AlliedModders LLC
  06 "MyPlugin" (0.1) by test'''
DAMAGE_CVARS = {f'survivor_friendly_fire_factor_{d}': '0.1' for d in ('easy', 'normal', 'hard', 'expert')}
DAMAGE_CVARS.update({f'survivor_burn_factor_{d}': '0.5' for d in ('easy', 'normal', 'hard', 'expert')})
PLUGIN_VERBS = {'reload': 'reloaded', 'load': 'loaded', 'unload': 'unloaded'}


def pkt(i, t, body):
    d = struct.pack('<ii', i, t) + body + b'\x00\x00'
    return struct.pack('<i', len(d)) + d


def read_pkt(s):
    raw = b''
    while len(raw) < 4:
        c = s.recv(4 - len(raw))
        if not c: return None
        raw += c
    n = struct.unpack('<i', raw)[0]; d = b''
    while len(d) < n:
        c = s.recv(n - len(d))
        if not c: return None
        d += c
    return struct.unpack('<ii', d[:8]) + (d[8:-2].decode('utf-8', 'replace'),)


class FakeGame:
    def __init__(self, password='fakerc0n', whitelist_path=None, a2s_challenge=False, port=0):
        self.password, self.whitelist_path, self.a2s_challenge = password, str(whitelist_path) if whitelist_path else None, a2s_challenge
        self.a2s_on = True; self.commands = []; self.status_text = STATUS_BUSY; self.auth_failures = 0
        self.state = {'preset': 'te12', 'difficulty': 'Normal', 'cvars': dict(sm_whitelist_enable='1', **DAMAGE_CVARS)}
        self._lock = threading.Lock()
        for _ in range(50):   # srcds answers RCON and A2S on the same port number: find one free for both TCP and UDP
            t = socket.socket(); t.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); t.bind(('127.0.0.1', port)); p = t.getsockname()[1]
            u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try: u.bind(('127.0.0.1', p)); break
            except OSError:
                t.close(); u.close()
                if port: raise
        else:
            raise RuntimeError('no port free for both TCP and UDP')
        self.port, self.tcp, self.udp = p, t, u
        t.listen(16)
        threading.Thread(target=self._accept, daemon=True).start()
        threading.Thread(target=self._a2s, daemon=True).start()

    # ---- RCON ----
    def _accept(self):
        while True:
            try: c, _ = self.tcp.accept()
            except OSError: return
            threading.Thread(target=self._conn, args=(c,), daemon=True).start()

    def _conn(self, c):
        with c:
            authed = False
            while True:
                p = read_pkt(c)
                if not p: return
                i, t, body = p
                if t == 3:                                       # SERVERDATA_AUTH: empty RESPONSE_VALUE, then AUTH_RESPONSE (id -1 = bad password)
                    authed = body == self.password
                    if not authed: self.auth_failures += 1
                    c.sendall(pkt(i, 0, b'') + pkt(i if authed else -1, 2, b''))
                    continue
                if not authed: return
                with self._lock:                                 # the panel ends each command with an empty EXEC as terminator: not a command
                    if body: self.commands.append(body)
                    reply = self.reply(body) if body else ''
                c.sendall(pkt(i, 0, reply.encode()))

    def reply(self, cmd):
        s = self.state; cmd = cmd.strip()
        if cmd == 'status': return self.status_text
        if cmd == 'sm plugins list': return PLUGINS_LIST
        if cmd == 'sm_preset': return f'[SM] 当前: {s["preset"]}（可选 auto / te8 / te12 / te16）'
        m = re.fullmatch(r'sm_preset (\w+)', cmd)
        if m: s['preset'] = m.group(1); return f'[SM] 特感预设已切换为 {m.group(1)}'
        if cmd == 'z_difficulty': return f'"z_difficulty" = "{s["difficulty"]}"\n game replicated\n - Difficulty of the current game (easy, normal, hard, impossible)'
        m = re.fullmatch(r'z_difficulty (\w+)', cmd)
        if m: s['difficulty'] = m.group(1); return ''
        m = re.fullmatch(r'sm_cvar (\S+)', cmd)
        if m: return f'[SM] Value of cvar "{m.group(1)}": "{s["cvars"].get(m.group(1), "0")}"'
        m = re.fullmatch(r'sm_cvar (\S+) (\S+)', cmd)
        if m: s['cvars'][m.group(1)] = m.group(2); return f'[SM] Changed cvar "{m.group(1)}" to "{m.group(2)}".'
        if cmd in s['cvars']: return f'"{cmd}" = "{s["cvars"][cmd]}"\n game replicated\n - factor'
        m = re.fullmatch(r'sm_wl_addid (\S+)(?: "(.*)")?', cmd)
        if m: self._wl_add(m.group(1), m.group(2) or ''); return f'[SM] 已加入白名单: {m.group(1)}'
        m = re.fullmatch(r'sm_wl_del (\S+)', cmd)
        if m: self._wl_del(m.group(1)); return f'[SM] 已从白名单删除: {m.group(1)}'
        if cmd == 'sm_reloadadmins': return '[SM] Admin cache refreshed.'
        m = re.fullmatch(r'sm plugins (reload|load|unload) (\S+)', cmd)
        if m: return f'[SM] Plugin {m.group(2)} {PLUGIN_VERBS[m.group(1)]} successfully.'
        m = re.fullmatch(r'kickid (\d+) "(.*)"', cmd)
        if m: return f'Kicked userid {m.group(1)} ({m.group(2)})'
        if cmd.startswith('changelevel '): return ''
        if cmd.startswith('sm_givepoints '): return '[SM] 积分已发放'
        if cmd in ('update_addon_paths', 'mission_reload'): return ''
        if cmd.startswith('l4d2_force_difficulty'): return 'Unknown command "l4d2_force_difficulty"'
        return 'echo: ' + cmd

    def _wl_lines(self):
        try: return open(self.whitelist_path, encoding='utf-8').read().splitlines()
        except (FileNotFoundError, TypeError): return []

    def _wl_add(self, steamid, note):
        if not self.whitelist_path: return
        with open(self.whitelist_path, 'a', encoding='utf-8') as f: f.write(f'{steamid} // {note}\n' if note else f'{steamid}\n')

    def _wl_del(self, steamid):
        if not self.whitelist_path: return
        keep = [l for l in self._wl_lines() if l.split()[:1] != [steamid]]
        with open(self.whitelist_path, 'w', encoding='utf-8') as f: f.write('\n'.join(keep) + ('\n' if keep else ''))

    # ---- A2S_INFO ----
    def _a2s(self):
        info = (b'\xFF\xFF\xFF\xFFI\x11' + A2S_INFO['name'].encode() + b'\x00' + A2S_INFO['map'].encode() + b'\x00left4dead2\x00Left 4 Dead 2\x00'
                + struct.pack('<H', 550) + bytes([A2S_INFO['players'], A2S_INFO['max'], A2S_INFO['bots']]) + b'dl\x00\x01')
        req = b'\xFF\xFF\xFF\xFFTSource Engine Query\x00'
        while True:
            try: d, addr = self.udp.recvfrom(4096)
            except OSError: return
            if not self.a2s_on or not d.startswith(req): continue
            if self.a2s_challenge and len(d) == len(req): self.udp.sendto(b'\xFF\xFF\xFF\xFFA\x0b\xad\xca\xfe', addr)
            elif not self.a2s_challenge or d[len(req):] == b'\x0b\xad\xca\xfe': self.udp.sendto(info, addr)

    def stop(self):
        for s in (self.tcp, self.udp):
            try: s.close()
            except OSError: pass


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description='fake L4D2 server (RCON + A2S) for running the panel without a game')
    ap.add_argument('--port', type=int, default=0, help='port for both TCP and UDP (default: any free port)')
    ap.add_argument('--password', default='fakerc0n'); ap.add_argument('--whitelist', default=None, help='whitelist.txt the fake edits on sm_wl_* commands')
    a = ap.parse_args()
    g = FakeGame(password=a.password, whitelist_path=a.whitelist, port=a.port)
    print(f'fake L4D2 server on 127.0.0.1:{g.port} (rcon_password {a.password}); Ctrl-C to stop', flush=True)
    try:
        while True: time.sleep(3600)
    except KeyboardInterrupt:
        g.stop(); sys.exit(0)
