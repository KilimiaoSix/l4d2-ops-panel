"""Persistent panel state. Initial onboarding migration runs before bootstrap account seeding."""
import json

from .db import Database


class PanelStateStore:
    def __init__(self, db: Database):
        self.db = db

    def init(self):
        with self.db.cursor() as c:
            c.execute('BEGIN IMMEDIATE')
            try:
                c.execute('CREATE TABLE IF NOT EXISTS panel_state(key TEXT PRIMARY KEY, value TEXT NOT NULL)')
                used = bool(c.execute('SELECT 1 FROM accounts LIMIT 1').fetchone())
                state = {'schema': 1, 'completed': used, 'step': 'join' if used else 'panel', 'draft': {}}
                c.execute('INSERT OR IGNORE INTO panel_state(key,value) VALUES(?,?)', ('onboarding', json.dumps(state)))
                c.commit()
            except Exception:
                c.rollback()
                raise

    def get(self, key):
        with self.db.cursor() as c:
            row = c.execute('SELECT value FROM panel_state WHERE key=?', (key,)).fetchone()
            return json.loads(row[0]) if row else None

    def put(self, key, value):
        with self.db.cursor() as c:
            c.execute('INSERT INTO panel_state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                      (key, json.dumps(value, ensure_ascii=False)))
