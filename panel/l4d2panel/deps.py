"""FastAPI dependencies: the app context, the client IP, the session cookie and the account behind it."""
from fastapi import Depends, Request, Response

from .context import AppContext
from .errors import ApiError

COOKIE = 'l4d2panel'


def get_ctx(request: Request) -> AppContext:
    return request.app.state.ctx


def client_ip(request: Request) -> str:
    return request.headers.get('x-real-ip', '').strip() or (request.client.host if request.client else '')   # X-Real-IP is set by nginx from $remote_addr


def session_id(request: Request):
    return request.cookies.get(COOKIE)


def current_account(request: Request, ctx: AppContext = Depends(get_ctx)) -> dict:
    account = ctx.auth.account_for(session_id(request))
    if not account: raise ApiError(401, 'auth')
    return account


def require_owner(account: dict = Depends(current_account)) -> dict:
    if account['role'] != 'owner': raise ApiError(403, '需要 owner 权限')
    return account


def set_session_cookie(response: Response, request: Request, ctx: AppContext, sid: str) -> None:
    secure = ctx.settings.tls or request.headers.get('x-forwarded-proto', '') == 'https'
    response.set_cookie(COOKIE, sid, max_age=int(ctx.settings.session_days) * 86400, path='/', httponly=True, samesite='lax', secure=secure)
