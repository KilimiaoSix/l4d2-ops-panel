#!/usr/bin/env python3
"""Build fixed, normalized plugin payloads, then a secrets-free Linux release.

Run on Linux: python3 tools/release/build.py --version <version> [--payloads-only].
Missing pins/payloads fail a complete release. No latest URLs or host deployment files.
"""
import argparse
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'panel'))
from l4d2panel.integrations.pack_files import PackError, digest, json_bytes, relative_path
from l4d2panel.integrations.pack_registry import PackRegistry


def fetch(pin, cache):
    path = cache / pin['cache']
    if not path.is_file() or digest(path.read_bytes()) != pin['sha256']:
        if not pin['url'].startswith('https://'): raise PackError('HTTPS upstream required')
        temp = path.with_suffix(path.suffix + '.part')
        with urllib.request.urlopen(pin['url'], timeout=60) as response, temp.open('wb') as output:
            shutil.copyfileobj(response, output)
        if digest(temp.read_bytes()) != pin['sha256']:
            temp.unlink(); raise PackError('Upstream hash mismatch: ' + pin['cache'])
        os.replace(temp, path)
    return path


def tar_members(path, prefixes=None):
    """Never call extractall: validate every member and return regular file bytes."""
    result = {}; total = 0; seen = set()
    with tarfile.open(path, 'r:*') as archive:
        for member in archive:
            name = member.name.removeprefix('./')
            parts = PurePosixPath(name).parts
            if name.startswith('/') or '..' in parts or '\\' in name or ':' in name or name in seen:
                raise PackError('Unsafe/duplicate upstream archive path: ' + name)
            seen.add(name)
            if member.isdir(): continue
            if not member.isfile(): raise PackError('Archive link or special file: ' + name)
            if prefixes and not any('/' + prefix in '/' + name for prefix in prefixes): continue
            total += member.size
            if member.size > 128 * 1024 * 1024 or total > 1024 * 1024 * 1024:
                raise PackError('Archive expands beyond build limit')
            result[name] = archive.extractfile(member).read()
    return result


def strip_root(members):
    roots = {p.split('/')[0] for p in members}
    if len(roots) != 1: raise PackError('Expected one source archive root')
    return {p.split('/', 1)[1]: data for p, data in members.items() if '/' in p}


def file_policy(name):
    return 'seed' if name.startswith(('cfg/', 'addons/sourcemod/configs/', 'addons/sourcemod/data/', 'addons/sourcemod/logs/')) else 'managed'


def normalize_cfg(name, data):
    if name.startswith('cfg/') and name.lower().endswith('.cfg') and not data.isascii():
        lines = data.decode('utf-8-sig').splitlines(keepends=True)
        # SourceMod's engine config comments must also be ASCII on this engine.
        for i, line in enumerate(lines):
            if not line.isascii():
                if not line.lstrip().startswith('//'): raise PackError('Non-ASCII engine directive: ' + name)
                lines[i] = line.encode('ascii', 'backslashreplace').decode('ascii')
        return ''.join(lines).encode('ascii')
    return data


def put(files, name, data):
    relative_path(name); data = normalize_cfg(name, data)
    if name.endswith('.smx') and not data.startswith(b'FFPS'): raise PackError('Invalid SMX: ' + name)
    if name.endswith('.so') and (data[:4] != b'\x7fELF' or data[4] not in (1, 2) or int.from_bytes(data[18:20], 'little') not in (3, 62)):
        raise PackError('Expected x86/x86_64 ELF: ' + name)
    if name in files and files[name] != data: raise PackError('Payload path collision: ' + name)
    files[name] = data


def compile_plugin(compiler, includes, source, destination, extra=()):
    compiler.chmod(0o755)
    result = subprocess.run([str(compiler), str(source), '-i' + str(includes), *('-i' + str(p) for p in extra),
                             '-o' + str(destination)], capture_output=True, text=True)
    if result.returncode: raise PackError(f'Plugin compile failed: {source.name}\n{result.stdout}\n{result.stderr}')
    data = destination.read_bytes()
    if not data.startswith(b'FFPS'): raise PackError('Compiler did not produce a SourceMod binary')
    print(f'Compiled {source.name}', flush=True)
    return data


