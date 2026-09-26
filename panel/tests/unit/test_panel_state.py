from concurrent.futures import ThreadPoolExecutor
import threading

from l4d2panel.store.accounts import AccountStore
from l4d2panel.store.db import Database
from l4d2panel.store.panel_state import PanelStateStore
from l4d2panel.store.sessions import SessionStore


def test_new_seeded_database_resumes_onboarding(tmp_path):
    db = Database(tmp_path / 'db'); db.init()
    state = PanelStateStore(db); state.init()
    AccountStore(db).create_initial_owner('admin', 'unchanged-hash')
    state.put('onboarding', dict(schema=1, completed=False, step='game', draft={'server_name': 'Test'}))
    state.init()
    assert state.get('onboarding') == dict(schema=1, completed=False, step='game', draft={'server_name': 'Test'})


def test_existing_accounts_are_migrated_once_without_password_or_session_change(tmp_path):
    db = Database(tmp_path / 'db'); db.init()
    accounts = AccountStore(db); aid = accounts.create('legacy', 'legacy-hash', 'owner')
    sessions = SessionStore(db, 7); sid = sessions.create(aid)
    state = PanelStateStore(db); state.init()
    assert state.get('onboarding')['completed'] is True
    state.put('onboarding', dict(schema=1, completed=False, step='panel', draft={}))
    state.init()
    assert state.get('onboarding')['completed'] is False
    assert accounts.get(aid)['pass'] == 'legacy-hash'
    assert sessions.account_for(sid)['id'] == aid


def test_initial_owner_claim_serializes_separate_database_connections(tmp_path):
    path = tmp_path / 'db'; Database(path).init()
    barrier = threading.Barrier(2)
    def claim(i):
        store = AccountStore(Database(path))
        barrier.wait()
        return store.create_initial_owner(f'owner{i}', f'hash{i}')
    with ThreadPoolExecutor(2) as pool:
        result = list(pool.map(claim, range(2)))
    assert sum(x is not None for x in result) == 1
    assert AccountStore(Database(path)).owners() == 1
