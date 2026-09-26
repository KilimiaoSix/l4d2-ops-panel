from pathlib import Path

import pytest

from l4d2panel.integrations.basic_config import BasicConfig, SERVER, HOSTNAME, MULTISLOTS, CAPACITY
from l4d2panel.integrations.game_mode_config import ModeConfig
from l4d2panel.integrations.hostname_file import canonical_name, read_name, parse_name_receipt
from l4d2panel.integrations.pack_files import PackError, PackFiles, digest


@pytest.fixture
def config(tmp_path):
    game = tmp_path / 'game'; (game / 'cfg').mkdir(parents=True)
    (game / SERVER).write_bytes('// 中文注释\nmp_gamemode coop\nhostname "original"\nsv_password "secret"\n'.encode())
    return BasicConfig(game, tmp_path / 'basic_state')


def test_multi_file_save_clear_password_and_no_secret_readback(config):
    first = config.read(); assert first['password_set'] and not config.state.exists()
    result = config.save(first['revision'], {'server_name': '中文开服', 'password': '', 'region': 4, 'coop_players': 8}, multiplayer=True)
    read = config.read()
    assert read['server_name'] == '中文开服' and not read['password_set'] and read['region'] == 4 and read['coop_players'] == 8
    assert read['revision'] == result['revision'] and read['hostname_file']
    assert 'secret' not in str(read) + str(result)
    assert (config.game / HOSTNAME).read_bytes() == '中文开服\n'.encode()
    server = (config.game / SERVER).read_bytes()
    assert server.startswith('// 中文注释\n'.encode()) and b'hostname "L4D2 Server"' in server
    assert b'l4d_multislots_max_survivors "8"' in (config.game / MULTISLOTS).read_bytes()
    assert b'panel_capacity 31' in (config.game / CAPACITY).read_bytes()
    config.save(read['revision'], {'password': 'new secret'})
    assert config.read()['password_set']
    assert not config.save(config.read()['revision'], {'password': 'new secret'})['changed']


@pytest.mark.parametrize('stage,index', [('prepared', 0), ('file', 0), ('file', 1), ('file', 2), ('file', 3), ('receipt', 0)])
def test_each_basic_save_failure_restores_all_original_files(config, stage, index):
    original = (config.game / SERVER).read_bytes()
    revision = config.read()['revision']
    def fail(current, i):
        if (current, i) == (stage, index): raise OSError('injected write failure')
    with pytest.raises(OSError):
        config.save(revision, {'server_name': 'new name', 'region': 4, 'coop_players': 12}, multiplayer=True, checkpoint=fail)
    assert (config.game / SERVER).read_bytes() == original
    assert all(not (config.game / name).exists() for name in (HOSTNAME, MULTISLOTS, CAPACITY))
    assert config.read()['revision'] == revision and not config.transaction.pending()


def test_mode_change_invalidates_revision_without_overwriting_new_mode(config):
    old = config.read()['revision']
    ModeConfig(config.game / SERVER).save('versus')
    with pytest.raises(PackError, match='变化'): config.save(old, {'region': 4})
    assert ModeConfig(config.game / SERVER).read() == 'versus'
    assert not (config.game / HOSTNAME).exists()


def test_interrupted_save_requires_explicit_recovery_and_respects_external_edit(config):
    original = (config.game / SERVER).read_bytes()
    def crash(stage, index):
        if stage == 'file': raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt): config.save(config.read()['revision'], {'server_name': 'saved'}, checkpoint=crash)
    assert config.read()['pending']
    (config.game / HOSTNAME).write_bytes(b'externally changed\n')
    with pytest.raises(PackError, match='外部修改'): config.recover()
    assert (config.game / HOSTNAME).read_bytes() == b'externally changed\n'
    assert (config.game / SERVER).read_bytes() == original


def test_pack_api_cannot_opt_itself_into_configuration_edits(config, tmp_path):
    source = tmp_path / 'source'; source.write_bytes(b'changed')
    row = {'path': SERVER, 'source': source, 'sha256': digest(source.read_bytes()),
           'policy': 'edit', 'pack': 'basic', 'expected': digest((config.game / SERVER).read_bytes())}
    with pytest.raises(PackError, match='策略'): PackFiles(config.game, tmp_path / 'packs').plan([row])
    row['path'] = 'addons/another.txt'; row['expected'] = None
    with pytest.raises(PackError, match='策略'): config.transaction.plan([row])


def test_basic_config_rejects_linked_secret_and_state(config, tmp_path):
    outside = tmp_path / 'outside'; outside.mkdir()
    config.state.symlink_to(outside, target_is_directory=True)
    with pytest.raises(PackError): config.save(config.read()['revision'], {'region': 4})
    assert list(outside.iterdir()) == []
    (config.game / SERVER).unlink(); (config.game / SERVER).symlink_to(outside / 'config')
    with pytest.raises(PackError): config.read()


def test_hostname_canonical_bytes_and_exact_receipt():
    assert canonical_name('  cafe\u0301  ') == 'café'
    assert read_name('中文\n'.encode()) == '中文'
    for value in ('', '中' * 33, 'bad;quit', 'bad\nname', 'bad\u202ename'):
        with pytest.raises(ValueError): canonical_name(value)
    with pytest.raises(ValueError): read_name(b'\xff')
    with pytest.raises(ValueError): read_name(b'name\n\n')
    raw = '中文'.encode().hex()
    assert parse_name_receipt(f'PANEL_HOSTNAME expected={raw} actual={raw} state=ok')['actual'] == '中文'
    assert parse_name_receipt('PANEL_HOSTNAME expected=ff actual=ff state=ok') is None


def test_saving_name_with_unchanged_count_does_not_require_another_restart(config):
    first = config.save(config.read()['revision'], {'coop_players': 8}, multiplayer=True)
    assert first['capacity_changed']
    second = config.save(config.read()['revision'], {'coop_players': 8, 'server_name': 'updated'}, multiplayer=True)
    assert second['changed'] and not second['capacity_changed']


def test_basic_mode_and_damage_serialize_without_lost_updates(config):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    from l4d2panel.integrations.sm_files import persist_cvars

    prepared, release = threading.Event(), threading.Event()
    mode_started, damage_started = threading.Event(), threading.Event()
    def checkpoint(stage, index):
        if stage == 'prepared':
            prepared.set()
            assert release.wait(5)
    def mode():
        mode_started.set()
        return ModeConfig(config.game / SERVER).save('versus')
    def damage():
        damage_started.set()
        persist_cvars(config.game / SERVER, [('survivor_friendly_fire_factor_expert', '0.3')])
    with ThreadPoolExecutor(max_workers=3) as pool:
        saving = pool.submit(config.save, config.read()['revision'], {'server_name': 'concurrent', 'region': 4}, checkpoint=checkpoint)
        try:
            assert prepared.wait(5)
            changing_mode, changing_damage = pool.submit(mode), pool.submit(damage)
            assert mode_started.wait(5) and damage_started.wait(5)
            assert not changing_mode.done() and not changing_damage.done()
        finally: release.set()
        saving.result(); changing_mode.result(); changing_damage.result()
    data = (config.game / SERVER).read_bytes()
    assert b'concurrent' in data and config.read()['region'] == 4
    assert b'survivor_friendly_fire_factor_expert 0.3' in data
    assert ModeConfig(config.game / SERVER).read() == 'versus'
    assert config.read()['server_name'] == 'concurrent'
