"""Audit table: who did what. Writing never raises — an audit failure must not fail the action."""
import time

from .db import Database


class AuditLog:
    def __init__(self, db: Database):
        self.db = db

    def add(self, who, action, detail=''):
        try:
            with self.db.cursor() as c:
                c.execute('INSERT INTO audit(ts,who,action,detail) VALUES(?,?,?,?)', (int(time.time()), who or '?', action, str(detail)[:400]))
        except Exception:
            pass

    def recent(self, n=200):
        with self.db.cursor() as c:
            return [dict(r) for r in c.execute('SELECT id,ts,who,action,detail FROM audit ORDER BY id DESC LIMIT ?', (n,))]
