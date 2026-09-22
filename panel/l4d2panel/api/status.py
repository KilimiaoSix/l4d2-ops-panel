from fastapi import APIRouter, Depends

from ..context import AppContext
from ..deps import current_account, get_ctx

router = APIRouter()


@router.get('/api/status')
def status(ctx: AppContext = Depends(get_ctx), account: dict = Depends(current_account)):
    return ctx.status.build(account)
