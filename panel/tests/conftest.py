"""Fixtures for the black-box parity suite: a temporary game directory, a fake L4D2 server, a fake Steam,
and the real panel started as a subprocess (`python3 <PANEL_ENTRY> --config <tmp>/panel.json`) so the same
suite runs unchanged against the legacy single-file panel and the packaged one.

PANEL_ENTRY (env) defaults to panel/panel.py. The entry file is copied into the temp dir so anything the
panel keeps beside itself (downloads/, workshop_tmp/, panel.db by default) lands there and not in the repo.
"""
import json, os, shutil, socket, sqlite3, subprocess, sys, time
from pathlib import Path

import httpx, pytest

from tests.fakes.game import FakeGame
from tests.fakes.steam import FakeSteam
from tests.fakes.vpk import build_vpk

ROOT = Path(__file__).resolve().parents[1]
PANEL_ENTRY = Path(os.environ.get('PANEL_ENTRY') or ROOT / 'panel.py').resolve()
RCON_PASSWORD = 'fakerc0n'
OWNER_USER, OWNER_PW = 'admin', 'owner-pass'
PROTECTED_PLUGINS = ['sourcemod', 'basecommands', 'basetriggers', 'basechat', 'admin-flatfile', 'adminmenu', 'sm_whitelist', 'sipreset', 'ps_mapreset', 'l4d2_points_system']
SMX_MAGIC = b'FFPS'
CONSOLE_LINES = ['L 09/22/2026 - 12:00:00: Log file started', '\x1b[32mMap loaded\x1b[0m c2m1_highway', 'Client "桐喵Six" connected']
PERF_ROWS = ['time,humans,cpu%,in_bytes,out_bytes,fps,players', '12:00:00,1,20.5,500,8192,29.9,1', '12:00:15,2,30.0,900,10240,30.1,2', '12:00:30,2,35.1,1000,12595,30.0,2']
ERROR_LINES = ['L 09/22/2026 - 11:00:00: SourceMod error session started', 'L 09/22/2026 - 11:00:01: [SM] Exception reported: boom']
LGSM_SCRIPT = '#!/bin/bash\n# fake LinuxGSM instance script: records the action, prints one status line like the real one\necho "$1" >> "$(dirname "$0")/lgsm.log"\necho "[  OK  ] Fake LinuxGSM: $1 done"\n'


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0)); return s.getsockname()[1]


class GameDir:
    """A throwaway <game_dir> tree with the files the panel reads and writes."""
    def __init__(self, root: Path):
        self.root = root
        self.cfg = root / 'cfg' / 'server.cfg'
        self.addons = root / 'addons'
        self.sm = self.addons / 'sourcemod'
        self.plugins = self.sm / 'plugins'; self.disabled = self.plugins / 'disabled'
        self.configs = self.sm / 'configs'; self.whitelist = self.configs / 'whitelist.txt'; self.admins = self.configs / 'admins_simple.ini'
        self.logs = self.sm / 'logs'
        for d in (self.cfg.parent, self.addons, self.plugins, self.disabled, self.configs, self.logs): d.mkdir(parents=True, exist_ok=True)
        self.cfg.write_text('hostname "test server"\nrcon_password "%s"\nsm_cvar survivor_friendly_fire_factor_expert 0.1\nsurvivor_burn_factor_easy 0.5\nsv_gametypes "coop,versus"\n' % RCON_PASSWORD, encoding='latin-1')
        (self.addons / 'admin_system.vpk').write_bytes(build_vpk(['scripts/admin.txt']))
        (self.addons / 'custom_campaign.vpk').write_bytes(build_vpk(['maps/cc2_end.bsp', 'maps/cc1_start.bsp', 'missions/customcamp.txt', 'materials/x.vtf']))
        (self.plugins / 'myplugin.smx').write_bytes(SMX_MAGIC + b'\0' * 64)
        (self.plugins / 'sm_whitelist.smx').write_bytes(SMX_MAGIC + b'\0' * 64)
        (self.disabled / 'oldplugin.smx').write_bytes(SMX_MAGIC + b'\0' * 64)
        self.whitelist.write_text('STEAM_1:0:111 // alice\n// a comment line\n\nSTEAM_1:1:222\n', encoding='utf-8')
        self.admins.write_text('// SourceMod admins\n"STEAM_1:0:999" "99:z" // existing admin\n', encoding='utf-8')
        (self.logs / 'errors_20260922.log').write_text('\n'.join(ERROR_LINES) + '\n', encoding='utf-8')

    def addon_names(self):
        return sorted(p.name for p in self.addons.iterdir() if p.name.lower().endswith('.vpk'))


@pytest.fixture
def game_dir(tmp_path):
    return GameDir(tmp_path / 'game')


@pytest.fixture
def fake_game(request, game_dir):
    marker = request.node.get_closest_marker('game')
    kw = dict(password=RCON_PASSWORD, whitelist_path=game_dir.whitelist); kw.update(marker.kwargs if marker else {})
    g = FakeGame(**kw)
    yield g
    g.stop()


