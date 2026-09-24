"""Live game state and settings: players, cached flags (preset / whitelist / difficulty / damage factors),
and the RCON-driven actions of the 游戏设置 and 玩家 pages."""
import re, time

from ..errors import ApiError
from ..integrations.rcon import RconClient
from ..integrations.sm_files import persist_cvars
from ..integrations.srcds import parse_status
from ..settings import Paths
from ..store.audit import AuditLog
from .game_modes import GameModes

PRESETS = ('auto', 'te8', 'te12', 'te16')
DIFFICULTIES = ('easy', 'normal', 'hard', 'impossible')
DAMAGE_CVARS = {
    'ff':   ['survivor_friendly_fire_factor_' + d for d in ('easy', 'normal', 'hard', 'expert')],
    'burn': ['survivor_burn_factor_' + d          for d in ('easy', 'normal', 'hard', 'expert')],
}
MAP_NAME = re.compile(r'^[a-z0-9_]+$')


def quote_arg(s: str) -> str:
    """One double-quoted srcds command argument (embedded quotes are dropped: srcds has no escaping)."""
    return '"' + str(s).replace('"', '') + '"'


class GameService:
    def __init__(self, paths: Paths, rcon: RconClient, audit: AuditLog, flags_ttl=15):
        self.paths, self.rcon, self.audit, self.flags_ttl = paths, rcon, audit, flags_ttl
        self.modes = GameModes(rcon, audit, paths.server_cfg)
        # 15 s cache cuts RCON churn and, crucially, keeps last-good values so one flaky RCON call doesn't blank the tiles
        self._flags = {'t': 0, 'preset': '', 'whitelist': None, 'difficulty': '', 'ff': None, 'burn': None}

    def players(self):
        """-> (human rows, summary counts, raw status text)"""
        out = self.rcon.run('status'); rows, summary = parse_status(out); return rows, summary, out

    def invalidate_flags(self):
        self._flags['t'] = 0

    def flags(self, online: bool, features: dict) -> dict:
        g = self._flags
        if online and time.time() - g['t'] >= self.flags_ttl:
            if features.get('preset'):
                try:
                    m = re.search(r'当前: (\w+)', self.rcon.run('sm_preset'))
                    if m: g['preset'] = m.group(1)
                except Exception: pass
            if features.get('whitelist'):
                try:
                    w = re.search(r'"sm_whitelist_enable"[^"]*"(\d)"', self.rcon.run('sm_cvar sm_whitelist_enable'))
                    if w: g['whitelist'] = (w.group(1) == '1')
                except Exception: pass
            try:
                dd = re.search(r'"z_difficulty" = "(\w+)"', self.rcon.run('z_difficulty'))
                if dd: g['difficulty'] = dd.group(1).lower()
            except Exception: pass
            # damage factors: set_damage keeps all four difficulty variants equal, so the expert one is representative
            for key, cv in (('ff', 'survivor_friendly_fire_factor_expert'), ('burn', 'survivor_burn_factor_expert')):
                try:
                    m = re.search(r'"%s" = "([0-9.]+)"' % cv, self.rcon.run(cv))
                    if m: g[key] = float(m.group(1))
                except Exception: pass
            g['t'] = time.time()
        return {k: g[k] for k in ('preset', 'whitelist', 'difficulty', 'ff', 'burn')}

    # ---- actions ----
    def run_command(self, cmd: str, actor: str) -> str:
        cmd = cmd.strip()
        if not cmd: raise ApiError(400, 'empty')
        self.audit.add(actor, 'rcon', cmd)
        return self.rcon.run(cmd)

    def set_preset(self, name: str, actor: str) -> str:
        if name not in PRESETS: raise ApiError(400, 'bad preset')
        out = self.rcon.run('sm_preset ' + name); self.invalidate_flags(); self.audit.add(actor, 'game.preset', name)
        return out

    def set_difficulty(self, level: str, actor: str) -> str:
        if level not in DIFFICULTIES: raise ApiError(400, 'bad difficulty')
        cap = level.capitalize()
        try: self.rcon.run('l4d2_force_difficulty ' + cap)   # plugin locks z_difficulty to this; survives map/campaign resets
        except Exception: pass
        out = self.rcon.run('z_difficulty ' + cap); self.invalidate_flags(); self.audit.add(actor, 'game.difficulty', level)
        return out

    def set_damage(self, ff, burn, actor: str):
        """-> (rcon output, persisted to server.cfg?)"""
        pairs = []
        for key, val in (('ff', ff), ('burn', burn)):
            if val is None: continue
            v = max(0.0, min(1.0, float(val)))
            pairs += [(cv, f'{v:g}') for cv in DAMAGE_CVARS[key]]
        if not pairs: raise ApiError(400, 'nothing to set')
        out = '\n'.join(self.rcon.run(f'sm_cvar {n} {v}') for n, v in pairs)
        persisted = True
        try: persist_cvars(self.paths.server_cfg, pairs)
        except Exception as e: persisted = False; out += f'\n(server.cfg not updated: {e})'
        self.invalidate_flags(); self.audit.add(actor, 'game.damage', ' '.join(f'{k}={v}' for k, v in (('ff', ff), ('burn', burn)) if v is not None))
        return out, persisted

    def change_map(self, m: str, actor: str) -> str:
        if not MAP_NAME.match(m): raise ApiError(400, 'bad map name')
        self.audit.add(actor, 'game.map', m)
        return self.rcon.run('changelevel ' + m)

    def give_points(self, target, amount: int, actor: str) -> str:
        tgt = str(target or '@all').strip() or '@all'
        tgt = tgt if tgt.startswith('@') or tgt.startswith('#') else quote_arg(tgt)
        self.audit.add(actor, 'game.points', f'{tgt} {amount}')
        return self.rcon.run(f'sm_givepoints {tgt} {int(amount)}')

    def kick(self, userid: int, reason: str, actor: str) -> str:
        self.audit.add(actor, 'game.kick', f'#{userid} {reason}')
        return self.rcon.run(f'kickid {int(userid)} {quote_arg(reason)}')
