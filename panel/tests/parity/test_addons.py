"""Campaign (.vpk) management: listing, upload, delete, zip packaging + download."""
import http.client
import io
import zipfile
from urllib.parse import quote

from tests.fakes.vpk import build_vpk


def test_list_addons_parses_vpk_contents(api):
    d = api.get('/api/addons').json()
    assert d['jobs'] == {} and d['zips'] == {}
    by = {a['name']: a for a in d['addons']}
    assert list(by) == ['admin_system.vpk', 'custom_campaign.vpk']
    assert by['admin_system.vpk'] == {'name': 'admin_system.vpk', 'size_mb': 0.0, 'maps': [], 'mission': '', 'protected': True}
    assert by['custom_campaign.vpk'] == {'name': 'custom_campaign.vpk', 'size_mb': 0.0, 'maps': ['cc1_start', 'cc2_end'], 'mission': 'customcamp', 'protected': False}


def test_upload_vpk_installs_and_hot_reloads(api, fake_game, game_dir):
    data = build_vpk(['maps/up1_a.bsp', 'missions/upmission.txt'])
    r = api.post('/api/upload?name=' + quote('新战役 v2.vpk'), content=data)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j['ok'] is True and j['installed'] == [{'name': '新战役 v2.vpk', 'size_mb': 0.0, 'maps': ['up1_a'], 'mission': 'upmission', 'protected': False}] and j['skipped'] == [] and 'out' in j
    assert fake_game.commands[-2:] == ['update_addon_paths', 'mission_reload']
    assert (game_dir.addons / '新战役 v2.vpk').read_bytes() == data
    assert not list(game_dir.addons.glob('*.uploading'))


def test_upload_rejects_bad_files(api, game_dir):
    before = game_dir.addon_names()
    r = api.post('/api/upload?name=bad.vpk', content=b'not a vpk at all')
    assert r.status_code == 400 and 'VPK' in r.json()['error']
    assert api.post('/api/upload?name=notes.txt', content=build_vpk(['maps/a.bsp'])).status_code == 400
    assert api.post('/api/upload', content=build_vpk(['a.txt'])).status_code == 400
    assert api.post('/api/upload?name=empty.vpk', content=b'').status_code == 400
    assert game_dir.addon_names() == before


def test_upload_over_the_size_limit_is_refused_before_reading(panel, api, game_dir):
    # max_upload_mb is 1 in the test config; claim a 3 MB body and see the 400 come back without sending it
    conn = http.client.HTTPConnection('127.0.0.1', panel.port, timeout=30)
    conn.putrequest('POST', '/api/upload?name=huge.vpk'); conn.putheader('Cookie', 'l4d2panel=' + api.cookies['l4d2panel']); conn.putheader('Content-Length', str(3 * 1048576)); conn.endheaders()
    conn.send(b'\x34\x12\xaa\x55')
    resp = conn.getresponse()
    assert resp.status == 400 and '1MB' in resp.read().decode()
    assert 'huge.vpk' not in game_dir.addon_names()


def test_delete_addon(api, fake_game, game_dir):
    assert api.post('/api/addons', json={'op': 'delete', 'name': 'admin_system.vpk'}).status_code == 400          # protected
    assert api.post('/api/addons', json={'op': 'delete', 'name': 'nope.vpk'}).status_code == 400
    assert api.post('/api/addons', json={'op': 'delete', 'name': '../cfg/server.cfg'}).status_code == 400
    r = api.post('/api/addons', json={'op': 'delete', 'name': 'custom_campaign.vpk'})
    assert r.status_code == 200 and r.json()['ok'] is True
    assert [a['name'] for a in r.json()['addons']] == ['admin_system.vpk'] and game_dir.addon_names() == ['admin_system.vpk']
    assert fake_game.commands[-2:] == ['update_addon_paths', 'mission_reload']
    assert game_dir.cfg.exists()
    assert api.post('/api/addons', json={'op': 'frobnicate'}).status_code == 400


def test_zip_then_download(api, panel, game_dir):
    r = api.post('/api/addons', json={'op': 'zip', 'name': 'custom_campaign.vpk'})
    assert r.status_code == 200 and r.json()['ok'] is True
    token = r.json()['token']
    job = panel.wait_for(lambda: (lambda z: z if z and z['state'] != 'running' else None)(api.get('/api/addons').json()['zips'].get(token)))
    assert job['state'] == 'done' and job['name'] == 'custom_campaign.zip' and job['size_mb'] == 0.0 and job['token'] == token
    r = api.get('/api/download?token=' + token)
    assert r.status_code == 200 and r.headers['content-type'] == 'application/zip'
    assert "filename*=UTF-8''custom_campaign.zip" in r.headers['content-disposition']
    z = zipfile.ZipFile(io.BytesIO(r.content))
    assert sorted(z.namelist()) == sorted(['custom_campaign.vpk', '安装说明.txt'])
    assert z.read('custom_campaign.vpk') == (game_dir.addons / 'custom_campaign.vpk').read_bytes()
    assert '附加组件' in z.read('安装说明.txt').decode('utf-8')
    r = api.get('/api/download?token=nope')
    assert r.status_code == 404 and 'error' in r.json()


def test_zip_several_and_invalid(api, panel):
    r = api.post('/api/addons', json={'op': 'zip', 'names': ['custom_campaign.vpk', 'admin_system.vpk']})
    token = r.json()['token']
    job = panel.wait_for(lambda: (lambda z: z if z and z['state'] != 'running' else None)(api.get('/api/addons').json()['zips'].get(token)))
    assert job['state'] == 'done' and job['name'] == 'l4d2_addons.zip'
    assert api.post('/api/addons', json={'op': 'zip', 'names': []}).status_code == 400
    r = api.post('/api/addons', json={'op': 'zip', 'name': 'missing.vpk'})
    token = r.json()['token']
    job = panel.wait_for(lambda: (lambda z: z if z and z['state'] != 'running' else None)(api.get('/api/addons').json()['zips'].get(token)))
    assert job['state'] == 'error' and 'vpk' in job['msg']