@pytest.fixture
def fake_steam():
    s = FakeSteam()
    yield s
    s.stop()


class Panel:
    def __init__(self, tmp: Path, game_dir: GameDir, game: FakeGame, steam: FakeSteam, overrides: dict):
        self.tmp, self.game_dir, self.game, self.steam = tmp, game_dir, game, steam
        self.dir = tmp / 'panel'; self.dir.mkdir(parents=True)
        self.port = free_port(); self.base_url = f'http://127.0.0.1:{self.port}'
        (tmp / 'console.log').write_text('\n'.join(CONSOLE_LINES) + '\n', encoding='utf-8')
        (tmp / 'perf.csv').write_text('\n'.join(PERF_ROWS) + '\n', encoding='utf-8')
        self.lgsm = tmp / 'lgsm'; self.lgsm.write_text(LGSM_SCRIPT); self.lgsm.chmod(0o755)
        self.config = {
            'password': OWNER_PW, 'bootstrap_user': OWNER_USER, 'port': self.port, 'bind': '127.0.0.1', 'tls': False, 'session_days': 7,
            'db': str(self.dir / 'panel.db'),
            'rcon_host': '127.0.0.1', 'rcon_port': game.port, 'rcon_password': '',        # '' -> the panel must read it from server.cfg
            'game_dir': str(game_dir.root), 'lgsm_script': str(self.lgsm), 'console_log': str(tmp / 'console.log'), 'perf_csv': str(tmp / 'perf.csv'),
            'depotdownloader': '', 'steam_api_base': steam.base, 'steam_community_base': steam.base, 'workshop_connections': 3, 'workshop_retries': 3,
            'panel_title': 'Test Panel', 'display_host': 'test.example', 'max_upload_mb': 1,
            'protected_addons': ['admin_system.vpk'], 'protected_plugins': PROTECTED_PLUGINS,
        }
        self.config.update(overrides)
        self.conf_path = self.dir / 'panel.json'; self.conf_path.write_text(json.dumps(self.config, ensure_ascii=False, indent=1), encoding='utf-8')
        self.entry = self.dir / 'panel.py'; shutil.copy(PANEL_ENTRY, self.entry)
        self.log_path = self.dir / 'panel.log'; self.proc = None

    def start(self):
        env = dict(os.environ, L4D2PANEL_CONFIG=str(self.conf_path), PYTHONUNBUFFERED='1', PYTHONPATH=str(PANEL_ENTRY.parent))
        self.log = open(self.log_path, 'w')
        self.proc = subprocess.Popen([sys.executable, str(self.entry), '--config', str(self.conf_path)], cwd=str(self.dir), env=env, stdout=self.log, stderr=subprocess.STDOUT)
        for _ in range(200):
            if self.proc.poll() is not None: raise RuntimeError('panel exited during startup:\n' + self.log_path.read_text())
            try: socket.create_connection(('127.0.0.1', self.port), timeout=0.2).close(); return self
            except OSError: time.sleep(0.05)
        raise RuntimeError('panel did not start listening:\n' + self.log_path.read_text())

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try: self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired: self.proc.kill(); self.proc.wait()
        self.log.close()

    def output(self):
        return self.log_path.read_text(errors='replace')

    def client(self):
        return httpx.Client(base_url=self.base_url, timeout=60)

    def login(self, user=OWNER_USER, password=OWNER_PW, client=None):
        c = client or self.client()
        r = c.post('/api/login', json={'username': user, 'password': password})
        assert r.status_code == 200, r.text
        return c

    def audit(self):
        with sqlite3.connect(f'file:{self.config["db"]}?mode=ro', uri=True) as c:
            c.row_factory = sqlite3.Row
            return [dict(r) for r in c.execute('SELECT ts, who, action, detail FROM audit ORDER BY id')]

    def audit_actions(self):
        return [(r['who'], r['action']) for r in self.audit()]

    def wait_for(self, fn, timeout=30, every=0.2):
        """Poll fn() until it returns a truthy value (returned) or the timeout expires (AssertionError)."""
        end = time.time() + timeout
        while True:
            v = fn()
            if v: return v
            if time.time() > end: raise AssertionError('timed out waiting; panel output:\n' + self.output())
            time.sleep(every)


@pytest.fixture
def panel_factory(tmp_path, game_dir, fake_game, fake_steam):
    started = []
    def make(overrides=None, game=None):
        p = Panel(tmp_path / f'p{len(started)}', game_dir, game or fake_game, fake_steam, overrides or {})
        started.append(p); return p.start()
    yield make
    for p in started:
        p.stop()


@pytest.fixture
def panel(request, panel_factory):
    marker = request.node.get_closest_marker('panel')
    return panel_factory(marker.kwargs if marker else {})


@pytest.fixture
def api(panel):
    """An httpx client logged in as the owner account."""
    c = panel.login()
    yield c
    c.close()
