"""Panel accounts (owner / admin), self-service password and Steam binding, and the SourceMod admin sync:
accounts with a SteamID are written into the panel-managed block of admins_simple.ini and hot-reloaded."""
import re

from ..errors import ApiError
from ..integrations.rcon import RconClient
from ..integrations.sm_files import write_admins_block
from ..integrations.steam import SteamClient
from ..integrations.steamid import parse_steamid
from ..settings import Paths
from ..store.accounts import AccountStore, DuplicateUsername
from ..store.audit import AuditLog
from ..store.sessions import SessionStore
from .auth import hash_pw, verify_pw

USERNAME = re.compile(r'^[\w.\-]{2,32}$')
ME_FIELDS = ('username', 'role', 'steamid', 'flags', 'created', 'last_login')


class AccountService:
    def __init__(self, paths: Paths, accounts: AccountStore, sessions: SessionStore, audit: AuditLog, steam: SteamClient, rcon: RconClient):
        self.paths, self.accounts, self.sessions, self.audit, self.steam, self.rcon = paths, accounts, sessions, audit, steam, rcon

    def parse_steamid(self, raw) -> str:
        try: return parse_steamid(raw, self.steam.resolve_vanity)
        except ValueError as e: raise ApiError(400, str(e))

    def sync_admins(self) -> str:
        rows = [(r['id'], r['username'], r['steamid'], r['flags']) for r in self.accounts.with_steamid()]
        write_admins_block(self.paths.admins_ini, rows)
        try: return self.rcon.run('sm_reloadadmins') or 'admin cache reloaded'
        except Exception as e: return f'(已写入，reload 失败: {e})'

    # ---- self service ----
    def me(self, account: dict) -> dict:
        return {k: account[k] for k in ME_FIELDS}

    def change_password(self, account: dict, current: str, new: str, sid: str):
        if not verify_pw(current, account['pass']): raise ApiError(403, '当前密码不对')
        if len(new) < 4: raise ApiError(400, '新密码至少 4 位')
        self.accounts.update(account['id'], **{'pass': hash_pw(new)})
        self.sessions.delete_others(account['id'], sid)   # other devices must log in again
        self.audit.add(account['username'], 'account.password', 'self')

    def bind_steam(self, account: dict, raw) -> tuple:
        """-> (canonical steamid or '', admin sync output)"""
        sid = self.parse_steamid(raw)
        self.accounts.update(account['id'], steamid=sid or None)
        self.audit.add(account['username'], 'account.steamid', sid or '(unbound)')
        return sid, self.sync_admins()

    # ---- owner: manage everyone ----
    def list(self, account: dict) -> dict:
        return {'accounts': self.accounts.list(), 'me': account['username']}

    def create(self, actor: str, username: str, password: str, role, steamid, flags, note) -> str:
        username = username.strip()
        if not USERNAME.match(username): raise ApiError(400, '用户名 2-32 位（字母数字 . _ -）')
        if len(password) < 4: raise ApiError(400, '密码至少 4 位')
        sid = self.parse_steamid(steamid)
        try:
            self.accounts.create(username, hash_pw(password), 'owner' if role == 'owner' else 'admin', sid or None, str(flags or '').strip() or '99:z', str(note or '').strip())
        except DuplicateUsername:
            raise ApiError(400, '用户名已存在')
        self.audit.add(actor, 'account.create', username)
        return self.sync_admins() if sid else ''

    def update(self, actor: str, account_id: int, password=None, role=None, steamid=None, flags=None, note=None) -> str:
        fields = {}
        if password: fields['pass'] = hash_pw(str(password))
        if role is not None: fields['role'] = 'owner' if role == 'owner' else 'admin'
        if steamid is not None: fields['steamid'] = self.parse_steamid(steamid) or None
        if flags is not None: fields['flags'] = str(flags).strip() or '99:z'
        if note is not None: fields['note'] = str(note).strip()
        if not fields: raise ApiError(400, '没有要修改的字段')
        self.accounts.update(account_id, **fields)
        self.audit.add(actor, 'account.update', str(account_id))
        return self.sync_admins()

    def delete(self, account: dict, account_id: int) -> str:
        if account_id == account['id']: raise ApiError(400, '不能删除自己')
        tgt = self.accounts.get(account_id)
        if tgt and tgt['role'] == 'owner' and self.accounts.owners() <= 1: raise ApiError(400, '至少保留一个 owner')
        self.accounts.delete(account_id)
        self.audit.add(account['username'], 'account.delete', str(account_id))
        return self.sync_admins()
