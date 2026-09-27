"""Opt-in test of actual final-tar payloads: minimal install, expansion, preservation.

python -m tests.pack_release_smoke ../dist/l4d2-panel-linux-x86_64.tar.gz
Does not run the game engine; it verifies release file installation and recovery.
"""
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile

from l4d2panel.integrations.pack_files import PackFiles, digest, json_bytes
from l4d2panel.integrations.pack_registry import PackRegistry
from l4d2panel.jobs import Job


def main():
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location('release_builder', root / 'tools/release/build.py')
    builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)
    archive = Path(sys.argv[1]).resolve()
    directory = Path(tempfile.mkdtemp(prefix='l4d2-pack-smoke-', dir='/var/tmp'))
    stage = directory / 'release'; stage.mkdir()
    for name, data in builder.tar_members(archive).items():
        target = stage / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(data)
    builder.validate_release(stage)
    registry = PackRegistry(stage / 'panel/packs')
    game = directory / 'game'; game.mkdir()
    transaction = PackFiles(game, directory / 'state')
    checks = []
    def check(name, value):
        assert value, name
        checks.append(name); print('PASS ' + name, flush=True)
    custom = {'addons/sourcemod/configs/admins_simple.ini': b'"STEAM_1:0:123" "99:z"\n',
              'addons/sourcemod/configs/whitelist.txt': b'// existing whitelist\n',
              'addons/sourcemod/data/panel_hostname.txt': '中文测试服\n'.encode(),
              'addons/sourcemod/data/l4dinfectedbots/coop.cfg': b'// custom IB data\n',
              'cfg/sourcemod/l4d2_points_system.cfg': b'l4d2_points_start "42"\n'}
    for name, data in custom.items():
        target = game / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(data)
    minimal = registry.files(['minimal']); job = Job('minimal', 'packs')
    transaction.install(minimal, {'minimal': {'version': registry.packs['minimal']['version']}}, job)
    check('minimal file progress and receipt', job.done == job.total == len(minimal) and set(transaction.receipt()['packs']) == {'minimal'})
    check('complete SourceMod addons and cfg installed', (game / 'addons/sourcemod/bin/sourcemod.2.l4d2.so').is_file() and (game / 'cfg/sourcemod/sourcemod.cfg').is_file())
    check('hostname and whitelist are real compiled plugins', all((game / ('addons/sourcemod/plugins/' + n + '.smx')).read_bytes()[:4] == b'FFPS' for n in ('panel_hostname', 'sm_whitelist', 'sipreset')))
    check('minimal does not install multiplayer or points', not (game / 'addons/l4dtoolz.so').exists() and not (game / 'addons/sourcemod/plugins/l4d2_points_system.smx').exists())
    downloads = directory / 'downloads'; pinned = downloads / 'l4dtoolz/official.zip'; pinned.parent.mkdir(parents=True)
    official = root / '.release-cache/l4dtoolz-2.5.1-main.zip'
    if official.exists(): shutil.copyfile(official, pinned)
    full = registry.files(registry.manifest['profiles']['full'], downloads, job)
    resolved = registry.resolve(registry.manifest['profiles']['full'])
    transaction.install(full, {name: {'version': registry.packs[name]['version']} for name in resolved}, job)
    check('expand minimal to full dependency closure', set(transaction.receipt()['packs']) == set(resolved))
    check('all declared files validated with uniform file counts', job.done == job.total == len(full))
    check('custom admins whitelist hostname IB and plugin settings preserved', all((game / name).read_bytes() == data for name, data in custom.items()))
    check('official L4DToolZ hash matches pinned release', digest(pinned.read_bytes()) == registry.manifest['official_downloads']['l4dtoolz']['sha256'])
    check('official-download binary absent from release tar', not any(p.name == 'l4dtoolz.so' for p in stage.rglob('*')))
    check('all transaction files are present', all((game / f['path']).is_file() for f in full))
    check('successful transaction has no recovery pending', transaction.pending() is None)
    result = {'checks': checks, 'passed': len(checks), 'archive_sha256': digest(archive.read_bytes()),
              'minimal_files': len(minimal), 'full_files': len(full), 'kind': 'actual release payload files; no game engine/client verification'}
    (directory / 'results.json').write_bytes(json_bytes(result))
    print('Evidence: ' + str(directory), flush=True)


if __name__ == '__main__': main()
