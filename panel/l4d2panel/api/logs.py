from fastapi import APIRouter, Depends, Request

from ..context import AppContext
from ..deps import current_account, get_ctx

router = APIRouter()


@router.get('/api/logs')
def logs(request: Request, ctx: AppContext = Depends(get_ctx), account: dict = Depends(current_account)):
    """?console (default) | ?errors | ?perf | ?perfjson — the kind is the bare query string."""
    kind = request.url.query
    if kind == 'errors': return {'lines': ctx.monitoring.errors()}
    if kind == 'perf': return {'lines': ctx.monitoring.perf_lines()}
    if kind == 'perfjson': return {'rows': ctx.monitoring.perf_rows()}
    return {'lines': ctx.monitoring.console()}
