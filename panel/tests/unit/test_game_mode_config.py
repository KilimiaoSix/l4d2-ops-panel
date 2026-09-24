import os
import stat

import pytest

from l4d2panel.integrations.game_mode_config import ModeConfig, ModeConfigError


@pytest.fixture
def config(tmp_path):
    path = tmp_path / 'server.cfg'
    path.write_bytes(b'mp_gamemode "coop"\n')
    return ModeConfig(path), path


def test_duplicate_modes_preserve_comments_bytes_crlf_and_permissions(config):
    files, path = config
    original = (b'// mp_gamemode "survival"\r\nhostname "caf\xe9"\r\n'
                b'  mp_gamemode   "coop"  // default\r\n'
                b'sm_cvar MP_GAMEMODE versus\r\nrcon_password "secret"\r\n')
    path.write_bytes(original)
    path.chmod(0o640)
    assert files.read() == 'versus'
    change = files.save('realism')
    assert change.changed and change.backup == os.path.basename(change.backup)
    assert path.read_bytes() == original.replace(b'  mp_gamemode', b'  sm_cvar mp_gamemode').replace(b'"coop"', b'"realism"').replace(b'versus', b'"realism"')
    backup = path.parent / change.backup
    assert backup.read_bytes() == original
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.stat().st_mode) == 0o640
    assert files.read() == 'realism'


@pytest.mark.parametrize('original,expected', [
    (b'', b'sm_cvar mp_gamemode "versus"\n'),
    (b'hostname "x"', b'hostname "x"\nsm_cvar mp_gamemode "versus"\n'),
    (b'// comment\r\n', b'// comment\r\nsm_cvar mp_gamemode "versus"\r\n'),
])
def test_append_when_absent(config, original, expected):
    files, path = config
    path.write_bytes(original)
    assert files.read() is None
    files.save('versus')
    assert path.read_bytes() == expected


def test_noop_has_no_backup(config):
    files, path = config
    path.write_bytes(b'sm_cvar mp_gamemode "coop"\n')
    change = files.save('coop')
    assert not change.changed and change.backup is None
    change.rollback()
    assert list(path.parent.iterdir()) == [path]


def test_bare_hidden_cvar_is_promoted_even_when_mode_is_unchanged(config):
    files, path = config
    path.write_bytes(b' \tmp_gamemode   coop // keep\r\n')
    change = files.save('coop')
    assert change.changed and change.backup
    assert path.read_bytes() == b' \tsm_cvar mp_gamemode   coop // keep\r\n'


def test_rollback_restores_exact_bytes_permissions_and_refuses_external_edit(config):
    files, path = config
    original = path.read_bytes()
    path.chmod(0o640)
    change = files.save('survival')
    change.rollback()
    assert path.read_bytes() == original
    assert stat.S_IMODE(path.stat().st_mode) == 0o640
    change = files.save('scavenge')
    path.write_bytes(b'// external change\n')
    with pytest.raises(ModeConfigError):
        change.rollback()
    assert path.read_bytes() == b'// external change\n'


@pytest.mark.parametrize('mode', ['invalid', 'coop;quit', '', None, ['coop']])
def test_invalid_mode_never_writes(config, mode):
    files, path = config
    with pytest.raises(ModeConfigError):
        files.save(mode)
    assert path.read_bytes() == b'mp_gamemode "coop"\n'
    assert list(path.parent.iterdir()) == [path]


@pytest.mark.parametrize('original', [
    b'mp_gamemode coop; quit\n', b'hostname x; mp_gamemode coop\n',
    b'/* mp_gamemode coop */\n', b'/*\nmp_gamemode coop\n*/\n',
    b'"mp_gamemode" "coop"\n', b'mp_gamemode "coop" extra\n',
])
def test_ambiguous_commands_are_rejected_without_changes(config, original):
    files, path = config
    path.write_bytes(original)
    with pytest.raises(ModeConfigError):
        files.save('versus')
    assert path.read_bytes() == original
    assert list(path.parent.iterdir()) == [path]


def test_exec_is_not_followed_and_comments_are_not_commands(config):
    files, path = config
    path.write_bytes(b'// mp_gamemode versus\nexec "other.cfg"\n')
    (path.parent / 'other.cfg').write_bytes(b'mp_gamemode versus\n')
    assert files.read() is None


def test_mode_name_in_unrelated_strings_and_comment_commands_are_preserved(config):
    files, path = config
    original = (b'hostname "mp_gamemode"\nsm_cvar hostname "mp_gamemode"\n'
                b'rcon_password "a;mp_gamemode"\n'
                b'mp_gamemode "coop" // keep; mp_gamemode versus\n')
    path.write_bytes(original)
    assert files.read() == 'coop'
    files.save('realism')
    assert path.read_bytes() == original.replace(b'\nmp_gamemode', b'\nsm_cvar mp_gamemode').replace(b'"coop"', b'"realism"')


def test_unique_backups_and_rollback_failure_preserve_saved_config(config, monkeypatch):
    files, path = config
    first = files.save('versus')
    second = files.save('realism')
    assert first.backup != second.backup
    def fail(*args):
        raise OSError('storage failure')
    monkeypatch.setattr('l4d2panel.integrations.game_mode_config.os.replace', fail)
    with pytest.raises(ModeConfigError):
        second.rollback()
    assert files.read() == 'realism'
    assert len(list(path.parent.iterdir())) == 3


def test_symlinks_missing_and_oversized_files_are_rejected(config):
    files, path = config
    target = path.parent / 'actual.cfg'
    path.rename(target)
    path.symlink_to(target)
    for action in (files.read, lambda: files.save('versus')):
        with pytest.raises(ModeConfigError):
            action()
    assert target.read_bytes() == b'mp_gamemode "coop"\n'
    path.unlink()
    with pytest.raises(ModeConfigError):
        files.read()
    path.write_bytes(b'x' * (1024 * 1024 + 1))
    with pytest.raises(ModeConfigError):
        files.save('versus')


@pytest.mark.parametrize('operation', ['replace', 'fsync'])
def test_write_failure_preserves_original_and_cleans_temporary_files(config, monkeypatch, operation):
    files, path = config
    def fail(*args, **kwargs):
        raise OSError('simulated storage failure')
    monkeypatch.setattr('l4d2panel.integrations.game_mode_config.os.' + operation, fail)
    with pytest.raises(ModeConfigError):
        files.save('versus')
    assert path.read_bytes() == b'mp_gamemode "coop"\n'
    assert list(path.parent.iterdir()) == [path]


def test_external_edit_during_preparation_is_not_overwritten(config, monkeypatch):
    files, path = config
    original_fsync = os.fsync
    def edit_then_sync(fd):
        path.write_bytes(b'// administrator changed file\n')
        original_fsync(fd)
    monkeypatch.setattr('l4d2panel.integrations.game_mode_config.os.fsync', edit_then_sync)
    with pytest.raises(ModeConfigError):
        files.save('versus')
    assert path.read_bytes() == b'// administrator changed file\n'
    assert list(path.parent.iterdir()) == [path]
