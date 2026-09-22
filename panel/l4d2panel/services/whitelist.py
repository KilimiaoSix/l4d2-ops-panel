"""Private Whitelist plugin: the list lives in whitelist.txt (maintained by the plugin), the panel drives it
over RCON and re-reads the file."""
from ..errors import ApiError
from ..integrations.rcon import RconClient
from ..integrations.sm_files import read_whitelist
from ..integrations.steam import SteamClient
from ..integrations.steamid import parse_steamid
from ..settings import Paths
from ..store.audit import AuditLog
from .game import GameService, quote_arg


class WhitelistService:
    def __init__(self, paths: Paths, rcon: RconClient, steam: SteamClient, game: GameService, audit: AuditLog):
        self.paths, self.rcon, self.steam, self.game, self.audit = paths, rcon, steam, game, audit

    def parse(self, raw) -> str:
        try: return parse_steamid(raw, self.steam.resolve_vanity)
        except ValueError as e: raise ApiError(400, str(e))

    def list(self):
        return read_whitelist(self.paths.whitelist)

    def add(self, raw, note: str, actor: str) -> str:
        sid = self.parse(raw)
        if not sid: raise ApiError(400, '无效 SteamID')
        out = self.rcon.run(f'sm_wl_addid {sid} {quote_arg(note)}'); self.audit.add(actor, 'whitelist.add', f'{sid} {note}')
        return out

    def remove(self, raw, actor: str) -> str:
        sid = self.parse(raw)
        if not sid: raise ApiError(400, '无效 SteamID')
        out = self.rcon.run(f'sm_wl_del {sid}'); self.audit.add(actor, 'whitelist.del', sid)
        return out

    def enable(self, on: bool, actor: str) -> str:
        out = self.rcon.run(f'sm_cvar sm_whitelist_enable {1 if on else 0}'); self.game.invalidate_flags()
        self.audit.add(actor, 'whitelist.enable', '1' if on else '0')
        return out
