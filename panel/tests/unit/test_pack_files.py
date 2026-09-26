import json
import os
from pathlib import Path

import pytest

from l4d2panel.integrations.pack_files import PackError, PackFiles, digest, json_bytes
from l4d2panel.jobs import Job


@pytest.fixture
def pack_files(tmp_path):
    game = tmp_path / 'game'; game.mkdir()
    return PackFiles(game, tmp_path / 'state')


def payload(tmp_path, name='addons/sourcemod/plugins/test.smx', data=b'FFPS-new', policy='managed'):
    root = tmp_path / 'payload'; source = root / name
    source.parent.mkdir(parents=True, exist_ok=True); source.write_bytes(data)
    return {'path': name, 'source': source, 'sha256': digest(data), 'policy': policy, 'pack': 'minimal'}


def test_commit_receipt_is_durable_read_only_and_preserves_data(pack_files, tmp_path):
    f = pack_files
    protected = ['addons/sourcemod/configs/admins_simple.ini', 'addons/sourcemod/configs/whitelist.txt',
                 'addons/sourcemod/data/panel_hostname.txt', 'addons/sourcemod/data/l4dinfectedbots/coop.cfg',
                 'cfg/sourcemod/custom.cfg']
    rows = [payload(tmp_path)]
    for name in protected:
        path = f.game / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b'custom user data')
        rows.append(payload(tmp_path, name, b'default', 'seed'))
    job = Job('test', 'packs')
    receipt = f.install(rows, {'minimal': {'version': '1'}}, job)
    assert receipt['packs']['minimal']['version'] == '1' and job.done == job.total == 6
    assert all((f.game / name).read_bytes() == b'custom user data' for name in protected)
    before = {p: p.stat().st_mtime_ns for p in f.state.rglob('*') if p.is_file()}
    assert f.pending() is None and f.receipt() == receipt
    assert before == {p: p.stat().st_mtime_ns for p in f.state.rglob('*') if p.is_file()}
    f.install(rows, {'minimal': {'version': '1'}})
    assert (f.game / rows[0]['path']).read_bytes() == b'FFPS-new'


@pytest.mark.parametrize('stage,index', [('prepared', 0), ('file', 0), ('file', 1), ('receipt', 0)])
def test_every_commit_phase_rolls_back_own_bytes(pack_files, tmp_path, stage, index):
    f = pack_files; old = payload(tmp_path, data=b'FFPS-old')
    f.install([old], {'minimal': {'version': 'old'}})
    receipt = f.receipt_path.read_bytes()
    rows = [payload(tmp_path), payload(tmp_path, 'cfg/new.cfg', b'cvar 1\n', 'seed')]
    def fail(where, n):
        if (where, n) == (stage, index): raise OSError('injected disk failure')
    with pytest.raises(OSError, match='disk failure'): f.install(rows, {'minimal': {'version': 'new'}}, checkpoint=fail)
    assert (f.game / old['path']).read_bytes() == b'FFPS-old'
    assert not (f.game / 'cfg/new.cfg').exists()
    assert f.receipt_path.read_bytes() == receipt and f.pending() is None


def test_crash_recovery_external_edits_and_backup_validation(pack_files, tmp_path):
    f = pack_files; old = payload(tmp_path, data=b'old'); f.install([old], {'minimal': {'version': 'old'}})
    row = payload(tmp_path)
    def crash(stage, index):
        if stage == 'file': raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt): f.install([row], {'minimal': {'version': 'new'}}, checkpoint=crash)
    assert f.pending()['phase'] == 'applying'
    target = f.game / row['path']; target.write_bytes(b'external')
    with pytest.raises(PackError, match='外部修改'): f.recover()
    assert target.read_bytes() == b'external' and f.pending()['phase'] == 'incomplete'
    target.write_bytes(b'FFPS-new')
    journal = f.pending(); backup = f.state / 'transactions' / journal['id'] / '0.old'
    backup.write_bytes(b'bad backup')
    with pytest.raises(PackError, match='备份校验失败'): f.recover()
    backup.write_bytes(b'old')
    assert f.recover() and target.read_bytes() == b'old'
    assert not f.recover()


def test_cancellation_before_and_during_commit(pack_files, tmp_path):
    f = pack_files; rows = [payload(tmp_path), payload(tmp_path, 'cfg/new.cfg', b'test 1', 'seed')]
    job = Job('test', 'packs'); job.cancel = True
    with pytest.raises(PackError, match='取消'): f.install(rows, {}, job)
    assert not list(f.game.rglob('*')) and not f.journal_path.exists()
    job.cancel = False
    def cancel(stage, index):
        if stage == 'file': job.cancel = True
    with pytest.raises(PackError, match='取消'): f.install(rows, {}, job, checkpoint=cancel)
    assert not [p for p in f.game.rglob('*') if p.is_file()] and not f.receipt_path.exists()


@pytest.mark.parametrize('name', ['../escape', '/cfg/a', 'cfg/../escape', 'cfg//a', 'cfg/a:b', 'addons\\evil', 'server.cfg'])
def test_unsafe_paths_rejected_without_mutation(pack_files, tmp_path, name):
    row = payload(tmp_path); row['path'] = name
    with pytest.raises(PackError): pack_files.install([row], {})
    assert not pack_files.state.exists() and not list(pack_files.game.iterdir())


def test_hash_ascii_existing_foreign_and_link_rejection(pack_files, tmp_path):
    f = pack_files; row = payload(tmp_path)
    row['sha256'] = '0' * 64
    with pytest.raises(PackError, match='校验'): f.install([row], {})
    with pytest.raises(PackError, match='ASCII'): f.install([payload(tmp_path, 'cfg/test.cfg', '中文'.encode())], {})
    row = payload(tmp_path); target = f.game / row['path']; target.parent.mkdir(parents=True); target.write_bytes(b'foreign')
    with pytest.raises(PackError, match='非托管'): f.install([row], {})
    target.unlink(); outside = tmp_path / 'outside'; outside.write_bytes(b'FFPS-new')
    target.symlink_to(outside)
    with pytest.raises(PackError, match='不安全'): f.install([row], {})
    target.unlink(); os.link(outside, target)
    with pytest.raises(PackError, match='硬链接'): f.install([row], {})
    assert outside.read_bytes() == b'FFPS-new'


def test_preflight_commit_race_preserves_external_change(pack_files, tmp_path):
    f = pack_files; row = payload(tmp_path)
    def race(stage, index):
        if stage == 'prepared':
            target = f.game / row['path']; target.parent.mkdir(parents=True); target.write_bytes(b'external')
    with pytest.raises(PackError, match='已变化'): f.install([row], {}, checkpoint=race)
    assert (f.game / row['path']).read_bytes() == b'external' and f.pending()


def test_receipt_game_ownership_checked(pack_files):
    f = pack_files; f.state.mkdir()
    f.receipt_path.write_bytes(json_bytes({'schema': 1, 'game_dir': '/another/game'}))
    with pytest.raises(PackError, match='归属'): f.receipt()


def test_compiler_executable_mode_is_explicit_and_limited(pack_files, tmp_path):
    row = payload(tmp_path, 'addons/sourcemod/scripting/spcomp64', b'compiler')
    row['mode'] = 0o755
    pack_files.install([row], {'minimal': {'version': '1'}})
    assert (pack_files.game / row['path']).stat().st_mode & 0o777 == 0o755
    row = payload(tmp_path); row['mode'] = 0o777
    with pytest.raises(PackError, match='权限'): pack_files.install([row], {})
