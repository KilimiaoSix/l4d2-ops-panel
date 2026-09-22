"""SQLite connection + schema. One lock serialises writers (autocommit connections, WAL); the schema is the
one the single-file panel created, so an existing panel.db is used as-is."""
import os, sqlite3, threading, time
from contextlib import closing, contextmanager

SCHEMA = '''
CREATE TABLE IF NOT EXISTS accounts(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, pass TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'admin', steamid TEXT, flags TEXT DEFAULT '99:z', note TEXT, created INTEGER, last_login INTEGER);
CREATE TABLE IF NOT EXISTS sessions(sid TEXT PRIMARY KEY, account_id INTEGER, expires INTEGER);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, ts INTEGER, who TEXT, action TEXT, detail TEXT);'''


class Database:
    def __init__(self, path):
        self.path = str(path); self.lock = threading.Lock()

    def _connect(self):
        c = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        c.row_factory = sqlite3.Row
        try: c.execute('PRAGMA journal_mode=WAL')
        except sqlite3.Error: pass
        return c

    @contextmanager
    def cursor(self):
        """A connection held under the writer lock; closed afterwards (short-lived, like the original panel)."""
        with self.lock, closing(self._connect()) as c:
            yield c

    def init(self):
        with self.cursor() as c:
            c.executescript(SCHEMA)
            c.execute('DELETE FROM sessions WHERE expires<?', (int(time.time()),))
        try: os.chmod(self.path, 0o600)
        except OSError: pass
