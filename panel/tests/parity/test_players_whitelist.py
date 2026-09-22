"""Online players (parsed from RCON `status`) and the whitelist plugin integration."""
from tests.fakes.game import HUMANS, STATUS_IDLE

ID64_BASE = 76561197960265728


def test_players_are_the_humans_of_the_status_reply(api, fake_game):
    d = api.get('/api/players').json()
    assert d['players'] == HUMANS
    assert d['raw'].startswith('hostname:') and d['raw'].rstrip().endswith('#end')
    assert fake_game.commands[-1] == 'status'


def test_players_empty_when_hibernating(api, fake_game):
    fake_game.status_text = STATUS_IDLE
    assert api.get('/api/players').json()['players'] == []


def test_whitelist_listing_skips_comments_and_blank_lines(api):
    assert api.get('/api/whitelist').json() == {'list': ['STEAM_1:0:111 // alice', 'STEAM_1:1:222']}


def test_whitelist_add_accepts_every_steam_id_form(api, fake_game):
    cases = [('STEAM_0:1:333', 'STEAM_1:1:333'),                                # SteamID2, any universe -> universe 1
             ('[U:1:200]', 'STEAM_1:0:100'),                                    # SteamID3
             (str(ID64_BASE + 301), 'STEAM_1:1:150'),                           # 17-digit SteamID64
             (f'https://steamcommunity.com/profiles/{ID64_BASE + 402}/', 'STEAM_1:0:201')]   # profile link
    for raw, canon in cases:
        r = api.post('/api/whitelist', json={'op': 'add', 'steamid': raw, 'note': 'bob "the" builder'})
        assert r.status_code == 200, (raw, r.text)
        assert fake_game.commands[-1] == f'sm_wl_addid {canon} "bob the builder"', raw   # quotes are stripped from the note
        assert f'{canon} // bob the builder' in r.json()['list']
    assert 'sm_wl_addid' in r.json()['out'] or '已加入' in r.json()['out']


def test_whitelist_delete_and_bad_input(api, fake_game):
    r = api.post('/api/whitelist', json={'op': 'del', 'steamid': 'STEAM_1:0:111'})
    assert r.status_code == 200 and fake_game.commands[-1] == 'sm_wl_del STEAM_1:0:111'
    assert r.json()['list'] == ['STEAM_1:1:222']
    assert api.post('/api/whitelist', json={'op': 'add', 'steamid': '???'}).status_code == 400
    assert api.post('/api/whitelist', json={'op': 'add', 'steamid': ''}).status_code == 400
    assert api.post('/api/whitelist', json={'op': 'move', 'steamid': 'STEAM_1:0:1'}).status_code == 400


def test_whitelist_toggle_is_reflected_in_status(api, fake_game):
    assert api.get('/api/status').json()['whitelist'] is True
    r = api.post('/api/whitelist_enable', json={'enable': False})
    assert r.status_code == 200 and 'out' in r.json() and fake_game.commands[-1] == 'sm_cvar sm_whitelist_enable 0'
    assert api.get('/api/status').json()['whitelist'] is False      # the 15 s flag cache is invalidated by the write
    api.post('/api/whitelist_enable', json={'enable': True})
    assert fake_game.commands[-1] == 'sm_cvar sm_whitelist_enable 1'
    assert api.get('/api/status').json()['whitelist'] is True
