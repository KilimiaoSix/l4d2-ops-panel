"""Which optional parts are available: detected from the installed SourceMod plugins + local tools, cached 120 s
while the game is online (an offline answer is not cached, so the tiles come back as soon as the game does)."""
import os, time

from ..integrations.lgsm import Lgsm
from ..integrations.rcon import RconClient
from ..settings import Settings


class FeatureDetector:
    def __init__(self, settings: Settings, rcon: RconClient, lgsm: Lgsm, ttl=120, server=None):
        self.settings, self.rcon, self.lgsm, self.ttl = settings, rcon, lgsm, ttl
        self.server = server
        self.t, self.v = 0, {}
        self.backend = settings.server_backend

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
                names = self.rcon.run('sm plugins list').lower()
                f['sourcemod'] = 'listing' in names or 'plugins' in names
                f['whitelist'] = 'private whitelist' in names; f['preset'] = 'si preset' in names; f['points'] = 'points system' in names
            except Exception:
                pass
            self.t, self.v = now, f
        return f
