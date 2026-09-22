"""SourceMod plugin manager: listing, enable / disable / reload / delete, .smx upload, protected plugins, audit."""
from tests.conftest import SMX_MAGIC
from tests.fakes.game import PLUGINS_LIST


def test_list_plugins(api):
    d = api.get('/api/plugins').json()
    assert d['enabled'] == [{'file': 'myplugin.smx', 'protected': False}, {'file': 'sm_whitelist.smx', 'protected': True}]
    assert d['disabled'] == [{'file': 'oldplugin.smx'}]
    assert d['raw'] == PLUGINS_LIST


def test_plugin_lifecycle(api, panel, fake_game, game_dir):
    r = api.post('/api/plugins', json={'op': 'disable', 'file': 'myplugin.smx'})
    assert r.status_code == 200, r.text
    assert fake_game.commands[-2:] == ['sm plugins unload myplugin', 'sm plugins list'] and 'disabled/' in r.json()['out']   # the reply carries a fresh listing
    assert r.json()['enabled'] == [{'file': 'sm_whitelist.smx', 'protected': True}] and r.json()['disabled'] == [{'file': 'myplugin.smx'}, {'file': 'oldplugin.smx'}]
    assert (game_dir.disabled / 'myplugin.smx').exists() and not (game_dir.plugins / 'myplugin.smx').exists()
    assert api.post('/api/plugins', json={'op': 'disable', 'file': 'sm_whitelist.smx'}).status_code == 400     # protected
    assert api.post('/api/plugins', json={'op': 'disable', 'file': 'ghost.smx'}).status_code == 400
    assert api.post('/api/plugins', json={'op': 'delete', 'file': 'sm_whitelist'}).status_code == 400          # protected, and enabled
    r = api.post('/api/plugins', json={'op': 'enable', 'file': 'oldplugin.smx'})
    assert r.status_code == 200 and fake_game.commands[-2] == 'sm plugins load oldplugin' and '已启用' in r.json()['out']
    assert (game_dir.plugins / 'oldplugin.smx').exists() and not (game_dir.disabled / 'oldplugin.smx').exists()
    assert api.post('/api/plugins', json={'op': 'delete', 'file': 'oldplugin.smx'}).status_code == 400          # only disabled plugins can be deleted
    r = api.post('/api/plugins', json={'op': 'reload', 'file': 'oldplugin'})
    assert r.status_code == 200 and fake_game.commands[-2] == 'sm plugins reload oldplugin'
    r = api.post('/api/plugins', json={'op': 'delete', 'file': 'myplugin.smx'})
    assert r.status_code == 200 and not (game_dir.disabled / 'myplugin.smx').exists() and r.json()['disabled'] == []
    assert api.post('/api/plugins', json={'op': 'explode', 'file': 'oldplugin.smx'}).status_code == 400
    assert api.post('/api/plugins', json={'op': 'reload', 'file': 'evil plugin;rm'}).status_code == 400   # names are [A-Za-z0-9_.-] only
    acts = panel.audit_actions()
    for a in ('plugin.disable', 'plugin.enable', 'plugin.reload', 'plugin.delete'):
        assert ('admin', a) in acts, a


def test_plugin_upload(api, panel, fake_game, game_dir):
    r = api.post('/api/plugin_upload?name=fresh.smx', content=SMX_MAGIC + b'\0' * 32)
    assert r.status_code == 200, r.text
    assert r.json()['ok'] is True and fake_game.commands[-2:] == ['sm plugins load fresh', 'sm plugins list']
    assert {'file': 'fresh.smx', 'protected': False} in r.json()['enabled']
    assert (game_dir.plugins / 'fresh.smx').read_bytes() == SMX_MAGIC + b'\0' * 32
    assert api.post('/api/plugin_upload?name=bad.smx', content=b'ELF\x00' * 8).status_code == 400
    assert not (game_dir.plugins / 'bad.smx').exists()
    assert api.post('/api/plugin_upload?name=e.smx', content=b'').status_code == 400
    assert ('admin', 'plugin.upload') in panel.audit_actions()
