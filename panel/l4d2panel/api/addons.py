from typing import List, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..context import AppContext
from ..deps import current_account, get_ctx
from ..errors import ApiError

router = APIRouter()


class AddonsIn(BaseModel):
    op: str
    name: str = ''
    id: str = ''
    names: Optional[List[str]] = None


@router.get('/api/addons')
def addons(ctx: AppContext = Depends(get_ctx), account: dict = Depends(current_account)):
    return ctx.addons.overview()


@router.post('/api/addons')
def addons_op(body: AddonsIn, ctx: AppContext = Depends(get_ctx), account: dict = Depends(current_account)):
    who = account['username']
    if body.op == 'delete': return ctx.addons.delete(body.name, who)
    if body.op == 'workshop': return {'ok': True, 'id': ctx.addons.start_workshop(body.id, who)}
    if body.op == 'workshop_cancel': ctx.addons.cancel_workshop(body.id); return {'ok': True}
    if body.op == 'zip': return {'ok': True, 'token': ctx.addons.start_zip(body.names or ([body.name] if body.name else []), who)}
    raise ApiError(400, 'bad op')


async def stream_to_file(request: Request, path) -> int:
    got = 0
    with open(path, 'wb') as f:
        async for chunk in request.stream():
            f.write(chunk); got += len(chunk)
    return got


@router.post('/api/upload')
async def upload(request: Request, name: str = '', ctx: AppContext = Depends(get_ctx), account: dict = Depends(current_account)):
    """VPK upload: the raw .vpk body, name in the query string (multi-GB files are streamed to disk)."""
    safe, tmp = ctx.addons.upload_target(name)
    n = int(request.headers.get('content-length', 0) or 0); ctx.addons.check_upload_size(n)
    got = await stream_to_file(request, tmp)
    return ctx.addons.finish_upload(safe, tmp, got, n, account['username'])


@router.get('/api/workshop_search')
def workshop_search(q: str = '', page: int = 1, ctx: AppContext = Depends(get_ctx), account: dict = Depends(current_account)):
    """Search L4D2 Workshop items (needs steam_api_key); ?q= text, empty = most subscribed; ?page= for more."""
    return ctx.addons.search(q, page)


@router.get('/api/download')
def download(token: str = '', ctx: AppContext = Depends(get_ctx), account: dict = Depends(current_account)):
    path, name = ctx.addons.download(token)
    return FileResponse(path, media_type='application/zip', headers={'Content-Disposition': "attachment; filename*=UTF-8''" + quote(name)})
