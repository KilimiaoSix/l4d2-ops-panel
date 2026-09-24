import glob
from concurrent.futures import ThreadPoolExecutor, TimeoutError
import threading

from l4d2panel.integrations.game_mode_config import ModeConfig

from l4d2panel.integrations.sm_files import (ADM_BEGIN, ADM_END, list_smx, persist_cvars, read_rcon_password,
                                             read_whitelist, write_admins_block)


def test_persist_cvars_replaces_or_appends_and_keeps_bytes(tmp_path):
    cfg = tmp_path / 'server.cfg'
    cfg.write_bytes(b'hostname "caf\xe9"\nsm_cvar a_factor 0.1\n  b_factor  0.5 // note\nsv_x 1\n')   # a latin-1 byte the engine may well have there
    persist_cvars(cfg, [('a_factor', '0.3'), ('b_factor', '1'), ('c_factor', '0')])
    text = cfg.read_bytes()
    assert b'sm_cvar a_factor 0.3\n' in text and b'a_factor 0.1' not in text
    assert b'sm_cvar b_factor 1\n' in text and b'0.5 // note' not in text            # prefix-less line replaced too
    assert text.endswith(b'sv_x 1\nsm_cvar c_factor 0\n') and b'caf\xe9' in text     # appended, other bytes untouched
    backups = glob.glob(str(cfg) + '.bak-panel-*')
    assert len(backups) == 1 and open(backups[0], 'rb').read().startswith(b'hostname "caf\xe9"')


def test_admins_block_created_replaced_and_legacy_marker(tmp_path):
    ini = tmp_path / 'admins_simple.ini'
    write_admins_block(ini, [(1, 'admin', 'STEAM_1:0:1', '99:z')])
    assert ini.read_text() == f'{ADM_BEGIN}\n"STEAM_1:0:1" "99:z"    // panel#1 admin\n{ADM_END}\n'
    ini.write_text('"STEAM_1:0:9" "99:z" // hand made\n\n; ==== panel-managed BEGIN old ====\n"STEAM_1:0:1" "z"\n; ==== panel-managed END ====\n')
    write_admins_block(ini, [(2, 'bob 桐', 'STEAM_1:0:2', ''), (3, 'c', 'STEAM_1:1:3', 'abc')])
    text = ini.read_text()
    assert text.startswith('"STEAM_1:0:9" "99:z" // hand made\n') and text.count('panel-managed BEGIN') == 1 and '; ====' not in text
    assert '"STEAM_1:0:2" "99:z"    // panel#2 bob ?' in text and '"STEAM_1:1:3" "abc"    // panel#3 c' in text   # non-ASCII in comments is masked
    write_admins_block(ini, [])
    assert ini.read_text().rstrip().endswith(f'{ADM_BEGIN}\n{ADM_END}')


def test_small_readers(tmp_path):
    wl = tmp_path / 'whitelist.txt'; wl.write_text('STEAM_1:0:1 // a\n// c\n\n  \nSTEAM_1:0:2\n')
    assert read_whitelist(wl) == ['STEAM_1:0:1 // a', 'STEAM_1:0:2'] and read_whitelist(tmp_path / 'nope') == []
    cfg = tmp_path / 'server.cfg'; cfg.write_text('sv_x 1\nrcon_password "s3cret"\n')
    assert read_rcon_password(cfg) == 's3cret' and read_rcon_password(tmp_path / 'nope') == ''
    (tmp_path / 'b.smx').write_bytes(b'x'); (tmp_path / 'a.smx').write_bytes(b'x'); (tmp_path / 'c.txt').write_bytes(b'x')
    assert list_smx(tmp_path) == ['a.smx', 'b.smx'] and list_smx(tmp_path / 'nope') == []


def test_damage_and_mode_concurrent_saves_preserve_both_updates(tmp_path, monkeypatch):
    from l4d2panel.integrations import sm_files

    cfg = tmp_path / 'server.cfg'
    cfg.write_bytes(b'sm_cvar mp_gamemode "coop"\nsm_cvar a_factor 0.1\n')
    damage_read = threading.Event()
    release_damage = threading.Event()
    mode_started = threading.Event()
    original_copy = sm_files.shutil.copy

    def pause_after_read(*args, **kwargs):
        damage_read.set()
        assert release_damage.wait(5)
        return original_copy(*args, **kwargs)

    def save_mode():
        mode_started.set()
        return ModeConfig(cfg).save('versus')

    monkeypatch.setattr(sm_files.shutil, 'copy', pause_after_read)
    with ThreadPoolExecutor(2) as pool:
        damage = pool.submit(persist_cvars, cfg, [('a_factor', '0.3')])
        try:
            assert damage_read.wait(5)
            mode = pool.submit(save_mode)
            assert mode_started.wait(5)
            try:
                mode.result(timeout=0.2)
            except TimeoutError:
                pass
        finally:
            release_damage.set()
        damage.result(timeout=5)
        mode.result(timeout=5)

    assert ModeConfig(cfg).read() == 'versus'
    assert b'sm_cvar a_factor 0.3\n' in cfg.read_bytes()
