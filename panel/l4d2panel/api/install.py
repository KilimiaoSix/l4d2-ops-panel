from typing import Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field

from ..context import AppContext
from ..deps import current_account, get_ctx

router = APIRouter()


class InstallIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    game_port: int = Field(default=27015, ge=1, le=65535)
    tick: Literal[30, 60, 100, 128] = 30
    vac: bool = False
    mirror_url: str = 'docker.cnb.cool'


@router.get('/api/install')
def install_status(response: Response, ctx: AppContext = Depends(get_ctx), account: dict = Depends(current_account)):
    response.headers['Cache-Control'] = 'no-store'
    return ctx.game_install.status()


@router.post('/api/install')
def install(body: InstallIn, ctx: AppContext = Depends(get_ctx), account: dict = Depends(current_account)):
    return {'ok': True, 'id': ctx.game_install.start(body.model_dump(exclude_unset=True), account['username'])}


@router.post('/api/install/cancel')
def cancel_install(ctx: AppContext = Depends(get_ctx), account: dict = Depends(current_account)):
    ctx.game_install.cancel(account['username'])
    return {'ok': True}
