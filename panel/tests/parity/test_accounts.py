"""Accounts: self-service password / Steam binding, owner-only account management, SourceMod admin sync."""
from tests.conftest import OWNER_PW, OWNER_USER


def test_me_and_password_change_logs_out_other_devices(panel):
    a = panel.login(); b = panel.login()
    me = a.get('/api/me').json()
    assert me['username'] == OWNER_USER and me['role'] == 'owner' and me['steamid'] is None and me['flags'] == '99:z'
    assert isinstance(me['created'], int) and isinstance(me['last_login'], int)
    assert a.post('/api/me', json={'op': 'password', 'current': 'wrong', 'password': 'newpass'}).status_code == 403
    assert a.post('/api/me', json={'op': 'password', 'current': OWNER_PW, 'password': '123'}).status_code == 400
    assert a.post('/api/me', json={'op': 'password', 'current': OWNER_PW, 'password': 'newpass'}).json() == {'ok': True}
    assert a.get('/api/me').status_code == 200                      # this device stays logged in
    assert b.get('/api/me').status_code == 401                      # every other device is logged out
    assert panel.client().post('/api/login', json={'username': OWNER_USER, 'password': OWNER_PW}).status_code == 403
    assert panel.login(password='newpass').get('/api/me').status_code == 200
    assert a.post('/api/me', json={'op': 'dance'}).status_code == 400
    assert (OWNER_USER, 'account.password') in panel.audit_actions()


def test_bind_steam_maintains_the_admins_block(api, panel, fake_game, game_dir):
    r = api.post('/api/me', json={'op': 'steamid', 'steamid': '[U:1:200]'})
    assert r.status_code == 200 and r.json()['ok'] is True and r.json()['steamid'] == 'STEAM_1:0:100' and 'Admin cache' in r.json()['out']
    assert fake_game.commands[-1] == 'sm_reloadadmins'
    ini = game_dir.admins.read_text(encoding='utf-8')
    assert ini.startswith('// SourceMod admins\n"STEAM_1:0:999" "99:z" // existing admin\n')
    assert '// ==== panel-managed BEGIN' in ini and ini.rstrip().endswith('// ==== panel-managed END ====')
    assert '"STEAM_1:0:100" "99:z"    // panel#1 admin' in ini
    assert api.get('/api/me').json()['steamid'] == 'STEAM_1:0:100'
    r = api.post('/api/me', json={'op': 'steamid', 'steamid': ''})
    assert r.json()['ok'] is True and r.json()['steamid'] == ''
    ini = game_dir.admins.read_text(encoding='utf-8')
    assert 'STEAM_1:0:100' not in ini and '"STEAM_1:0:999" "99:z" // existing admin' in ini and ini.count('panel-managed BEGIN') == 1
    assert api.post('/api/me', json={'op': 'steamid', 'steamid': 'not an id!'}).status_code == 400
    assert (OWNER_USER, 'account.steamid') in panel.audit_actions()


def test_owner_manages_accounts(api, panel, fake_game, game_dir):
    d = api.get('/api/accounts').json()
    assert d['me'] == OWNER_USER and len(d['accounts']) == 1
    a = d['accounts'][0]
    assert {k: a[k] for k in ('id', 'username', 'role', 'steamid', 'flags', 'note')} == {'id': 1, 'username': OWNER_USER, 'role': 'owner', 'steamid': None, 'flags': '99:z', 'note': None}
    assert api.post('/api/accounts', json={'op': 'create', 'username': 'a', 'password': 'bobpass'}).status_code == 400
    assert api.post('/api/accounts', json={'op': 'create', 'username': 'bob', 'password': '123'}).status_code == 400
    assert api.post('/api/accounts', json={'op': 'create', 'username': 'bob', 'password': 'bobpass', 'steamid': 'nope!'}).status_code == 400
    r = api.post('/api/accounts', json={'op': 'create', 'username': 'bob', 'password': 'bobpass', 'role': 'admin', 'steamid': 'STEAM_1:0:555', 'flags': 'z', 'note': 'friend'})
    assert r.status_code == 200 and r.json()['ok'] is True and 'Admin cache' in r.json()['out']
    assert '"STEAM_1:0:555" "z"    // panel#2 bob' in game_dir.admins.read_text(encoding='utf-8')
    r = api.post('/api/accounts', json={'op': 'create', 'username': 'bob', 'password': 'bobpass'})
    assert r.status_code == 400 and '已存在' in r.json()['error']
    r = api.post('/api/accounts', json={'op': 'create', 'username': 'carol', 'password': 'carolpass', 'role': 'owner'})
    assert r.status_code == 200 and r.json()['out'] == ''            # no SteamID: nothing to sync
    accts = {a['username']: a for a in api.get('/api/accounts').json()['accounts']}
    assert accts['bob']['role'] == 'admin' and accts['bob']['steamid'] == 'STEAM_1:0:555' and accts['bob']['flags'] == 'z' and accts['bob']['note'] == 'friend' and accts['bob']['last_login'] is None
    assert accts['carol']['role'] == 'owner'
    # admins can log in and use the panel but not the account list
    bob = panel.login('bob', 'bobpass')
    assert bob.get('/api/status').status_code == 200
    assert bob.get('/api/accounts').status_code == 403 and bob.post('/api/accounts', json={'op': 'delete', 'id': 1}).status_code == 403
    # update: role / steamid / flags / note / password
    r = api.post('/api/accounts', json={'op': 'update', 'id': 2, 'role': 'owner', 'steamid': '', 'flags': '', 'note': 'promoted', 'password': 'bobpass2'})
    assert r.status_code == 200 and r.json()['ok'] is True
    bob2 = accts = {a['username']: a for a in api.get('/api/accounts').json()['accounts']}['bob']
    assert bob2['role'] == 'owner' and bob2['steamid'] is None and bob2['flags'] == '99:z' and bob2['note'] == 'promoted'
    assert 'STEAM_1:0:555' not in game_dir.admins.read_text(encoding='utf-8')
    assert panel.login('bob', 'bobpass2').get('/api/accounts').status_code == 200
    assert api.post('/api/accounts', json={'op': 'update', 'id': 2}).status_code == 400
    # delete: not yourself; deleting an account kills its sessions
    assert api.post('/api/accounts', json={'op': 'delete', 'id': 1}).status_code == 400
    assert bob.get('/api/me').status_code == 200
    r = api.post('/api/accounts', json={'op': 'delete', 'id': 2})
    assert r.status_code == 200 and r.json()['ok'] is True
    assert bob.get('/api/me').status_code == 401
    assert [a['username'] for a in api.get('/api/accounts').json()['accounts']] == [OWNER_USER, 'carol']
    assert api.post('/api/accounts', json={'op': 'rename'}).status_code == 400
    acts = panel.audit_actions()
    for a in ('account.create', 'account.update', 'account.delete'):
        assert (OWNER_USER, a) in acts, a
