"""The /api/status document: liveness (A2S, with the RCON fallback when A2S is throttled), host load, the
running LinuxGSM action, features, the perf sample and the cached game flags."""
from ..integrations.a2s import A2SClient
from ..integrations.srcds import srcds_running
from ..settings import Settings
from .features import FeatureDetector
from .game import GameService
from .monitoring import Monitoring
from .server_control import ServerControl


class StatusService:
    def __init__(self, settings: Settings, a2s: A2SClient, game: GameService, features: FeatureDetector, monitoring: Monitoring, server: ServerControl, process_check=srcds_running):
        self.settings, self.a2s, self.game, self.features, self.monitoring, self.server, self.process_check = settings, a2s, game, features, monitoring, server, process_check

    def build(self, account: dict) -> dict:
        st = self.a2s.query()
        if self.settings.server_backend == 'docker':
            st['backend'] = 'docker'
            try: st['srcds'] = self.server.running()
            except Exception as exc:
                st['srcds'] = False
                st['server_error'] = str(exc)
        else:
            st['srcds'] = self.process_check()
        if not st['online'] and st['srcds']:   # (2026-09-19) A2S throttled but the process is up: confirm via RCON instead of reporting "not responding"
            try:
                _, sm, _ = self.game.players(); cache = self.a2s.cache
                st.update(online=True, degraded=True, name=cache.get('name', self.settings.panel_title), map=(cache.get('map') or sm['map'] or '?'),
                          players=sm['humans'], bots=sm['bots'], max=(cache.get('max') or sm['max'] or 8))
            except Exception: pass
        st['sys'] = self.monitoring.sysinfo(); st['action'] = self.server.state
        st['account'] = {'user': account['username'], 'role': account['role']}
        st['features'] = fe = self.features.get(st['online']); st['title'] = self.settings.panel_title; st['display_host'] = self.settings.display_host
        st['perf'] = self.monitoring.latest_perf()
        st.update(self.game.flags(st['online'], fe))
        return st
