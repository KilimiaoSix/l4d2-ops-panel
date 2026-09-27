"""Which optional parts are available: detected from the installed SourceMod plugins + local tools, cached 120 s
while the game is online (an offline answer is not cached, so the tiles come back as soon as the game does)."""
import os, re, time

from ..integrations.lgsm import Lgsm
from ..integrations.rcon import RconClient
from ..settings import Settings


def active_plugin_names(raw):
    return '\n'.join(line for line in raw.lower().splitlines() if re.match(r'^\s*\d+\s+"', line))


class FeatureDetector:
    def __init__(self, settings: Settings, rcon: RconClient, lgsm: Lgsm, ttl=120, server=None, paths=None):
        self.settings, self.rcon, self.lgsm, self.ttl = settings, rcon, lgsm, ttl
        self.server = server
        self.paths = paths
        self.t, self.v = 0, {}
        self.backend = settings.server_backend

    def invalidate(self):
        self.t, self.v = 0, {}

    def get(self, online: bool) -> dict:
        now = time.time()
        if self.backend != self.settings.server_backend:
            self.t, self.v, self.backend = 0, {}, self.settings.server_backend
        if now - self.t < self.ttl and self.v: return self.v
        s = self.settings
        f = {'lgsm': self.lgsm.available(),
             'workshop': True,   # Web API + ranged HTTP download; DepotDownloader is only a fallback
             'workshop_search': bool(s.steam_api_key),
             'console_log': bool(s.console_log) and os.path.exists(s.console_log), 'perf': bool(s.perf_csv) and os.path.exists(s.perf_csv),
             'sourcemod': False, 'whitelist': False, 'preset': False, 'points': False}
        if s.server_backend == 'docker':
            available = bool(self.server and self.server.available())
            f.update(lgsm=False, docker=True, server_control=available, console_log=available, perf=available)
        if online:
            try:
                raw = self.rcon.run('sm plugins list').lower()
                f['sourcemod'] = 'listing' in raw
                names = active_plugin_names(raw)
                f['whitelist'] = 'private whitelist' in names; f['points'] = 'points system' in names
                data_ready = self.paths is None or all((self.paths.game / 'addons/sourcemod/data/l4dinfectedbots' / (name + '.cfg')).is_file()
                                                       for name in ('coop', 'te8', 'te12', 'te16'))
                f['preset'] = all(token in names for token in ('si preset', 'infected bots', 'left 4 dhooks')) and data_ready
            except Exception:
                # A transient RCON failure is unknown, never a 120-second negative cache.
                return f
            # During startup RCON can accept commands before SourceMod is ready.
            # An "Unknown command" response is inconclusive, just like a timeout.
            if f['sourcemod']:
                self.t, self.v = now, f
        return f
