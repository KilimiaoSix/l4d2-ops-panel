import json
import shutil
import zipfile
from pathlib import Path

import pytest

from l4d2panel.integrations.pack_files import PackError, digest, json_bytes
from l4d2panel.integrations.pack_registry import PackRegistry

ROOT = Path(__file__).resolve().parents[2] / 'packs'


@pytest.fixture
def registry(tmp_path):
    shutil.copy(ROOT / 'manifest.json', tmp_path / 'manifest.json')
    return PackRegistry(tmp_path)


def test_single_manifest_real_dependencies_and_default(registry):
    assert registry.resolve(['minimal']) == ['minimal']
    assert registry.resolve(['multiplayer']) == ['minimal', 'left4dhooks', 'l4dtoolz', 'multiplayer']
    assert 'spawn-fixes' in registry.resolve(['infected'])
    assert registry.manifest['profiles']['minimal'] == ['minimal']
    with pytest.raises(PackError, match='未知'): registry.resolve(['https://arbitrary.example/file'])
    registry.packs['minimal']['requires'] = ['multiplayer']
    with pytest.raises(PackError, match='循环'): registry.resolve(['minimal'])


def test_missing_conflicting_and_unavailable_payloads(registry):
    registry.packs['multiplayer']['conflicts'] = ['infected']
    with pytest.raises(PackError, match='冲突'): registry.resolve(['multiplayer', 'infected'])
    with pytest.raises(PackError, match='缺少已验证载荷'): registry.files(['minimal'])
    data = registry.manifest; data['packs'][0]['requires'] = ['missing']
    (registry.root / 'manifest.json').write_bytes(json_bytes(data))
    with pytest.raises(PackError, match='缺少依赖'): PackRegistry(registry.root)


def test_normalized_payload_and_symlink_validation(registry, tmp_path):
    path = 'addons/sourcemod/plugins/example.smx'; root = registry.root / 'payloads/minimal'
    file = root / path; file.parent.mkdir(parents=True); file.write_bytes(b'FFPS-test')
    index = {'schema': 1, 'payloads': {'minimal': {'version': '1', 'files': [{'path': path, 'sha256': digest(file.read_bytes()), 'policy': 'managed'}]}}}
    (registry.root / 'payload-manifest.json').write_bytes(json_bytes(index))
    result = registry.files(['minimal']); assert result[0]['source'] == file
    outside = tmp_path / 'other'; outside.write_bytes(file.read_bytes()); file.unlink(); file.symlink_to(outside)
    with pytest.raises(PackError, match='不安全'): registry.files(['minimal'])


def test_official_download_uses_fixed_hash_and_does_not_extract_other_files(registry, tmp_path):
    directory = tmp_path / 'download'; directory.mkdir()
    archive = directory / 'official.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('l4dtoolz.so', b'ELF-test'); z.writestr('l4dtoolz.vdf', b'Plugin'); z.writestr('unused.dll', b'not linux')
    registry.manifest['official_downloads']['l4dtoolz']['sha256'] = digest(archive.read_bytes())
    files = registry._download('l4dtoolz', directory, None)
    assert len(files) == 2 and not (directory / 'unused.dll').exists()
    with zipfile.ZipFile(archive, 'w') as z: z.writestr('../unsafe', b'bad')
    registry.manifest['official_downloads']['l4dtoolz']['sha256'] = digest(archive.read_bytes())
    with pytest.raises(PackError, match='不安全'): registry._download('l4dtoolz', directory, None)
