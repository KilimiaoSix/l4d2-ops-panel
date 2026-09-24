from types import SimpleNamespace

import pytest

from l4d2panel.errors import IntegrationError
from l4d2panel.integrations.convars import read_convar
from l4d2panel.services.plugin_config import PluginConfigService


@pytest.mark.parametrize('response', [
    '[SM] Value of cvar "test_value": "0"',
    '[SM] 变量 "test_value" 的值为 "0"',
    '"test_value" = "0"\n - description',
])
def test_convar_read_uses_identifiers_not_translated_prose(response):
    assert read_convar(SimpleNamespace(run=lambda command: response), 'test_value') == '0'


def test_unknown_variable_is_not_a_value():
    with pytest.raises(IntegrationError):
        read_convar(SimpleNamespace(run=lambda command: '[SM] Unable to find cvar: "test_value"'), 'test_value')


def test_quoted_live_value_is_not_silently_truncated():
    with pytest.raises(IntegrationError):
        read_convar(SimpleNamespace(run=lambda command: '[SM] Value of cvar "test_value": "hello "world""'), 'test_value')


@pytest.mark.parametrize('operation', ['runtime', 'apply'])
def test_offline_batch_stops_retrying_the_same_connection_failure(tmp_path, operation):
    plugins = tmp_path / 'plugins'; plugins.mkdir()
    (plugins / 'demo.smx').write_bytes(b'FFPS')
    config = tmp_path / 'cfg' / 'sourcemod'; config.mkdir(parents=True)
    (config / 'demo.cfg').write_text('// Default: "1"\nfirst "1"\n// Default: "2"\nsecond "2"\n')
    calls = []

    def offline(command):
        calls.append(command)
        raise IntegrationError('RCON 连接失败: timed out')

    paths = SimpleNamespace(game=tmp_path, base=tmp_path, sm_plugins=plugins, sm_disabled=tmp_path / 'disabled')
    service = PluginConfigService(paths, SimpleNamespace(run=offline), SimpleNamespace(add=lambda *args: None))
    if operation == 'runtime':
        result = service.runtime('demo.smx', 'demo.cfg', ['first', 'second'])['values']
    else:
        doc = service.read('demo.smx', 'demo.cfg')
        result = service.update('admin', 'demo.smx', 'demo.cfg', doc['revision'], {'first': '3', 'second': '4'}, 'apply')['applied']
    assert len(calls) == 1
    assert len(result) == 2 and all(item['value'] is None and item['error'] for item in result)
