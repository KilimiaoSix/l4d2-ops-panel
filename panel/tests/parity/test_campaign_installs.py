"""VPK uploads, Workshop search/install, and map selection summaries."""
import io
import zipfile

import pytest

from tests.fakes.vpk import build_vpk

MAP_VPK = build_vpk(['maps/c1m1_test.bsp', 'maps/c1m2_test.bsp', 'missions/testcamp.txt', 'materials/vgui/x.vtf'])
SKIN_VPK = build_vpk(['materials/models/survivors/coach.vtf', 'models/survivors/coach.mdl', 'addoninfo.txt'])


def make_zip(members):
    b = io.BytesIO()
    with zipfile.ZipFile(b, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, data in members.items(): z.writestr(name, data)
    return b.getvalue()


def test_upload_vpk_reports_installed_list(api, game_dir):
    r = api.post('/api/upload?name=camp2.vpk', content=MAP_VPK)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j['ok'] is True and j['skipped'] == [] and 'out' in j
    assert j['installed'] == [{'name': 'camp2.vpk', 'size_mb': 0.0, 'maps': ['c1m1_test', 'c1m2_test'], 'mission': 'testcamp', 'protected': False}]
    assert 'camp2.vpk' in game_dir.addon_names()


def test_upload_accepts_vpk_without_maps(api, game_dir):
    r = api.post('/api/upload?name=coach.vpk', content=SKIN_VPK)
    assert r.status_code == 200, r.text
    assert r.json()['installed'] == [{'name': 'coach.vpk', 'size_mb': 0.0, 'maps': [], 'mission': '', 'protected': False}]
    assert 'coach.vpk' in game_dir.addon_names() and not list(game_dir.addons.glob('*.uploading'))


def test_upload_cannot_overwrite_a_protected_addon(api, game_dir):
    before = (game_dir.addons / 'admin_system.vpk').read_bytes()
    r = api.post('/api/upload?name=admin_system.vpk', content=MAP_VPK)
    assert r.status_code == 400 and '受保护' in r.json()['error']
    assert (game_dir.addons / 'admin_system.vpk').read_bytes() == before


def test_upload_zip_installs_all_vpks(api, fake_game, game_dir):
    z = make_zip({'Some Campaign/camp.vpk': MAP_VPK, 'Some Campaign/coach.vpk': SKIN_VPK, 'readme.txt': b'hi', '__MACOSX/._camp.vpk': b'junk'})
    r = api.post('/api/upload?name=pack.zip', content=z)
    assert r.status_code == 200, r.text
    j = r.json()
    assert [a['name'] for a in j['installed']] == ['camp.vpk', 'coach.vpk'] and j['installed'][0]['maps'] == ['c1m1_test', 'c1m2_test']
    assert j['installed'][1]['maps'] == [] and j['skipped'] == []
    assert 'camp.vpk' in game_dir.addon_names() and 'coach.vpk' in game_dir.addon_names()
    assert not list(game_dir.addons.glob('*.zip*')) and not list(game_dir.addons.glob('*.uploading'))
    assert fake_game.commands[-2:] == ['update_addon_paths', 'mission_reload']


def test_upload_zip_failures(api, game_dir):
    before = game_dir.addon_names()
    r = api.post('/api/upload?name=pack.zip', content=make_zip({'readme.txt': b'hi', 'shot.jpg': b'x'}))
    assert r.status_code == 400 and 'readme.txt' in r.json()['error']
    r = api.post('/api/upload?name=pack.zip', content=make_zip({'coach.vpk': SKIN_VPK}))
    assert r.status_code == 200 and r.json()['installed'][0]['name'] == 'coach.vpk'
    r = api.post('/api/upload?name=pack.zip', content=b'Rar!\x1a\x07\x00 not a zip')
    assert r.status_code == 400 and 'zip' in r.json()['error']
    r = api.post('/api/upload?name=camp.rar', content=b'Rar!')
    assert r.status_code == 400 and '.zip' in r.json()['error']
    assert game_dir.addon_names() == sorted(before + ['coach.vpk']) and not list(game_dir.addons.glob('*.uploading'))


@pytest.mark.panel(steam_api_key='testkey')
def test_workshop_search(api, fake_steam):
    assert api.get('/api/status').json()['features']['workshop_search'] is True
    r = api.get('/api/workshop_search?q=helm')
    assert r.status_code == 200, r.text
    j = r.json()
    assert j['total'] == 57 and j['page'] == 1 and [i['id'] for i in j['items']] == ['2396847377', '100100100']   # result!=1 rows dropped
    it = j['items'][0]
    assert it == {'id': '2396847377', 'title': '广州增城 （Zengcheng）Lv8.06', 'size_mb': 827.0, 'subs': 1553836, 'updated': 1782860476,
                  'preview': 'https://images.example/zc.jpg', 'tags': ['Single Player', 'Co-op'], 'score': 0.91, 'desc': 'A campaign'}
    q = fake_steam.queries[-1]
    assert q['appid'] == ['550'] and 'requiredtags[0]' not in q and q['query_type'] == ['12'] and q['search_text'] == ['helm'] and q['page'] == ['1']
    r = api.get('/api/workshop_search?q=&page=2')
    assert r.status_code == 200 and r.json()['items'] == [] and r.json()['page'] == 2
    q = fake_steam.queries[-1]
    assert q['query_type'] == ['9'] and 'search_text' not in q and q['page'] == ['2']      # empty query = most subscribed workshop items


def test_workshop_search_needs_a_key(api):
    assert api.get('/api/status').json()['features']['workshop_search'] is False
    r = api.get('/api/workshop_search?q=x')
    assert r.status_code == 400 and 'steam_api_key' in r.json()['error']


@pytest.mark.panel(steam_api_key='wrong')
def test_workshop_search_with_a_rejected_key(api):
    r = api.get('/api/workshop_search?q=x')
    assert r.status_code >= 400 and 'Key' in r.json()['error'] and 'wrong' not in r.json()['error']


def test_workshop_download_installs_vpk_without_maps(api, panel, fake_steam, game_dir):
    fake_steam.add_item('100200200', SKIN_VPK, filename='coach.vpk', title='Coach Skin')
    assert api.post('/api/addons', json={'op': 'workshop', 'id': '100200200'}).status_code == 200
    job = panel.wait_for(lambda: (lambda j: j if j and j['state'] != 'running' else None)(api.get('/api/addons').json()['jobs'].get('100200200')), timeout=60)
    assert job['state'] == 'done' and '已安装: coach.vpk' in job['msg']
    assert 'coach.vpk' in game_dir.addon_names() and not (panel.dir / 'workshop_tmp' / '100200200.part').exists()
