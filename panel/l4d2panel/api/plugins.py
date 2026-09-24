from typing import Dict, List, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from ..context import AppContext
from ..deps import current_account, get_ctx
from .addons import stream_to_file

router = APIRouter()


class PluginsIn(BaseModel):
    op: Literal['reload', 'disable', 'enable', 'delete']
    file: str = ''


@router.get('/api/plugins')
def plugins(ctx: AppContext = Depends(get_ctx), account: dict = Depends(current_account)):
    return ctx.plugins.list()


@router.post('/api/plugins')
def plugins_op(body: PluginsIn, ctx: AppContext = Depends(get_ctx), account: dict = Depends(current_account)):
    return ctx.plugins.action(body.op, body.file, account['username'])


@router.post('/api/plugin_upload')
async def plugin_upload(request: Request, name: str = '', ctx: AppContext = Depends(get_ctx), account: dict = Depends(current_account)):
    nm, tmp = ctx.plugins.upload_target(name)
    n = int(request.headers.get('content-length', 0) or 0); ctx.plugins.check_upload_size(n)
    got = await stream_to_file(request, tmp)
    return ctx.plugins.finish_upload(nm, tmp, got, n, account['username'])


class ConfigTarget(BaseModel):
    plugin: str
    file: str


class ConfigRuntimeIn(ConfigTarget):
    names: List[str]


class ConfigUpdateIn(ConfigTarget):
    revision: str
    updates: Dict[str, str]
    mode: Literal['save', 'apply', 'save_apply'] = 'save'


class ConfigRestoreIn(ConfigTarget):
    revision: str
    backup_id: str


@router.get('/api/plugin-configs')
def plugin_configs(plugin: str, ctx: AppContext = Depends(get_ctx), account: dict = Depends(current_account)):
    return ctx.plugin_config.discover(plugin)


@router.get('/api/plugin-config')
def plugin_config(plugin: str, file: str, ctx: AppContext = Depends(get_ctx), account: dict = Depends(current_account)):
    return ctx.plugin_config.read(plugin, file)


@router.post('/api/plugin-config/runtime')
def plugin_config_runtime(body: ConfigRuntimeIn, ctx: AppContext = Depends(get_ctx), account: dict = Depends(current_account)):
    return ctx.plugin_config.runtime(body.plugin, body.file, body.names)


@router.post('/api/plugin-config')
def plugin_config_update(body: ConfigUpdateIn, ctx: AppContext = Depends(get_ctx), account: dict = Depends(current_account)):
    return ctx.plugin_config.update(account['username'], body.plugin, body.file, body.revision, body.updates, body.mode)


@router.post('/api/plugin-config/restore')
def plugin_config_restore(body: ConfigRestoreIn, ctx: AppContext = Depends(get_ctx), account: dict = Depends(current_account)):
    return ctx.plugin_config.restore(account['username'], body.plugin, body.file, body.revision, body.backup_id)
