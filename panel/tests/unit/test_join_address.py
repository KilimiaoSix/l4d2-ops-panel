import pytest

from l4d2panel.integrations.join_address import endpoint, join_info
from l4d2panel.settings import Settings


@pytest.mark.parametrize('host,port,expected', [
    ('play.example', 27020, 'play.example:27020'),
    ('PLAY.Example:27021', 27020, 'play.example:27021'),
    ('1.2.3.4', 27015, '1.2.3.4:27015'),
    ('1.2.3.4:27022', 27015, '1.2.3.4:27022'),
    ('[2001:db8::1]', 27015, '[2001:db8::1]:27015'),
    ('[2001:db8::1]:27020', 27015, '[2001:db8::1]:27020'),
    ('2001:db8::1', 27015, '[2001:db8::1]:27015'),
    ('游戏.example', 27015, 'xn--unup4y.example:27015'),
])
def test_normalized_endpoint_with_port_exactly_once(host, port, expected):
    assert endpoint(host, port)[0] == expected


@pytest.mark.parametrize('host', ['', 'a;quit', 'a"', 'a\\b', 'a\nquit', 'a quit', 'https://a',
    'user:password@a', 'a/path', 'a?password=x', 'a#b', 'a:0', 'a:65536', 'a:', '999.1.2.3',
    '[::1];quit', '[::1]:27015:27016', '[fe80::1%eth0]', 'fe80::1%eth0;quit', 'fe80::1%eth0',
    '-a.example', 'a..b', 'a`id`'])
def test_invalid_endpoint_never_becomes_console_command(host):
    with pytest.raises(ValueError): endpoint(host, 27015)
    result = join_info(Settings(display_host=host))
    assert result['command'] == result['address'] == '' and result['error']


def test_join_document_has_no_secrets_and_no_external_connectivity_claim():
    settings = Settings(display_host='game.example', rcon_port=27020, password='owner-secret',
                        rcon_password='rcon-secret', steam_api_key='steam-secret')
    result = join_info(settings)
    assert result['command'] == 'connect game.example:27020'
    assert result['public_access'] == 'unverified'
    assert 'secret' not in str(result)
