"""Native game modes: save the default, set the cvar, then reload a starting map.

An RCON acknowledgement is only a switch request. Callers must read fresh mode
and map values afterwards; server.cfg or a plugin can override the requested mode.
"""
import re
import threading
import time

from ..errors import ApiError, IntegrationError
from ..game_modes import MODES
from ..integrations.convars import read_convar
from ..integrations.game_mode_config import ModeConfig, ModeConfigError
from ..integrations.srcds import parse_status

RELOAD_ERROR = re.compile(r'unknown command|failed|not found|no such|invalid|unable|cannot|couldn.t|can.t|not valid|does not exist|错误|失败|不存在', re.I)


class GameModes:
    def __init__(self, rcon, audit, server_cfg):
        self.rcon, self.audit = rcon, audit
        self.config = ModeConfig(server_cfg)
        self.lock = threading.Lock()
        self.next_switch = 0.0

    def read(self):
        result = {'modes': list(MODES), 'mode': None, 'map': None, 'read_error': None,
                  'saved_mode': None, 'config_error': None}
        if not self.lock.acquire(blocking=False):
            result['read_error'] = '正在发送模式切换请求，请稍后刷新'
            return result
        try:
            try:
                result['saved_mode'] = self.config.read()
            except (ModeConfigError, OSError) as exc:
                result['config_error'] = str(exc)
            result['mode'] = read_convar(self.rcon, 'mp_gamemode') or None
            result['map'] = parse_status(self.rcon.run('status'))[1]['map'] or None
            if not result['mode'] or not result['map']:
                result['read_error'] = '服务器未返回完整的模式和地图，请稍后刷新'
        except IntegrationError as exc:
            result['read_error'] = str(exc)
        finally:
            self.lock.release()
        return result

    def _rollback(self, change, previous, requested, actor):
        notes = []
        was_changed = change.changed
        try:
            change.rollback()
            notes.append('默认配置已恢复' if was_changed else '默认配置未改变')
        except (ModeConfigError, OSError) as exc:
            notes.append('配置回滚失败，请检查备份：' + str(exc))
        try:
            current = read_convar(self.rcon, 'mp_gamemode')
            if current == requested and current != previous:
                self.rcon.run('sm_cvar mp_gamemode ' + previous)
                current = read_convar(self.rcon, 'mp_gamemode')
            notes.append('运行模式已恢复' if current == previous else f'运行模式为 {current}，未能恢复为 {previous}')
        except IntegrationError as exc:
            notes.append('运行模式无法确认，请刷新核对：' + str(exc))
        message = '；'.join(notes)
        self.audit.add(actor, 'game.mode.rollback', message)
        return message

    def switch(self, mode, actor):
        target = next((item for item in MODES if item['id'] == mode), None)
        if target is None:
            raise ApiError(400, '不支持的游戏模式')
        if not self.lock.acquire(blocking=False):
            raise ApiError(409, '正在切换模式，请等待完成后再操作')
        try:
            if time.monotonic() < self.next_switch:
                raise ApiError(409, '地图正在重载，请稍后刷新再操作')
            try:
                previous = read_convar(self.rcon, 'mp_gamemode')
            except IntegrationError as exc:
                raise ApiError(502, '无法读取游戏模式，请确认服务器在线且 SourceMod 可用：' + str(exc)) from exc
            if not re.fullmatch(r'[A-Za-z0-9_]+', previous):
                raise ApiError(502, '服务器返回的原模式无效，无法保证失败后恢复；未修改配置')
            try:
                change = self.config.save(mode)
            except (ModeConfigError, OSError) as exc:
                self.audit.add(actor, 'game.mode.result', f'{mode}; config save failed; {exc}')
                raise ApiError(500, '默认模式保存失败，未修改运行模式或重载地图：' + str(exc)) from exc
            self.audit.add(actor, 'game.mode', f'{previous} -> {mode}; map={target["map"]}; requested')
            self.audit.add(actor, 'game.mode.config', f'{mode}; backup={change.backup or "unchanged"}')
            try:
                self.rcon.run('sm_cvar mp_gamemode ' + mode)
                observed = read_convar(self.rcon, 'mp_gamemode')
            except IntegrationError as exc:
                self.audit.add(actor, 'game.mode.result', f'{mode}; mode write unconfirmed; {exc}')
                recovery = self._rollback(change, previous, mode, actor)
                raise ApiError(502, '模式参数结果无法确认，未发送地图重载请求：' + str(exc) + '；' + recovery) from exc
            if observed != mode:
                self.audit.add(actor, 'game.mode.result', f'{mode}; rejected; observed={observed}')
                recovery = self._rollback(change, previous, mode, actor)
                raise ApiError(409, f'服务器返回模式 {observed}，未接受目标模式；未重载地图；' + recovery)
            try:
                if self.config.read() != mode:
                    raise ModeConfigError('默认配置已被其他操作修改')
            except (ModeConfigError, OSError) as exc:
                recovery = self._rollback(change, previous, mode, actor)
                raise ApiError(409, '重载前的配置检查失败：' + str(exc) + '；' + recovery) from exc
            # Once sent, a disconnect may mean the map is already loading. Never
            # retry this write or label the mode active without a subsequent read.
            try:
                output = self.rcon.run('changelevel ' + target['map'])
            except IntegrationError:
                self.audit.add(actor, 'game.mode.result', f'{mode}; reload unconfirmed')
                return {'state': 'uncertain', 'mode': mode, 'map': target['map'],
                        'persisted': True, 'backup': change.backup,
                        'message': '默认模式已保存；重载时连接中断，切换结果待核对，请等待服务器恢复'}
            finally:
                self.next_switch = time.monotonic() + 6
            if RELOAD_ERROR.search(output):
                self.audit.add(actor, 'game.mode.result', f'{mode}; reload rejected; {output}')
                recovery = self._rollback(change, previous, mode, actor)
                raise ApiError(502, '地图重载被拒绝：' + output[:300] + '；' + recovery)
            self.audit.add(actor, 'game.mode.result', f'{mode}; reload requested')
            return {'state': 'switching', 'mode': mode, 'map': target['map'],
                    'persisted': True, 'backup': change.backup,
                    'message': '默认模式已保存，已发送地图重载请求，正在等待服务器状态'}
        finally:
            self.lock.release()
