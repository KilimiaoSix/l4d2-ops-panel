from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..context import AppContext
from ..deps import current_account, get_ctx

router = APIRouter()


class WhitelistIn(BaseModel):
    op: Literal['add', 'del']
    steamid: str = ''
    note: str = ''


class WhitelistEnableIn(BaseModel):
    enable: bool = False


class KickIn(BaseModel):
    userid: int
    reason: str = '由管理面板踢出'


class PointsIn(BaseModel):
    amount: int = 0
    target: str = '@all'


@router.get('/api/players')
def players(ctx: AppContext = Depends(get_ctx), account: dict = Depends(current_account)):
    rows, _, raw = ctx.game.players()
    return {'players': rows, 'raw': raw}


@router.get('/api/whitelist')
def whitelist(ctx: AppContext = Depends(get_ctx), account: dict = Depends(current_account)):
    return {'list': ctx.whitelist.list()}


@router.post('/api/whitelist')
def whitelist_edit(body: WhitelistIn, ctx: AppContext = Depends(get_ctx), account: dict = Depends(current_account)):
    out = ctx.whitelist.add(body.steamid, body.note, account['username']) if body.op == 'add' else ctx.whitelist.remove(body.steamid, account['username'])
    return {'out': out, 'list': ctx.whitelist.list()}


@router.post('/api/whitelist_enable')
def whitelist_enable(body: WhitelistEnableIn, ctx: AppContext = Depends(get_ctx), account: dict = Depends(current_account)):
    return {'out': ctx.whitelist.enable(body.enable, account['username'])}


@router.post('/api/kick')
def kick(body: KickIn, ctx: AppContext = Depends(get_ctx), account: dict = Depends(current_account)):
    return {'out': ctx.game.kick(body.userid, body.reason, account['username'])}


@router.post('/api/points')
def points(body: PointsIn, ctx: AppContext = Depends(get_ctx), account: dict = Depends(current_account)):
    return {'out': ctx.game.give_points(body.target, body.amount, account['username'])}
