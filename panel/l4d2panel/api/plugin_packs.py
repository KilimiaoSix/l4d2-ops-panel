from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict

from ..context import AppContext
from ..deps import current_account, get_ctx

router = APIRouter()


class PackInstallIn(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    packs: list[str] = ['minimal']
    stop_game: bool = False


class PackRecoverIn(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    stop_game: bool = False


@router.get('/api/plugin-packs')
def pack_status(response: Response, probe: bool = False, ctx: AppContext = Depends(get_ctx), account: dict = Depends(current_account)):
    response.headers['Cache-Control'] = 'no-store'
    return ctx.plugin_packs.status(probe)


@router.post('/api/plugin-packs/install')
def pack_install(body: PackInstallIn, ctx: AppContext = Depends(get_ctx), account: dict = Depends(current_account)):
    return ctx.plugin_packs.start(body.packs, body.stop_game, account['username'])


@router.post('/api/plugin-packs/recover')
def pack_recover(body: PackRecoverIn, ctx: AppContext = Depends(get_ctx), account: dict = Depends(current_account)):
    return ctx.plugin_packs.recover(body.stop_game, account['username'])


@router.post('/api/plugin-packs/cancel')
def pack_cancel(ctx: AppContext = Depends(get_ctx), account: dict = Depends(current_account)):
    return ctx.plugin_packs.cancel(account['username'])
