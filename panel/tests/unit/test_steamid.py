import pytest

from l4d2panel.integrations.steamid import STEAMID64_BASE, parse_steamid


@pytest.mark.parametrize('raw, canon', [
    ('', ''), ('   ', ''),
    ('STEAM_0:1:333', 'STEAM_1:1:333'), ('steam_1:0:7', 'STEAM_1:0:7'),
    ('[U:1:200]', 'STEAM_1:0:100'), ('U:1:201', 'STEAM_1:1:100'),
    (str(STEAMID64_BASE + 301), 'STEAM_1:1:150'),
    (f'https://steamcommunity.com/profiles/{STEAMID64_BASE + 402}/', 'STEAM_1:0:201'),
])
def test_forms_without_network(raw, canon):
    assert parse_steamid(raw, resolve_vanity=None) == canon


def test_vanity_uses_the_resolver():
    calls = []
    def resolver(name): calls.append(name); return str(STEAMID64_BASE + 10) if name == 'kili' else None
    assert parse_steamid('https://steamcommunity.com/id/kili/', resolver) == 'STEAM_1:0:5'
    assert parse_steamid('kili', resolver) == 'STEAM_1:0:5'
    assert calls == ['kili', 'kili']
    with pytest.raises(ValueError, match='自定义主页'):
        parse_steamid('nobody', resolver)


def test_garbage():
    with pytest.raises(ValueError, match='无法识别'):
        parse_steamid('not an id!', None)
    with pytest.raises(ValueError):
        parse_steamid(str(STEAMID64_BASE - 1), None)       # below the SteamID64 base -> negative account id
