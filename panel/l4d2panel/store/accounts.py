"""Accounts table."""
import sqlite3, time

from .db import Database


class DuplicateUsername(Exception):
    pass


class AccountStore:
    def __init__(self, db: Database):
        self.db = db

    def count(self) -> int:
        with self.db.cursor() as c: return c.execute('SELECT COUNT(*) FROM accounts').fetchone()[0]

    def by_name(self, username):
        with self.db.cursor() as c: return c.execute('SELECT * FROM accounts WHERE username=?', (username,)).fetchone()

    def get(self, account_id):
        with self.db.cursor() as c: return c.execute('SELECT * FROM accounts WHERE id=?', (account_id,)).fetchone()

    def list(self):
        with self.db.cursor() as c:
            return [dict(r) for r in c.execute('SELECT id,username,role,steamid,flags,note,created,last_login FROM accounts ORDER BY id')]

    def with_steamid(self):
        with self.db.cursor() as c:
            return c.execute("SELECT id,username,steamid,flags FROM accounts WHERE steamid IS NOT NULL AND steamid<>'' ORDER BY id").fetchall()

    def create(self, username, pw_hash, role, steamid=None, flags='99:z', note=None, last_login=None) -> int:
        try:
            with self.db.cursor() as c:
                return c.execute('INSERT INTO accounts(username,pass,role,steamid,flags,note,created,last_login) VALUES(?,?,?,?,?,?,?,?)',
                                 (username, pw_hash, role, steamid or None, flags, note, int(time.time()), last_login)).lastrowid
        except sqlite3.IntegrityError:
            raise DuplicateUsername(username)

    def update(self, account_id, **fields):
        """fields: any of pass, role, steamid, flags, note (only the given ones change)."""
        if not fields: return
        with self.db.cursor() as c:
            c.execute('UPDATE accounts SET ' + ','.join(f'{k}=?' for k in fields) + ' WHERE id=?', [*fields.values(), account_id])

    def touch_login(self, account_id):
        with self.db.cursor() as c: c.execute('UPDATE accounts SET last_login=? WHERE id=?', (int(time.time()), account_id))

    def owners(self) -> int:
        with self.db.cursor() as c: return c.execute("SELECT COUNT(*) FROM accounts WHERE role='owner'").fetchone()[0]

    def delete(self, account_id):
        with self.db.cursor() as c:
            c.execute('DELETE FROM accounts WHERE id=?', (account_id,)); c.execute('DELETE FROM sessions WHERE account_id=?', (account_id,))
