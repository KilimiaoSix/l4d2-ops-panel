from fastapi import APIRouter, BackgroundTasks, Depends, Response
from pydantic import BaseModel, ConfigDict, Field

from ..context import AppContext
from ..deps import get_ctx, require_owner

router = APIRouter()


class ConfigIn(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    revision: str = Field(pattern=r'^[a-f0-9]{64}$')
    updates: dict
    restart: bool = False


@router.get('/api/panel-config')
def get_config(response: Response, ctx: AppContext = Depends(get_ctx), owner: dict = Depends(require_owner)):
    response.headers['Cache-Control'] = 'no-store'
    return ctx.panel_config.get()


@router.post('/api/panel-config')
def save_config(body: ConfigIn, tasks: BackgroundTasks, response: Response,
                ctx: AppContext = Depends(get_ctx), owner: dict = Depends(require_owner)):
    response.headers['Cache-Control'] = 'no-store'
    result = ctx.panel_config.save(body.revision, body.updates, body.restart, owner['username'])
    if result['restart_scheduled']: tasks.add_task(ctx.panel_config.restart.request_exit)
    return result
