"""Plugin parameter workflows over real HTTP, files, SQLite and fake RCON."""
import json
import re

import pytest


CONFIG = '''// ConVars for plugin "myplugin.smx"
// Spawn interval
// Default: "10"
// Minimum: "0"
// Maximum: "60"
test_interval "10" // keep this note

// Welcome message
// Default: "hello"
test_message "hello"
'''


@pytest.fixture
def cfg(game_dir, fake_game):
    directory = game_dir.root / 'cfg' / 'sourcemod'
    directory.mkdir()
    path = directory / 'custom-settings.cfg'
    path.write_text(CONFIG)
    fake_game.state['cvars'].update(test_interval='15', test_message='live message')
    original = fake_game.reply

    def reply(cmd):
        match = re.fullmatch(r'sm_cvar (test_\w+)(?: "([^"\n]*)")?', cmd)
        if match:
            name, value = match.groups()
            if value is not None:
                fake_game.state['cvars'][name] = value
                return ''  # RCON set can return no useful confirmation; must read back.
            return f'[SM] Value of cvar "{name}": "{fake_game.state["cvars"][name]}"'
        return original(cmd)

    fake_game.reply = reply
    return path


def document(api):
    response = api.get('/api/plugin-config', params={'plugin': 'myplugin.smx', 'file': 'custom-settings.cfg'})
    assert response.status_code == 200, response.text
    return response.json()


def change(api, doc, updates, mode='save'):
    return api.post('/api/plugin-config', json={
        'plugin': 'myplugin.smx', 'file': doc['file'], 'revision': doc['revision'], 'updates': updates, 'mode': mode,
    })


def test_discovery_and_saved_values_do_not_claim_to_be_live(api, cfg, fake_game):
    response = api.get('/api/plugin-configs', params={'plugin': 'myplugin.smx'})
    assert response.status_code == 200, response.text
    assert response.json()['files'] == [{'name': cfg.name, 'source': 'header'}]
    doc = document(api)
    interval = doc['parameters'][0]
    assert interval['value'] == '10' and interval['default'] == '10'
    assert interval['min'] == '0' and interval['max'] == '60' and interval['editable']
    assert not any(command.startswith('sm_cvar test_') for command in fake_game.commands)
    r = api.post('/api/plugin-config/runtime', json={'plugin': 'myplugin.smx', 'file': cfg.name, 'names': ['test_interval', 'test_message']})
    assert r.status_code == 200, r.text
    assert r.json()['values'] == [
        {'name': 'test_interval', 'value': '15', 'error': None},
        {'name': 'test_message', 'value': 'live message', 'error': None},
    ]


def test_save_is_persistent_revision_guarded_and_restorable(api, cfg, fake_game, panel):
    doc = document(api)
    r = change(api, doc, {'test_interval': '0', 'test_message': ''})
    assert r.status_code == 200, r.text
    result = r.json()
    assert result['saved'] and result['backup_id'] and result['applied'] == []
    assert result['document']['revision'] != doc['revision']
    assert 'test_interval "0" // keep this note' in cfg.read_text()
    assert 'test_message ""' in cfg.read_text()
    assert fake_game.state['cvars']['test_interval'] == '15'
    assert change(api, doc, {'test_interval': '20'}).status_code == 409
    restore = api.post('/api/plugin-config/restore', json={
        'plugin': 'myplugin.smx', 'file': cfg.name, 'revision': result['document']['revision'], 'backup_id': result['backup_id'],
    })
    assert restore.status_code == 200, restore.text
    assert restore.json()['saved'] and restore.json()['applied'] == []
    assert cfg.read_text() == CONFIG
    actions = panel.audit_actions()
    assert ('admin', 'plugin.config.save') in actions
    assert ('admin', 'plugin.config.restore') in actions


def test_apply_and_save_apply_report_verified_values(api, cfg, fake_game, panel):
    doc = document(api)
    r = change(api, doc, {'test_interval': '20'}, 'apply')
    assert r.status_code == 200, r.text
    assert r.json()['saved'] is False and r.json()['document']['revision'] == doc['revision']
    assert cfg.read_text() == CONFIG
    assert r.json()['applied'] == [{'name': 'test_interval', 'requested': '20', 'value': '20', 'status': 'applied', 'error': None}]
    assert fake_game.commands[-2:] == ['sm_cvar test_interval "20"', 'sm_cvar test_interval']
    r = change(api, doc, {'test_message': 'new message'}, 'save_apply')
    assert r.status_code == 200, r.text
    assert r.json()['saved'] and r.json()['applied'][0]['status'] == 'applied'
    assert 'test_message "new message"' in cfg.read_text()
    assert ('admin', 'plugin.config.apply') in panel.audit_actions()


