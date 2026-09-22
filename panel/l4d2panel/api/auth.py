from typing import Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel

from ..context import AppContext
from ..deps import client_ip, current_account, get_ctx, session_id, set_session_cookie

router = APIRouter()


class SetupIn(BaseModel):
    password: str = ''


class LoginIn(BaseModel):
    username: str = ''
    password: str = ''


class MeIn(BaseModel):
    op: Literal['password', 'steamid']
    current: str = ''
    password: str = ''
    steamid: str = ''


@router.get('/api/setup')
def setup_state(ctx: AppContext = Depends(get_ctx)):
    return {'needed': ctx.auth.setup_needed(), 'username': ctx.settings.bootstrap_user}


@router.post('/api/setup')
def setup(body: SetupIn, request: Request, response: Response, ctx: AppContext = Depends(get_ctx), ip: str = Depends(client_ip)):
    sid = ctx.auth.setup(body.password, ip)
    set_session_cookie(response, request, ctx, sid)
    return {'ok': True}


@router.post('/api/login')
def login(body: LoginIn, request: Request, response: Response, ctx: AppContext = Depends(get_ctx), ip: str = Depends(client_ip)):
    sid = ctx.auth.login(body.username, body.password, ip)
    set_session_cookie(response, request, ctx, sid)
    return {'ok': True}


@router.post('/api/logout')
def logout(request: Request, ctx: AppContext = Depends(get_ctx), account: dict = Depends(current_account)):
    ctx.auth.logout(session_id(request))
    return {'ok': True}


@router.get('/api/me')
def me(ctx: AppContext = Depends(get_ctx), account: dict = Depends(current_account)):
    return ctx.accounts.me(account)


@router.post('/api/me')
def me_update(body: MeIn, request: Request, ctx: AppContext = Depends(get_ctx), account: dict = Depends(current_account)):
    if body.op == 'password':
        ctx.accounts.change_password(account, body.current, body.password, session_id(request))
        return {'ok': True}
    sid, out = ctx.accounts.bind_steam(account, body.steamid)
    return {'ok': True, 'steamid': sid, 'out': out}
