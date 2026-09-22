from typing import Literal, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..context import AppContext
from ..deps import get_ctx, require_owner

router = APIRouter()


class AccountsIn(BaseModel):
    op: Literal['create', 'delete', 'update']
    id: int = 0
    username: str = ''
    password: str = ''
    role: Optional[str] = None
    steamid: Optional[str] = None
    flags: Optional[str] = None
    note: Optional[str] = None


@router.get('/api/accounts')
def accounts(ctx: AppContext = Depends(get_ctx), account: dict = Depends(require_owner)):
    return ctx.accounts.list(account)


@router.post('/api/accounts')
def accounts_op(body: AccountsIn, ctx: AppContext = Depends(get_ctx), account: dict = Depends(require_owner)):
    who = account['username']
    if body.op == 'create':
        return {'ok': True, 'out': ctx.accounts.create(who, body.username, body.password, body.role, body.steamid, body.flags, body.note)}
    if body.op == 'delete':
        return {'ok': True, 'out': ctx.accounts.delete(account, body.id)}
    return {'ok': True, 'out': ctx.accounts.update(who, body.id, body.password, body.role, body.steamid, body.flags, body.note)}