def build_payloads(cache, output, selected=None):
    pins = json.loads((ROOT / 'tools/release/upstreams.json').read_text())['upstreams']
    registry = PackRegistry(ROOT / 'panel/packs')
    chosen = registry.resolve(selected or ['minimal'])
    archives = {}; payloads = {name: {} for name in chosen if name not in registry.manifest['official_downloads']}
    output.mkdir(parents=True, exist_ok=True); (output / 'licenses').mkdir(exist_ok=True)
    for name in {u for p in chosen for u in registry.packs[p]['upstreams'] + registry.packs[p].get('compile_upstreams', []) if u != 'panel'}:
        if name not in pins: raise PackError('Missing pinned upstream: ' + name)
        pin = pins[name]
        if pin['distribution'] == 'official-download': continue
        path = fetch(pin, cache)
        prefixes = ['LICENSE', 'l4dmultislots/', 'l4d_CreateSurvivorBot/', 'l4dinfectedbots/', 'spawn_infected_nolimit/'] if name == 'harry-plugins' else None
        archives[name] = tar_members(path, prefixes)
        if name not in ('metamod', 'sourcemod', 'sourcescramble'): archives[name] = strip_root(archives[name])
        license_text = next((v for k, v in archives[name].items() if k in ('LICENSE', 'LICENSE.txt', 'addons/sourcemod/LICENSE.txt')), None)
        if license_text is None:
            license_pin = pin.get('license_artifact')
            if not license_pin: raise PackError('Missing pinned license artifact: ' + name)
            license_text = fetch(license_pin, cache).read_bytes()
        (output / 'licenses' / (name + '.txt')).write_bytes(license_text)
    for name in ('metamod', 'sourcemod'):
        for path, data in archives[name].items():
            # SourceMod ships Nextmap enabled, but it explicitly fails on L4D2.
            if path == 'addons/sourcemod/plugins/nextmap.smx':
                path = 'addons/sourcemod/plugins/disabled/nextmap.smx'
            if path.startswith(('addons/', 'cfg/')): put(payloads['minimal'], path, data)
    for directory in ('addons/sourcemod/data', 'addons/sourcemod/logs'):
        put(payloads['minimal'], directory + '/.panel-keep', b'')
    with tempfile.TemporaryDirectory(prefix='l4d2-release-') as work:
        work = Path(work); sm = work / 'sm'
        for name, data in archives['sourcemod'].items():
            target = sm / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(data)
        compiler = sm / 'addons/sourcemod/scripting/spcomp64'; includes = compiler.parent / 'include'
        for plugin in ('panel_hostname', 'panel_join_password', 'sipreset', 'sm_whitelist'):
            source = ROOT / 'sourcemod/scripting' / (plugin + '.sp')
            compiled = compile_plugin(compiler, includes, source, work / (source.stem + '.smx'))
            put(payloads['minimal'], 'addons/sourcemod/plugins/' + source.stem + '.smx', compiled)
            put(payloads['minimal'], 'addons/sourcemod/scripting/' + source.name, source.read_bytes())
        if 'left4dhooks' in payloads:
            for path, data in archives['left4dhooks'].items():
                if path.startswith('sourcemod/'): put(payloads['left4dhooks'], 'addons/' + path, data)
                if path.startswith('sourcemod/scripting/include/'):
                    (includes / Path(path).name).write_bytes(data)
            prefix = 'addons/sourcemod/scripting/include/'
            for path, data in archives['multicolors'].items():
                if path.startswith(prefix):
                    target = includes / path[len(prefix):]; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(data)
                    put(payloads['left4dhooks'], path, data)
        # Additional fixed upstream mappings are declared below as they are validated.
        if 'multiplayer' in payloads:
            put(payloads['multiplayer'], 'cfg/panel-capacity.cfg',
                b'// Panel startup profile, not executed as engine CFG.\npanel_capacity 31\n')
            for prefix in ('l4dmultislots/', 'l4d_CreateSurvivorBot/'):
                for path, data in archives['harry-plugins'].items():
                    if path.startswith(prefix):
                        relative = path[len(prefix):]
                        if relative.startswith(('plugins/', 'scripting/', 'gamedata/', 'translations/')):
                            put(payloads['multiplayer'], 'addons/sourcemod/' + relative, data)
            # Compile dependency includes first, then both pinned plugin sources.
            for path, data in payloads['multiplayer'].items():
                if path.startswith('addons/sourcemod/scripting/include/'):
                    (includes / Path(path).name).write_bytes(data)
            for path, data in list(payloads['multiplayer'].items()):
                if path.endswith('.sp'):
                    src = work / Path(path).name; src.write_bytes(data)
                    payloads['multiplayer']['addons/sourcemod/plugins/' + src.stem + '.smx'] = compile_plugin(compiler, includes, src, work / (src.stem + '.smx'))
        if 'points' in payloads:
            prefix = 'l4d2_points_system/'
            point_files = {p[len(prefix):]: data for p, data in archives['umlka'].items() if p.startswith(prefix)}
            source_text = point_files['l4d2_points_system.sp'].decode('utf-8')
            anchor = 'CreateNative("PS_IsSystemEnabled", Native_PS_IsSystemEnabled);'
            if source_text.count(anchor) != 1: raise PackError('Points patch anchor changed')
            source_text = source_text.replace(anchor, anchor + '\n\tCreateNative("PS_GetDataLoadState", Native_PS_GetDataLoadState);')
            cfg_anchor = '//AutoExecConfig(true);'
            if source_text.count(cfg_anchor) != 1: raise PackError('Points config patch anchor changed')
            source_text = source_text.replace(cfg_anchor, 'AutoExecConfig(true, "l4d2_points_system");')
            source_text += '''\n// l4d2-ops-panel patch: exact async SQL readiness for the map-reset helper.
public int Native_PS_GetDataLoadState(Handle plugin, int count) {
    int client = GetNativeCell(1);
    if (client < 1 || client > MaxClients) return ThrowNativeError(SP_ERROR_NATIVE, "Invalid client");
    return g_ePlayer[client].DatabaseLoaded;
}
'''
            point_files['l4d2_points_system.sp'] = source_text.encode('utf-8')
            point_files['ps_natives.inc'] += b'\n// Panel map-reset readiness (added by l4d2-ops-panel).\nnative bool PS_GetDataLoadState(int client);\n'
            (includes / 'ps_natives.inc').write_bytes(point_files['ps_natives.inc'])
            source = work / 'l4d2_points_system.sp'; source.write_bytes(point_files['l4d2_points_system.sp'])
            for path, data in point_files.items():
                if path.startswith('translations/'): put(payloads['points'], 'addons/sourcemod/' + path, data)
                elif path.endswith(('.sp', '.inc')):
                    put(payloads['points'], 'addons/sourcemod/scripting/' + ('include/' if path.endswith('.inc') else '') + path, data)
            for src in (source, ROOT / 'sourcemod/scripting/ps_mapreset.sp'):
                put(payloads['points'], 'addons/sourcemod/plugins/' + src.stem + '.smx',
                    compile_plugin(compiler, includes, src, work / (src.stem + '.smx')))
                put(payloads['points'], 'addons/sourcemod/scripting/' + src.name, src.read_bytes())
            # Load the shipped seed configuration on every map; AutoExecConfig
            # preserves a user's existing file instead of regenerating its values.
            defaults = re.findall(r'CreateConVar\("(l4d2_points_\w+)"\s*,\s*"([^"]*)"', source_text)
            put(payloads['points'], 'cfg/sourcemod/l4d2_points_system.cfg',
                ('// Pinned Points System 1.9.3 defaults.\n' + ''.join(f'{n} "{v}"\n' for n, v in defaults)).encode('ascii'))
            (output / 'licenses/points-panel-patch.txt').write_text('Points System 1.9.3: added PS_GetDataLoadState native and include declaration for the bundled ps_mapreset helper; enabled AutoExecConfig for l4d2_points_system.cfg so saved configuration survives restarts. Modified source is in addons/sourcemod/scripting/.\n', encoding='utf-8')
        if 'spawn-fixes' in payloads:
            for path, data in archives['moyu'].items():
                if path == 'include/@Forgetest/gamedatawrapper.inc':
                    target = includes / path[len('include/'):]; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(data)
                    put(payloads['spawn-fixes'], 'addons/sourcemod/scripting/' + path, data)
            for path, data in archives['sourcescramble'].items():
                if path.startswith('addons/sourcemod/extensions/') or path.startswith('addons/sourcemod/scripting/'):
                    put(payloads['spawn-fixes'], path, data)
                if path.startswith('addons/sourcemod/scripting/include/'): (includes / Path(path).name).write_bytes(data)
            mappings = [('umlka', 'zombie_spawn_fix/zombie_spawn_fix.sp', 'scripting/zombie_spawn_fix.sp'),
                        ('umlka', 'zombie_spawn_fix/zombie_spawn_fix.txt', 'gamedata/zombie_spawn_fix.txt')]
            moyu = 'The Last Stand/l4d_unrestrict_panic_battlefield/'
            mappings.extend(('moyu', p, p[len(moyu):]) for p in archives['moyu'] if p.startswith(moyu) and p.endswith(('.sp', '.txt')))
            for origin, path, target in mappings:
                data = archives[origin][path]; put(payloads['spawn-fixes'], 'addons/sourcemod/' + target, data)
                if target.endswith('.sp'):
                    source = work / Path(target).name; source.write_bytes(data)
                    put(payloads['spawn-fixes'], 'addons/sourcemod/plugins/' + source.stem + '.smx',
                        compile_plugin(compiler, includes, source, work / (source.stem + '.smx')))
            prefix = 'spawn_infected_nolimit/'
            for path, data in archives['harry-plugins'].items():
                if path.startswith(prefix) and path[len(prefix):].startswith(('plugins/', 'scripting/', 'gamedata/', 'translations/')):
                    put(payloads['spawn-fixes'], 'addons/sourcemod/' + path[len(prefix):], data)
            for path, data in payloads['spawn-fixes'].items():
                if path.startswith('addons/sourcemod/scripting/include/'):
                    target = includes / path[len('addons/sourcemod/scripting/include/'):]
                    target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(data)
            source = work / 'spawn_infected_nolimit.sp'
            source.write_bytes(payloads['spawn-fixes']['addons/sourcemod/scripting/spawn_infected_nolimit.sp'])
            payloads['spawn-fixes']['addons/sourcemod/plugins/spawn_infected_nolimit.smx'] = compile_plugin(compiler, includes, source, work / 'spawn_infected_nolimit.smx')
        if 'infected' in payloads:
            prefix = 'l4dinfectedbots/'
            for path, data in archives['harry-plugins'].items():
                if path.startswith(prefix) and path[len(prefix):].startswith(('plugins/', 'scripting/', 'gamedata/', 'translations/', 'data/')):
                    put(payloads['infected'], 'addons/sourcemod/' + path[len(prefix):], data)
            ib = work / 'l4dinfectedbots'; ib.mkdir()
            prefix = 'addons/sourcemod/data/l4dinfectedbots/'
            for path, data in payloads['infected'].items():
                if path.startswith(prefix):
                    target = ib / path[len(prefix):]; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(data)
            subprocess.run([sys.executable, str(ROOT / 'tools/gen_ib_presets.py'), str(ib)], check=True)
            for path in ib.rglob('*'):
                if path.is_file(): payloads['infected'][prefix + path.relative_to(ib).as_posix()] = path.read_bytes()
            source = work / 'l4dinfectedbots.sp'; source.write_bytes(payloads['infected']['addons/sourcemod/scripting/l4dinfectedbots.sp'])
            payloads['infected']['addons/sourcemod/plugins/l4dinfectedbots.smx'] = compile_plugin(compiler, includes, source, work / 'l4dinfectedbots.smx')
    # Empty optional packs cannot be disguised as complete release output.
    index = {'schema': 1, 'payloads': {}}
    for name, files in payloads.items():
        if not files: raise PackError('Payload implementation incomplete: ' + name)
        directory = output / 'payloads' / registry.packs[name]['payload']
        if directory.exists():
            # Build directory only; never operate on an installation's game tree.
            if not directory.resolve().is_relative_to(output.resolve()) or directory.is_symlink(): raise PackError('Unsafe build target')
            shutil.rmtree(directory)
        entries = []
        for path, data in sorted(files.items()):
            target = directory / path; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(data)
            target.chmod(0o755 if target.name in ('spcomp', 'spcomp64') else 0o644)
            entries.append({'path': path, 'sha256': digest(data), 'policy': file_policy(path),
                            'mode': 0o755 if target.name in ('spcomp', 'spcomp64') else 0o644})
        index['payloads'][registry.packs[name]['payload']] = {'version': registry.packs[name]['version'], 'files': entries}
    if (ROOT / 'panel/packs/manifest.json').resolve() != (output / 'manifest.json').resolve():
        shutil.copyfile(ROOT / 'panel/packs/manifest.json', output / 'manifest.json')
        shutil.copyfile(ROOT / 'panel/packs/manifest.schema.json', output / 'manifest.schema.json')
    (output / 'payload-manifest.json').write_bytes(json_bytes(index))
    (output / 'licenses/upstreams.json').write_bytes(json_bytes(pins))
    shutil.copyfile(ROOT / 'LICENSE', output / 'licenses/panel.txt')
    print('Payload files:', sum(len(p['files']) for p in index['payloads'].values()), flush=True)
    return index


