"""SteamClient vanity-URL resolution: the Web API path (needed where steamcommunity.com is blocked) and the XML fallback."""
from l4d2panel.integrations.steam import SteamClient

ID64 = '76561198100202943'
DEAD = 'http://127.0.0.1:1'        # refuses at once, like a host that cannot be reached at all


def test_vanity_prefers_the_web_api(fake_steam):
    fake_steam.vanity['kili'] = ID64
    steam = SteamClient(fake_steam.base, DEAD, fake_steam.api_key)      # community side unreachable
    assert steam.resolve_vanity('kili') == ID64
    assert steam.resolve_vanity('nobody') is None                       # success=42 is an answer, not a failure
    assert any('/ISteamUser/ResolveVanityURL/' in path for _, path, _ in fake_steam.requests)


def test_vanity_falls_back_to_community_xml(fake_steam):
    fake_steam.vanity['kili'] = ID64
    assert SteamClient(fake_steam.base, fake_steam.base).resolve_vanity('kili') == ID64                   # no key configured
    assert SteamClient(fake_steam.base, fake_steam.base, 'wrongkey').resolve_vanity('kili') == ID64       # key rejected -> XML
    assert SteamClient(fake_steam.base, fake_steam.base, fake_steam.api_key).resolve_vanity('ghost') is None
    assert SteamClient(DEAD, DEAD, fake_steam.api_key).resolve_vanity('kili') is None                     # nothing answers
