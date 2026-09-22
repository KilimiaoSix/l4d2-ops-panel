"""Accounts: first-run setup, login with per-IP lockout, sessions. Passwords are PBKDF2-SHA256 in the same
`pbkdf2$iterations$salt$hash` format the single-file panel wrote, so existing accounts keep working."""
import hashlib, hmac, secrets, threading, time

from ..errors import ApiError
from ..settings import Settings
from ..store.accounts import AccountStore
from ..store.audit import AuditLog
from ..store.sessions import SessionStore


def hash_pw(pw, salt=None, it=200000):
    salt = salt or secrets.token_hex(16)
    return f'pbkdf2${it}${salt}$' + hashlib.pbkdf2_hmac('sha256', pw.encode(), bytes.fromhex(salt), it).hex()


def verify_pw(pw, stored):
    try:
        _a, it, salt, h = stored.split('$')
        return hmac.compare_digest(hashlib.pbkdf2_hmac('sha256', pw.encode(), bytes.fromhex(salt), int(it)).hex(), h)
    except Exception:
        return False


class LoginLimiter:
    """Six failed logins from one IP lock that IP out for a minute."""
    def __init__(self, limit=6, window=60):
        self.limit, self.window, self.fails, self.lock = limit, window, {}, threading.Lock()

    def locked(self, ip) -> bool:
        with self.lock:
            f = self.fails.get(ip)
            return bool(f and f[0] >= self.limit and time.time() - f[1] < self.window)

    def failed(self, ip):
        with self.lock:
            f = self.fails.get(ip, [0, 0]); self.fails[ip] = [f[0] + 1, time.time()]

    def reset(self, ip):
        with self.lock: self.fails.pop(ip, None)


class AuthService:
    def __init__(self, settings: Settings, accounts: AccountStore, sessions: SessionStore, audit: AuditLog):
        self.settings, self.accounts, self.sessions, self.audit = settings, accounts, sessions, audit
        self.limiter = LoginLimiter()

    def setup_needed(self) -> bool:
        return self.accounts.count() == 0

    def seed(self):
        """Startup: create the owner from panel.json's password once, or announce the setup page."""
        if self.accounts.count(): return
        u = self.settings.bootstrap_user
        if self.settings.password:
            self.accounts.create(u, hash_pw(self.settings.password), 'owner')
            print(f'[panel] seeded owner account "{u}" from panel.json password (change it in the 账号 tab)', flush=True)
        else:
            print(f'[panel] no accounts yet: the first visit to the panel sets the password of "{u}"', flush=True)

    def setup(self, password: str, ip: str) -> str:
        """First run: create the owner account with this password; returns a session id."""
        if len(password) < 4: raise ApiError(400, '密码至少 4 位')
        if not self.setup_needed(): raise ApiError(409, '面板已经初始化过了，请直接登录')
        u = self.settings.bootstrap_user
        aid = self.accounts.create(u, hash_pw(password), 'owner', last_login=int(time.time()))
        self.audit.add(u, 'setup', ip); print(f'[panel] owner account "{u}" created from {ip}', flush=True)
        return self.sessions.create(aid)

    def login(self, username: str, password: str, ip: str) -> str:
        if self.limiter.locked(ip): raise ApiError(429, '失败太多，1 分钟后再试')
        row = self.accounts.by_name(username.strip())
        if row and verify_pw(password, row['pass']):
            sid = self.sessions.create(row['id']); self.limiter.reset(ip)
            self.accounts.touch_login(row['id']); self.audit.add(row['username'], 'login', ip)
            return sid
        self.limiter.failed(ip); time.sleep(1)   # slows down guessing
        raise ApiError(403, '面板还没有初始化，请先设置管理员密码' if not row and self.setup_needed() else '用户名或密码错误')

    def logout(self, sid: str):
        self.sessions.delete(sid)

    def account_for(self, sid):
        """The account behind a session cookie value, or None."""
        return self.sessions.account_for(sid)
