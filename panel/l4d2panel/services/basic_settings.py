"""Basic settings: validate, commit files, then verify each requested live value."""
import re

from ..errors import ApiError
from ..integrations.basic_config import BasicConfig
from ..integrations.game_mode_config import ModeConfigError
from ..integrations.hostname_file import canonical_name, parse_name_receipt
from ..integrations.pack_files import PackError, safe_file
from ..integrations.sm_files import read_rcon_password, SERVER_CFG_LOCK

FIELDS = {'server_name', 'ascii_fallback', 'password', 'region', 'coop_players'}
MULTIPLAYER_FILES = ('addons/l4dtoolz.so', 'addons/l4dtoolz.vdf',
    'addons/sourcemod/plugins/l4dmultislots.smx', 'addons/sourcemod/plugins/l4d_CreateSurvivorBot.smx',
    'addons/sourcemod/plugins/left4dhooks.smx')


def safe_ascii(value, *, empty=False, maximum=64):
    return (isinstance(value, str) and (empty or bool(value)) and len(value) <= maximum
            and all(32 <= ord(c) <= 126 and c not in '";\\' for c in value))


class BasicSettingsService:
    def __init__(self, paths, settings, rcon, server, packs, state, audit, invalidate):
        self.paths, self.settings, self.rcon, self.server = paths, settings, rcon, server
        self.packs, self.state, self.audit, self.invalidate = packs, state, audit, invalidate
        self.config = BasicConfig(paths.game, paths.base / 'basic_state')

    def _ready(self):
        return all((self.paths.game / name).is_file() for name in ('steam.inf', 'gameinfo.txt', 'bin/server_srv.so'))

    def _multiplayer(self):
        return ('multiplayer' in self.packs.files.receipt()['packs']
                and all(safe_file(self.paths.game, name).is_file() for name in MULTIPLAYER_FILES))

    def read(self):
        result = {'game_installed': self._ready(), 'config_error': '', 'multiplayer_available': False,
                  'multiplayer_url': '#/plugins', 'engine_capacity': 18, 'fields': None,
                  'restart_required': self.state.get('basic_restart_required') is True,
                  'display_host': self.settings.display_host, 'game_port': self.settings.rcon_port}
        if not result['game_installed']: return result
        try:
            result['fields'] = self.config.read()
            result['multiplayer_available'] = self._multiplayer()
            result['engine_capacity'] = 31 if result['multiplayer_available'] else 18
        except (OSError, ValueError, ModeConfigError) as error: result['config_error'] = str(error)
        return result

    def _validate(self, updates):
        if not updates or set(updates) - FIELDS: raise ApiError(400, '请选择基础设置字段')
        values = dict(updates)
        if 'server_name' in values:
            try: values['server_name'] = canonical_name(values['server_name'])
            except ValueError as error: raise ApiError(400, str(error)) from None
        if 'ascii_fallback' in values and not safe_ascii(values['ascii_fallback'], maximum=96):
            raise ApiError(400, '备用名称应为 1–96 个安全 ASCII 字符')
        if 'password' in values:
            value = values['password']
            if not safe_ascii(value, empty=True): raise ApiError(400, '进服密码最多 64 个安全 ASCII 字符；留空表示清除')
            rcon_password = self.settings.rcon_password or read_rcon_password(self.paths.server_cfg)
            if value and value == rcon_password: raise ApiError(400, '进服密码不能与 RCON 管理密码相同')
        if 'region' in values and (type(values['region']) is not int or values['region'] not in (*range(8), 255)):
            raise ApiError(400, '地区必须为 0–7 或 255')
        if 'coop_players' in values and (type(values['coop_players']) is not int or not 4 <= values['coop_players'] <= 12):
            raise ApiError(400, '合作人数必须是 4–12 的整数')
        return values

    def check_budget(self, players, *, presets=('coop', 'te8', 'te12', 'te16'), capacity=31):
        """Conservative live-client budget, including Tank slots separately."""
        if 'infected' not in self.packs.files.receipt()['packs']: return
        for preset in presets:
            path = safe_file(self.paths.game, f'addons/sourcemod/data/l4dinfectedbots/{preset}.cfg')
            if not path.is_file() or path.stat().st_size > 1024 * 1024: raise ApiError(409, '特感预设缺失或过大，请检查插件包')
            text = re.sub(r'//[^\n]*', '', path.read_text(encoding='utf-8'))
            blocks = dict(re.findall(r'"(default|[0-9]+)"\s*\{([^{}]*)\}', text))
            default = blocks.get('default')
            if default is None: raise ApiError(409, '无法验证自定义特感预设的容量')
            totals = []
            for count in range(1, players + 1):
                data = {}
                for block in (default, blocks.get(str(count), '')):
                    for key, value in re.findall(r'"(max_specials|tank_limit)"\s*"([^"]*)"', block):
                        if not re.fullmatch(r'[0-9]+', value): raise ApiError(409, '特感容量必须是有限的非负整数')
                        data[key] = int(value)
                if set(data) != {'max_specials', 'tank_limit'}: raise ApiError(409, '特感预设缺少容量字段')
                totals.append(data['max_specials'] + data['tank_limit'])
            if players + max(totals) > capacity:
                raise ApiError(409, f'{preset} 特感与 Tank 加上 {players} 名生还者超过 {capacity} 个引擎槽位，请调整预设或安装多人包')

    def guard_preset(self, name):
        # Legacy installations retain their existing preset behavior. Capacity
        # certification applies to the managed fixed-version infected package.
        if 'infected' not in self.packs.files.receipt()['packs']: return
        if not self._ready(): raise ApiError(409, '请先安装游戏')
        multiplayer = self._multiplayer()
        players = self.config.read()['coop_players'] if multiplayer else 4
        self.check_budget(players, presets=('coop' if name == 'auto' else name,), capacity=31 if multiplayer else 18)

    def _cvar(self, name):
        out = self.rcon.run('sm_cvar ' + name)
        match = re.search(r'"' + re.escape(name) + r'"\s*(?:=|:)\s*"([^"]*)"', out)
        if not match:
            out = self.rcon.run(name)
            match = re.search(r'"' + re.escape(name) + r'"\s*(?:=|:)\s*"([^"]*)"', out)
        return match.group(1) if match else None

    def runtime(self, names):
        if not self._ready(): raise ApiError(409, '请先安装游戏')
        if not names or set(names) - (FIELDS - {'ascii_fallback'}): raise ApiError(400, '未知基础设置字段')
        result = {}
        for name in names:
            try:
                if name == 'password':
                    result[name] = {'state': 'unverified', 'message': '游戏隐藏进服密码，面板不回显或猜测运行值'}
                elif name == 'server_name':
                    receipt = parse_name_receipt(self.rcon.run('sm_panel_hostname_status'))
                    result[name] = {'state': 'verified' if receipt and receipt['state'] == 'ok' and receipt['expected'] == receipt['actual'] else 'unverified',
                                    'value': receipt['actual'] if receipt else None}
                elif name == 'region':
                    value = self._cvar('sv_region')
                    result[name] = {'state': 'verified' if value is not None else 'unverified', 'value': value}
                else:
                    values = {key: self._cvar(key) for key in ('sv_setmax', 'sv_maxplayers', 'l4d_multislots_max_survivors',
                              'l4d_multislots_min_survivors', 'sv_force_unreserved', 'sv_allow_lobby_connect_only')}
                    result[name] = {'state': 'verified' if all(v is not None for v in values.values()) else 'unverified', 'values': values}
                    with SERVER_CFG_LOCK:
                        expected = self._expected_count(self.config.read()['coop_players'])
                        if values == expected: self.state.put('basic_restart_required', False)
            except Exception:
                result[name] = {'state': 'error', 'message': '运行值暂时无法读取，请检查游戏状态后重试'}
        return {'fields': result}

    @staticmethod
    def _expected_count(count):
        return {'sv_setmax': '31', 'sv_maxplayers': str(count), 'l4d_multislots_max_survivors': str(count),
                'l4d_multislots_min_survivors': '4', 'sv_force_unreserved': '1', 'sv_allow_lobby_connect_only': '0'}

    def update(self, revision, mode, updates, actor):
        if mode not in ('save', 'apply', 'save_apply'): raise ApiError(400, '未知保存方式')
        if not self._ready(): raise ApiError(409, '请先安装游戏')
        if not self.server.operation_lock.acquire(False): raise ApiError(409, '安装或服务器操作正在进行')
        try:
            with SERVER_CFG_LOCK:
                values = self._validate(updates)
                original = self.config.read()
                if revision != original['revision']: raise ApiError(409, '基础配置已变化，请重新读取')
                if original['pending']: raise ApiError(409, '上次基础设置保存未完成，请先恢复')
                multiplayer = self._multiplayer()
                if 'coop_players' in values:
                    if original['game_mode'] != 'coop': raise ApiError(409, '合作人数只用于普通合作模式，请先在游戏设置中切换为 coop')
                    if values['coop_players'] > 4 and not multiplayer: raise ApiError(409, '请先在插件页安装多人合作包')
                    if multiplayer: self.check_budget(values['coop_players'])
                    if mode == 'apply' and values['coop_players'] != original['coop_players']:
                        raise ApiError(400, '人数调整需要先保存启动配置，再完整重启游戏')
                if mode == 'apply' and 'server_name' in values and (not original['hostname_file'] or values['server_name'] != original['server_name']):
                    raise ApiError(400, '中文名称需要先保存到名称文件，请使用保存并应用')
                saved = mode != 'apply'
                commit = self.config.save(revision, values, multiplayer=multiplayer) if saved else {'revision': revision, 'changed': False, 'transaction': None}
                if saved and self.config.read()['hostname_file']: self.state.put('basic_settings_saved', True)
                if saved and commit.get('capacity_changed'):
                    self.state.put('basic_restart_required', True)
            fields = {name: {'saved': saved, 'state': 'saved' if saved else 'unverified'} for name in values}
            if mode == 'save' and 'coop_players' in fields and self.state.get('basic_restart_required') is True:
                fields['coop_players'].update(state='restart_required', message='人数已保存，请完整重启游戏后检查实际配置')
            if mode != 'save':
                for name, value in values.items():
                    field = fields[name]
                    try:
                        if name == 'server_name':
                            receipt = parse_name_receipt(self.rcon.run('sm_panel_hostname_reload'))
                            verified = receipt and receipt['state'] == 'ok' and receipt['actual'] == receipt['expected'] == value
                            field.update(state='applied' if verified else 'unverified', message='' if verified else '中文名称插件未确认精确名称，请检查插件加载')
                        elif name == 'ascii_fallback':
                            field.update(state='saved' if saved else 'unverified', message='备用名称在引擎读取配置时使用')
                        elif name == 'password':
                            out = self.rcon.run('sv_password "' + value + '"')
                            if re.search(r'unknown command|unable to|cannot|can.t change', out, re.I):
                                field.update(state='error', message='游戏拒绝了进服密码设置')
                            else: field.update(state='unverified', message='命令已发送；游戏隐藏密码，请用客户端验证')
                        elif name == 'region':
                            self.rcon.run('sv_region ' + str(value))
                            actual = self._cvar('sv_region')
                            field.update(state='applied' if actual == str(value) else 'unverified', actual=actual)
                        elif name == 'coop_players':
                            if value == 4 and not multiplayer:
                                field.update(state='unverified', message='原生四人合作；仍需客户端验证实际进服')
                            else:
                                actual = self.runtime(['coop_players'])['fields']['coop_players'].get('values', {})
                                expected = self._expected_count(value)
                                field.update(state='applied' if actual == expected else 'restart_required',
                                    message='' if actual == expected else '人数配置需要完整重启游戏；重启会断开当前玩家')
                    except Exception:
                        field.update(state='error', message='运行应用未确认；已保存的配置保留，请检查游戏后重试')
            self.invalidate()
            self.audit.add(actor, 'game.basic-settings', mode + ' fields=' + ','.join(sorted(values)))
            return {**commit, 'saved': saved, 'fields': fields,
                    'restart_required': self.state.get('basic_restart_required') is True or any(f['state'] == 'restart_required' for f in fields.values())}
        except (OSError, ValueError, ModeConfigError) as error: raise ApiError(409, str(error)) from None
        finally: self.server.operation_lock.release()

    def recover(self, actor):
        if not self.server.operation_lock.acquire(False): raise ApiError(409, '安装或服务器操作正在进行')
        try:
            if self.server.running(): raise ApiError(409, '请先停止游戏，再恢复未完成的基础设置事务')
            recovered = self.config.recover()
            self.audit.add(actor, 'game.basic-settings.recover', str(recovered))
            return {'recovered': recovered}
        except (OSError, ValueError, ModeConfigError) as error: raise ApiError(409, str(error)) from None
        finally: self.server.operation_lock.release()
