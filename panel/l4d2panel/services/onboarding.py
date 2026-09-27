"""Persistent, non-secret setup progress; completion is checked against saved installation state."""
import threading

from ..errors import ApiError
from ..integrations.join_address import join_info

STEPS = ('panel', 'game', 'packs', 'settings', 'join')
DRAFT_KEYS = frozenset({'server_name', 'region', 'coop_players', 'game_port', 'tick', 'vac', 'packs'})


def validate_draft(draft):
    if not isinstance(draft, dict) or set(draft) - DRAFT_KEYS:
        raise ApiError(400, '只允许保存向导中的非秘密选项')
    for key, value in draft.items():
        if key == 'server_name':
            if not isinstance(value, str) or not 1 <= len(value.encode('utf-8')) <= 96 or any(ord(c) < 32 or c in '\x7f";\\' for c in value):
                raise ApiError(400, '服务器名称应为 1–96 个 UTF-8 字节且不含控制或命令字符')
        elif key == 'packs':
            if not isinstance(value, list) or not value or any(x not in ('minimal', 'multiplayer', 'infected', 'points') for x in value):
                raise ApiError(400, '插件包选择无效')
        elif key == 'vac':
            if type(value) is not bool: raise ApiError(400, 'VAC 选项必须为布尔值')
        else:
            valid = type(value) is int
            if key == 'region': valid = valid and value in (*range(8), 255)
            if key == 'coop_players': valid = valid and 4 <= value <= 12
            if key == 'game_port': valid = valid and 1 <= value <= 65535
            if key == 'tick': valid = valid and value in (30, 60, 100, 128)
            if not valid: raise ApiError(400, f'{key} 超出允许范围')


class OnboardingService:
    def __init__(self, state, paths, settings, audit):
        self.state, self.paths, self.settings, self.audit = state, paths, settings, audit
        self.lock = threading.Lock()

    def checks(self):
        game = all((self.paths.game / name).is_file() for name in ('steam.inf', 'gameinfo.txt', 'bin/server_srv.so'))
        # Receipt producers are the plugin and basic-settings services. A directory created
        # by an upload or a seeded owner account is never evidence that setup is complete.
        packs = self.state.get('minimal_pack_committed') is True
        basic = self.state.get('basic_settings_saved') is True
        restart = self.state.get('basic_restart_required') is True
        join = join_info(self.settings)
        return {'panel': {'ready': True, 'reason': ''},
                'game': {'ready': game, 'reason': '' if game else '请完成游戏安装'},
                'packs': {'ready': packs, 'reason': '' if packs else '请安装最小插件包'},
                'settings': {'ready': basic and not restart, 'reason': '请完整重启游戏并检查人数配置' if restart else '' if basic else '请保存服务器基础设置'},
                'join': {'ready': bool(join['address']), 'reason': join['error']}}

    def get(self):
        state = self.state.get('onboarding')
        checks = self.checks()
        return {'complete': state['completed'], 'step': state['step'], 'draft': state['draft'], 'checks': checks,
                'missing': [key for key, check in checks.items() if not check['ready']], 'public_access': 'unverified'}

    def save(self, step, draft, complete, reopen, actor):
        if step is not None and step not in STEPS: raise ApiError(400, '未知向导步骤')
        validate_draft(draft)
        with self.lock:
            state = self.state.get('onboarding')
            if complete:
                missing = [value['reason'] for value in self.checks().values() if not value['ready']]
                if missing: raise ApiError(409, '尚未完成：' + '；'.join(missing))
            if step is not None: state['step'] = step
            state['draft'] = {**state['draft'], **draft}
            if complete: state['completed'] = True
            if reopen: state['completed'] = False
            self.state.put('onboarding', state)
            self.audit.add(actor, 'panel.setup', f'step={state["step"]} complete={state["completed"]}')
        return self.get()
