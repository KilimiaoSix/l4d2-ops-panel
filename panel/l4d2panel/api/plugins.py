from typing import Literal

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
