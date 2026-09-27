from typing import Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict

from ..context import AppContext
from ..deps import current_account, get_ctx

router = APIRouter()


class BasicSettingsIn(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    revision: str
    mode: Literal['save', 'apply', 'save_apply'] = 'save_apply'
    server_name: str | None = None
    ascii_fallback: str | None = None
    password: str | None = None
    region: int | None = None
    coop_players: int | None = None


class RuntimeIn(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    names: list[str]


@router.get('/api/basic-settings')
def read(response: Response, ctx: AppContext = Depends(get_ctx), account: dict = Depends(current_account)):
    response.headers['Cache-Control'] = 'no-store'
    return ctx.basic_settings.read()


@router.post('/api/basic-settings')
def update(body: BasicSettingsIn, response: Response, ctx: AppContext = Depends(get_ctx), account: dict = Depends(current_account)):
    response.headers['Cache-Control'] = 'no-store'
    values = body.model_dump(exclude_unset=True, exclude={'revision', 'mode'})
    return ctx.basic_settings.update(body.revision, body.mode, values, account['username'])


@router.post('/api/basic-settings/runtime')
def runtime(body: RuntimeIn, response: Response, ctx: AppContext = Depends(get_ctx), account: dict = Depends(current_account)):
    response.headers['Cache-Control'] = 'no-store'
    return ctx.basic_settings.runtime(body.names)


@router.post('/api/basic-settings/recover')
def recover(ctx: AppContext = Depends(get_ctx), account: dict = Depends(current_account)):
    return ctx.basic_settings.recover(account['username'])
