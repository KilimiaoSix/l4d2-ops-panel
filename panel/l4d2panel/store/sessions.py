"""Sessions table: opaque cookie value -> account, with an absolute expiry."""
import secrets, time

from .db import Database


class SessionStore:
    def __init__(self, db: Database, ttl_days: int):
        self.db, self.ttl = db, int(ttl_days) * 86400

    def create(self, account_id) -> str:
        sid = secrets.token_urlsafe(32)
        with self.db.cursor() as c:
            c.execute('INSERT INTO sessions(sid,account_id,expires) VALUES(?,?,?)', (sid, account_id, int(time.time()) + self.ttl))
        return sid

    def account_for(self, sid):
        """The account row of a live session, or None."""
        if not sid: return None
        with self.db.cursor() as c:
            row = c.execute('SELECT a.* FROM sessions s JOIN accounts a ON a.id=s.account_id WHERE s.sid=? AND s.expires>?', (sid, int(time.time()))).fetchone()
        return dict(row) if row else None

    def delete(self, sid):
        if sid:
            with self.db.cursor() as c: c.execute('DELETE FROM sessions WHERE sid=?', (sid,))

    def delete_others(self, account_id, keep_sid):
        with self.db.cursor() as c: c.execute('DELETE FROM sessions WHERE account_id=? AND sid<>?', (account_id, keep_sid or ''))