def archive_release(stage, target):
    """Stable metadata; timestamps in source files do not influence archive bytes."""
    with target.open('wb') as stream, gzip.GzipFile(filename='', mode='wb', fileobj=stream, mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode='w') as archive:
            for path in sorted(stage.rglob('*')):
                if path.is_symlink(): raise PackError('Release cannot contain links')
                if path.is_dir(): continue
                info = archive.gettarinfo(str(path), arcname=path.relative_to(stage).as_posix())
                if not info.isfile(): raise PackError('Release cannot contain special files')
                info.mtime = 0; info.uid = info.gid = 0; info.uname = info.gname = ''
                info.mode = 0o755 if path.name in ('spcomp', 'spcomp64', 'get.sh') else 0o644
                with path.open('rb') as source: archive.addfile(info, source)


def validate_release(stage):
    panel = stage / 'panel'
    forbidden = {'panel.json', 'panel.db', 'venv', 'devenv', '.git', 'node_modules', '__pycache__',
                 'downloads', 'workshop_tmp', 'pack_state', 'basic_state', 'docker', 'config_backups'}
    for path in stage.rglob('*'):
        relative = path.relative_to(stage)
        if (any(p in forbidden for p in relative.parts) or path.name.endswith(('.pem', '.pyc', '.sqlite', '.db-wal', '.db-shm'))
                or path.is_symlink()): raise PackError('Private or mutable file in release: ' + str(relative))
    for name in ('VERSION', 'panel/panel.py', 'panel/requirements.txt', 'panel/constraints.txt',
                 'panel/l4d2panel/static/index.html', 'panel/packs/payload-manifest.json',
                 'tools/bootstrap/install.py', 'tools/bootstrap/recover.py', 'tools/bootstrap/network.py'):
        if not (stage / name).is_file(): raise PackError('Release missing: ' + name)
    registry = PackRegistry(panel / 'packs')
    for name in registry.resolve(registry.manifest['profiles']['full']):
        if name in registry.manifest['official_downloads']:
            if (panel / 'packs/payloads' / name).exists(): raise PackError('Official-download-only payload was bundled')
            continue
        # Iterate bundled dependencies without triggering an official network download.
        index = registry.payload_index()[registry.packs[name]['payload']]
        for item in index['files']:
            source = panel / 'packs/payloads' / registry.packs[name]['payload'] / item['path']
            if digest(source.read_bytes()) != item['sha256']: raise PackError('Release payload hash mismatch')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--version', required=True)
    parser.add_argument('--payloads-only', action='store_true')
    parser.add_argument('--skip-frontend-build', action='store_true', help='Use the already verified local SPA; CI does not use this option')
    parser.add_argument('--packs', nargs='+')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}', args.version): parser.error('Invalid release version')
    cache = ROOT / '.release-cache'; cache.mkdir(exist_ok=True)
    if args.payloads_only:
        build_payloads(cache, ROOT / 'panel/packs', args.packs)
        return
    registry = PackRegistry(ROOT / 'panel/packs')
    with tempfile.TemporaryDirectory(prefix='l4d2-release-stage-') as directory:
        stage = Path(directory); panel = stage / 'panel'; panel.mkdir()
        build_payloads(cache, panel / 'packs', registry.manifest['profiles']['full'])
        if not args.skip_frontend_build:
            subprocess.run(['npm', 'ci'], cwd=ROOT / 'frontend', check=True)
            subprocess.run(['npm', 'run', 'build'], cwd=ROOT / 'frontend', check=True)
        static = ROOT / 'panel/l4d2panel/static'
        if not (static / 'index.html').is_file() or not list((static / 'assets').glob('*.js')):
            raise PackError('Release requires the built SPA')
        shutil.copytree(ROOT / 'panel/l4d2panel', panel / 'l4d2panel', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        for name in ('panel.py', 'requirements.txt', 'constraints.txt', 'install.sh', 'panel.example.json', 'nginx.example.conf'):
            shutil.copyfile(ROOT / 'panel' / name, panel / name)
        shutil.copytree(ROOT / 'tools/bootstrap', stage / 'tools/bootstrap', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        (stage / 'VERSION').write_text(args.version + '\n')
        (panel / 'l4d2panel/_build_version.py').write_text('__version__ = ' + repr(args.version) + '\n')
        validate_release(stage)
        dist = ROOT / 'dist'; dist.mkdir(exist_ok=True)
        asset = dist / 'l4d2-panel-linux-x86_64.tar.gz'; archive_release(stage, asset)
        (dist / 'SHA256SUMS').write_text(digest(asset.read_bytes()) + '  ' + asset.name + '\n')
        print(asset)


if __name__ == '__main__': main()
