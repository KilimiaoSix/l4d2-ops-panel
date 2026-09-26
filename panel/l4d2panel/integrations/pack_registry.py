"""One release manifest for dependency resolution and normalized plugin payloads."""
import json
import re
import stat
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .pack_files import PackError, atomic_write, digest, relative_path, safe_file

ID = re.compile(r'^[a-z0-9][a-z0-9_-]{0,63}$')
HASH = re.compile(r'^[0-9a-f]{64}$')


class PackDefinition(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    id: str
    name: str
    summary: str
    version: str
    required: bool
    default: bool
    visible: bool
    requires: list[str]
    conflicts: list[str]
    payload: str
    provides: list[str]
    probes: list[str]
    upstreams: list[str]
    compile_upstreams: list[str] = Field(default_factory=list)


class OfficialDownload(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    url: str
    sha256: str
    max_bytes: int
    files: dict[str, str]


class PackManifest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    schema_version: Literal[1] = Field(alias='schema')
    architecture: Literal['linux-x86_64-host-x86-game']
    profiles: dict[str, list[str]]
    packs: list[PackDefinition]
    official_downloads: dict[str, OfficialDownload] = Field(default_factory=dict)


class PackRegistry:
    def __init__(self, root):
        self.root = Path(root)
        try:
            self.manifest = PackManifest.model_validate(json.loads((self.root / 'manifest.json').read_text(encoding='utf-8'))).model_dump(by_alias=True)
        except ValidationError as error: raise PackError('插件注册表不符合 schema 1') from error
        m = self.manifest
        if m.get('schema') != 1 or m.get('architecture') != 'linux-x86_64-host-x86-game':
            raise PackError('不支持的插件注册表版本或架构')
        self.packs = {}
        for pack in m['packs']:
            name = pack['id']
            if not ID.fullmatch(name) or name in self.packs or not ID.fullmatch(pack['payload']):
                raise PackError('插件注册表有重复或无效的 ID')
            self.packs[name] = pack
        for pack in self.packs.values():
            if any(n not in self.packs for n in pack['requires'] + pack['conflicts']):
                raise PackError('插件注册表缺少依赖或冲突对象')
        self.resolve(list(self.packs), check_conflicts=False)
        for selection in m['profiles'].values(): self.resolve(selection)
        for name, download in m.get('official_downloads', {}).items():
            if name not in self.packs or not HASH.fullmatch(download['sha256']): raise PackError('无效的官方下载定义')
            if not download['url'].startswith('https://github.com/lakwsh/l4dtoolz/releases/download/2.5.1/'):
                raise PackError('未经允许的运行时下载源')
            if not 1 <= download['max_bytes'] <= 20 * 1024 * 1024: raise PackError('下载大小限制无效')
            for source, target in download['files'].items():
                if PurePosixPath(source).name != source or '\\' in source: raise PackError('下载文件映射无效')
                relative_path(target)

    def resolve(self, selection, check_conflicts=True):
        if not isinstance(selection, list) or not selection: raise PackError('请选择插件包')
        seen, visiting, result = set(), set(), []
        def visit(name):
            if name not in self.packs: raise PackError(f'未知插件包：{name}')
            if name in visiting: raise PackError('插件依赖存在循环')
            if name in seen: return
            visiting.add(name)
            for dependency in self.packs[name]['requires']: visit(dependency)
            visiting.remove(name); seen.add(name); result.append(name)
        for name, pack in self.packs.items():
            if pack['required']: visit(name)
        for name in selection: visit(name)
        if check_conflicts:
            for name in result:
                if seen.intersection(self.packs[name]['conflicts']): raise PackError(f'插件包冲突：{name}')
        return result

    def payload_index(self):
        path = self.root / 'payload-manifest.json'
        if not path.is_file(): return {}
        value = json.loads(path.read_text(encoding='utf-8'))
        if value.get('schema') != 1: raise PackError('载荷清单版本无效')
        for name, payload in value['payloads'].items():
            if not ID.fullmatch(name) or not isinstance(payload.get('version'), str): raise PackError('无效的载荷定义')
            for item in payload['files']:
                relative_path(item['path'])
                if not HASH.fullmatch(item['sha256']) or item['policy'] not in ('seed', 'managed'):
                    raise PackError('无效的载荷文件策略或哈希')
        return value['payloads']

    def files(self, selection, download_dir=None, job=None):
        index = self.payload_index(); files = []
        for name in self.resolve(selection):
            pack = self.packs[name]; payload = pack['payload']
            if name in self.manifest.get('official_downloads', {}):
                if download_dir is None: raise PackError(f'{pack["name"]} 需要在安装任务中下载')
                files.extend(self._download(name, Path(download_dir) / name, job))
                continue
            if payload not in index: raise PackError(f'发布物缺少已验证载荷：{pack["name"]}')
            if index[payload]['version'] != pack['version']: raise PackError(f'载荷版本不匹配：{name}')
            root = self.root / 'payloads' / payload
            if (self.root / 'payloads').is_symlink() or root.is_symlink(): raise PackError('载荷目录不能使用链接')
            entries = index[payload]['files']
            if not entries: raise PackError(f'空的插件载荷：{name}')
            for item in entries:
                if not HASH.fullmatch(item['sha256']): raise PackError('载荷哈希无效')
                source = safe_file(root, item['path'])
                files.append({**item, 'source': source, 'pack': name})
        return files

    def _download(self, name, directory, job):
        info = self.manifest['official_downloads'][name]
        archive = directory / 'official.zip'
        if directory.is_symlink() or archive.is_symlink(): raise PackError('下载目录不能使用链接')
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not archive.exists() or digest(archive.read_bytes()) != info['sha256']:
            if job: job.msg = f'正在下载官方 {self.packs[name]["name"]}…'
            request = urllib.request.Request(info['url'], headers={'User-Agent': 'l4d2-ops-panel'})
            data = bytearray()
            with urllib.request.urlopen(request, timeout=45) as response:
                if not response.url.startswith('https://'): raise PackError('官方下载被降级为非 HTTPS')
                while chunk := response.read(65536):
                    if job and job.cancel: raise PackError('安装已取消，未更改游戏文件')
                    data.extend(chunk)
                    if len(data) > info['max_bytes']: raise PackError('官方下载超过大小限制')
            if digest(data) != info['sha256']: raise PackError('官方下载 SHA256 校验失败')
            atomic_write(archive, data)
        files = []
        with zipfile.ZipFile(archive) as source:
            names = set()
            for member in source.infolist():
                if member.filename in names: raise PackError('官方压缩包含重复文件')
                names.add(member.filename)
                path = PurePosixPath(member.filename)
                if path.is_absolute() or '..' in path.parts or '\\' in member.filename or ':' in member.filename:
                    raise PackError('官方压缩包路径不安全')
                mode = member.external_attr >> 16
                if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) and not (stat.S_ISREG(mode) or stat.S_ISDIR(mode))):
                    raise PackError('官方压缩包含链接或特殊文件')
                if member.file_size > info['max_bytes']: raise PackError('官方文件超过大小限制')
            for src, target in info['files'].items():
                if src not in names: raise PackError('官方压缩包缺少固定映射文件')
                data = source.read(src); destination = safe_file(directory, target)
                atomic_write(destination, data, 0o644)
                files.append({'path': target, 'source': destination, 'sha256': digest(data), 'policy': 'managed', 'pack': name})
        return files
