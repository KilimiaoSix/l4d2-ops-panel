"""Steam Workshop downloads: Web API lookup, parallel ranged CDN fetch with retry / cancel / resume, install + hot reload."""
import math

from tests.fakes.vpk import build_vpk

CHUNK = 8 * 1048576


def big_vpk(extra):
    return build_vpk(['maps/ws1_start.bsp', 'missions/ws.txt']) + b'\0' * extra


def job_when_finished(api, pubid):
    def probe():
        j = api.get('/api/addons').json()['jobs'].get(pubid)
        return j if j and j['state'] != 'running' else None
    return probe


def test_workshop_download_installs_the_vpk(api, panel, fake_game, fake_steam, game_dir):
    data = big_vpk(2 * CHUNK + 4096)                                       # 3 ranges of 8 MB
    fake_steam.add_item('123456789', data, filename='Cool Campaign.vpk', title='Cool')
    r = api.post('/api/addons', json={'op': 'workshop', 'id': 'https://steamcommunity.com/sharedfiles/filedetails/?id=123456789'})
    assert r.status_code == 200 and r.json() == {'ok': True, 'id': '123456789'}
    job = panel.wait_for(job_when_finished(api, '123456789'), timeout=120)
    assert job['state'] == 'done', job
    assert job['files'] == ['Cool Campaign.vpk'] and job['name'] == 'Cool Campaign.vpk' and job['title'] == 'Cool'
    assert job['total'] == len(data) and job['done'] == len(data) and '已安装' in job['msg']
    assert (game_dir.addons / 'Cool Campaign.vpk').read_bytes() == data
    assert fake_game.commands[-2:] == ['update_addon_paths', 'mission_reload']
    assert len(fake_steam.range_requests('123456789')) == math.ceil(len(data) / CHUNK)
    assert not list((panel.dir / 'workshop_tmp').glob('*.part*'))
    assert 'Cool Campaign.vpk' in [a['name'] for a in api.get('/api/addons').json()['addons']]


def test_workshop_retries_a_cut_range(api, panel, fake_steam, game_dir):
    data = big_vpk(CHUNK + 100)
    fake_steam.add_item('100000222', data); fake_steam.fail_ranges['100000222'] = 1
    api.post('/api/addons', json={'op': 'workshop', 'id': '100000222'})
    job = panel.wait_for(job_when_finished(api, '100000222'), timeout=120)
    assert job['state'] == 'done', job
    assert (game_dir.addons / 'campaign.vpk').read_bytes() == data
    assert len(fake_steam.range_requests('100000222')) == 3                     # 2 ranges + 1 retry
    assert '第 1 次失败' in (panel.dir / 'workshop_tmp' / '100000222.log').read_text(encoding='utf-8')


def test_workshop_cancel_keeps_parts_and_resumes(api, panel, fake_steam, game_dir):
    data = big_vpk(CHUNK + 100)
    fake_steam.add_item('100000333', data)
    fake_steam.hold.set()                                                  # CDN stalls: the job stays running
    assert api.post('/api/addons', json={'op': 'workshop', 'id': '100000333'}).json()['ok'] is True
    panel.wait_for(lambda: len(fake_steam.range_requests('100000333')) >= 1)
    assert api.post('/api/addons', json={'op': 'workshop', 'id': '100000333'}).status_code == 400            # already running
    assert api.get('/api/addons').json()['jobs']['100000333']['state'] == 'running'
    assert api.post('/api/addons', json={'op': 'workshop_cancel', 'id': '100000333'}).json() == {'ok': True}
    fake_steam.hold.clear()
    job = panel.wait_for(job_when_finished(api, '100000333'), timeout=60)
    assert job['state'] == 'error' and '已取消' in job['msg']
    assert (panel.dir / 'workshop_tmp' / '100000333.part').exists() and not (game_dir.addons / 'campaign.vpk').exists()
    assert api.post('/api/addons', json={'op': 'workshop_cancel', 'id': '100000333'}).status_code == 400    # nothing running any more
    api.post('/api/addons', json={'op': 'workshop', 'id': '100000333'})                                     # second attempt continues
    job = panel.wait_for(job_when_finished(api, '100000333'), timeout=120)
    assert job['state'] == 'done' and (game_dir.addons / 'campaign.vpk').read_bytes() == data


def test_workshop_rejects_unusable_items(api, panel, fake_steam, game_dir):
    fake_steam.add_item('100000401', b'x', file_type=2)                          # a collection
    fake_steam.add_item('100000402', b'x', consumer_app_id=440)                  # not L4D2
    fake_steam.add_item('100000403', b'x', file_url='', file_size=0)             # no direct file and no DepotDownloader configured
    fake_steam.add_item('100000404', b'not a vpk' * 100)                         # downloads but is not a VPK
    for pubid, needle in [('100000401', '合集'), ('100000402', 'Left 4 Dead 2'), ('100000403', '没有可直接下载'), ('100000404', '不是 VPK'), ('100000999', '没有这个物品')]:
        assert api.post('/api/addons', json={'op': 'workshop', 'id': pubid}).status_code == 200
        job = panel.wait_for(job_when_finished(api, pubid), timeout=60)
        assert job['state'] == 'error' and needle in job['msg'], (pubid, job)
    assert game_dir.addon_names() == ['admin_system.vpk', 'custom_campaign.vpk']
    r = api.post('/api/addons', json={'op': 'workshop', 'id': 'abc'})
    assert r.status_code == 400 and '创意工坊' in r.json()['error']
