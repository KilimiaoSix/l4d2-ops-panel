from typing import Literal, Optional

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from ..context import AppContext
from ..deps import current_account, get_ctx
from ..game_modes import GameMode

router = APIRouter()


class RconIn(BaseModel):
    cmd: str = ''


class PresetIn(BaseModel):
    name: Literal['auto', 'te8', 'te12', 'te16']


class DifficultyIn(BaseModel):
    level: Literal['easy', 'normal', 'hard', 'impossible']


class GameModeIn(BaseModel):
    mode: GameMode


class DamageIn(BaseModel):
    ff: Optional[float] = None
    burn: Optional[float] = None


class MapIn(BaseModel):
    map: str


class ActionIn(BaseModel):
    name: Literal['start', 'stop', 'restart', 'monitor']


@router.post('/api/rcon')
def rcon(body: RconIn, ctx: AppContext = Depends(get_ctx), account: dict = Depends(current_account)):
    return {'out': ctx.game.run_command(body.cmd, account['username'])}


@router.post('/api/preset')
def preset(body: PresetIn, ctx: AppContext = Depends(get_ctx), account: dict = Depends(current_account)):
    return {'out': ctx.game.set_preset(body.name, account['username'])}


@router.post('/api/difficulty')
def difficulty(body: DifficultyIn, ctx: AppContext = Depends(get_ctx), account: dict = Depends(current_account)):
    return {'out': ctx.game.set_difficulty(body.level, account['username'])}


@router.get('/api/game-mode')
def game_mode(response: Response, ctx: AppContext = Depends(get_ctx), account: dict = Depends(current_account)):
    response.headers['Cache-Control'] = 'no-store'
    return ctx.game.modes.read()


@router.post('/api/game-mode')
def switch_game_mode(body: GameModeIn, ctx: AppContext = Depends(get_ctx), account: dict = Depends(current_account)):
    return ctx.game.modes.switch(body.mode.value, account['username'])


@router.post('/api/damage')
def damage(body: DamageIn, ctx: AppContext = Depends(get_ctx), account: dict = Depends(current_account)):
    out, persisted = ctx.game.set_damage(body.ff, body.burn, account['username'])
    return {'out': out, 'persisted': persisted}


@router.post('/api/map')
def change_map(body: MapIn, ctx: AppContext = Depends(get_ctx), account: dict = Depends(current_account)):
    return {'out': ctx.game.change_map(body.map, account['username'])}


@router.post('/api/action')
def action(body: ActionIn, ctx: AppContext = Depends(get_ctx), account: dict = Depends(current_account)):
    ok = ctx.server.run(body.name, account['username'])
    return {'ok': ok, 'running': ctx.server.state['running']}
