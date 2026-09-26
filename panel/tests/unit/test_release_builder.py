import importlib.util
import io
import os
import tarfile
from pathlib import Path

import pytest

from l4d2panel.integrations.pack_files import PackError

path = Path(__file__).resolve().parents[3] / 'tools/release/build.py'
spec = importlib.util.spec_from_file_location('release_builder', path)
builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)


@pytest.mark.parametrize('name,kind', [('../escape', tarfile.REGTYPE), ('/cfg/escape', tarfile.REGTYPE),
    ('cfg/evil', tarfile.SYMTYPE), ('cfg/hard', tarfile.LNKTYPE), ('cfg/device', tarfile.CHRTYPE), ('cfg\\escape', tarfile.REGTYPE)])
def test_release_unpack_rejects_links_devices_and_unsafe_paths(tmp_path, name, kind):
    file = tmp_path / 'unsafe.tar'
    with tarfile.open(file, 'w') as archive:
        member = tarfile.TarInfo(name); member.type = kind; member.linkname = 'outside'
        archive.addfile(member, io.BytesIO())
    with pytest.raises(PackError): builder.tar_members(file)
    assert not (tmp_path / 'escape').exists()


def test_stable_archive_metadata_and_compiler_executable_bit(tmp_path):
    root = tmp_path / 'stage'; root.mkdir()
    compiler = root / 'spcomp64'; compiler.write_bytes(b'compiler')
    (root / 'source.txt').write_text('source')
    a, b = tmp_path / 'a.tar.gz', tmp_path / 'b.tar.gz'
    builder.archive_release(root, a)
    os.utime(compiler, (1, 1)); builder.archive_release(root, b)
    assert a.read_bytes() == b.read_bytes()
    with tarfile.open(a) as archive:
        assert archive.getmember('spcomp64').mode == 0o755
        assert archive.getmember('source.txt').mode == 0o644
        assert all(m.uid == m.gid == m.mtime == 0 for m in archive)


def test_binary_architecture_ascii_policy_and_collision():
    files = {}
    builder.put(files, 'cfg/comment.cfg', '// 中文注释\nsv_region 4\n'.encode())
    assert files['cfg/comment.cfg'].isascii() and b'sv_region 4' in files['cfg/comment.cfg']
    with pytest.raises(PackError): builder.put(files, 'cfg/value.cfg', 'hostname "中文"'.encode())
    with pytest.raises(PackError): builder.put(files, 'addons/evil.so', b'not elf')
    with pytest.raises(PackError): builder.put(files, 'addons/plugin.smx', b'not smx')
    with pytest.raises(PackError): builder.put(files, 'cfg/comment.cfg', b'different')


@pytest.mark.parametrize('name', ['panel/panel.json', 'panel/panel.db', 'panel/key.pem', 'panel/pack_state/receipt.json', 'panel/basic_state/pending.json'])
def test_private_material_rejected_before_archiving(tmp_path, name):
    file = tmp_path / name; file.parent.mkdir(parents=True); file.write_text('private')
    with pytest.raises(PackError, match='Private or mutable'): builder.validate_release(tmp_path)