def test_saved_file_survives_offline_apply_with_explicit_failure(api, cfg, fake_game):
    doc = document(api)
    fake_game.stop()
    r = change(api, doc, {'test_interval': '20'}, 'save_apply')
    assert r.status_code == 200, r.text
    assert r.json()['saved'] is True
    assert r.json()['applied'][0]['status'] == 'error'
    assert r.json()['applied'][0]['value'] is None
    assert 'test_interval "20"' in cfg.read_text()


def test_game_adjusting_a_value_is_not_reported_as_requested_success(api, cfg, fake_game):
    original = fake_game.reply

    def clamp(cmd):
        reply = original(cmd)
        if cmd.startswith('sm_cvar test_interval "'):
            fake_game.state['cvars']['test_interval'] = '12'
        return reply

    fake_game.reply = clamp
    r = change(api, document(api), {'test_interval': '20'}, 'apply')
    assert r.status_code == 200, r.text
    assert r.json()['applied'][0]['status'] == 'adjusted'
    assert r.json()['applied'][0]['value'] == '12'


@pytest.mark.parametrize('updates', [
    {'test_interval': '61'}, {'test_interval': 'nan'}, {'test_interval': '-1'},
    {'test_message': 'ok"; quit'}, {'test_message': 'one\ntwo'}, {'rcon_password': 'other'},
])
def test_invalid_edits_do_not_write_files_or_send_commands(api, cfg, fake_game, updates):
    doc = document(api)
    before = list(fake_game.commands)
    assert change(api, doc, updates, 'save_apply').status_code == 400
    assert cfg.read_text() == CONFIG and fake_game.commands == before


def test_auth_and_file_plugin_binding(api, panel, cfg, game_dir):
    anon = panel.client()
    assert anon.get('/api/plugin-configs', params={'plugin': 'myplugin.smx'}).status_code == 401
    for plugin, file in [('myplugin.smx', '../server.cfg'), ('oldplugin.smx', cfg.name), ('../myplugin.smx', cfg.name)]:
        assert api.get('/api/plugin-config', params={'plugin': plugin, 'file': file}).status_code in (400, 404)
    assert api.get('/api/plugin-configs', params={'plugin': 'ghost.smx'}).status_code == 404
    other = cfg.parent / 'other.cfg'
    other.write_text(CONFIG.replace('myplugin.smx', 'oldplugin.smx'))
    assert api.get('/api/plugin-config', params={'plugin': 'myplugin.smx', 'file': other.name}).status_code == 404


def test_disabled_plugin_can_save_but_cannot_apply(api, cfg, game_dir, fake_game):
    (game_dir.plugins / 'myplugin.smx').rename(game_dir.disabled / 'myplugin.smx')
    doc = document(api)
    assert change(api, doc, {'test_interval': '20'}, 'apply').status_code == 400
    assert change(api, doc, {'test_interval': '20'}, 'save_apply').status_code == 400
    assert cfg.read_text() == CONFIG
    assert change(api, doc, {'test_interval': '20'}).status_code == 200


def test_runtime_failure_is_unknown_not_zero(api, cfg, fake_game):
    original = fake_game.reply
    fake_game.reply = lambda cmd: 'Unknown command "sm_cvar"' if cmd.startswith('sm_cvar test_') else original(cmd)
    r = api.post('/api/plugin-config/runtime', json={'plugin': 'myplugin.smx', 'file': cfg.name, 'names': ['test_interval']})
    assert r.status_code == 200, r.text
    assert r.json()['values'][0]['value'] is None and r.json()['values'][0]['error']


def test_empty_batches_and_unrecognized_runtime_names_are_rejected(api, cfg):
    doc = document(api)
    assert change(api, doc, {}).status_code == 400
    r = api.post('/api/plugin-config/runtime', json={'plugin': 'myplugin.smx', 'file': cfg.name, 'names': ['rcon_password']})
    assert r.status_code == 400


def test_long_parameter_changes_keep_complete_audit_values(api, cfg, panel):
    before, after = 'a' * 254, 'b' * 254
    cfg.write_text(CONFIG.replace('test_message "hello"', f'test_message "{before}"'))
    response = change(api, document(api), {'test_message': after})
    assert response.status_code == 200, response.text
    record = next(row for row in panel.audit() if row['action'] == 'plugin.config.save')
    detail = json.loads(record['detail'])
    assert detail['before'] == before and detail['after'] == after
