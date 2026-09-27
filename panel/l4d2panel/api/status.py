import os

from fastapi import APIRouter, Depends, Response

from ..context import AppContext
from ..deps import current_account, get_ctx
from .. import __version__

router = APIRouter()


@router.get('/api/health')
def health(response: Response, ctx: AppContext = Depends(get_ctx)):
    """Bootstrap liveness only: no game probes, secrets or user configuration."""
    response.headers['Cache-Control'] = 'no-store'
    return {'version': __version__, 'boot': ctx.panel_config.restart.boot,
            'pid': os.getpid(), 'ready': not ctx.auth.setup_needed()}


@router.get('/api/status')
def status(response: Response, ctx: AppContext = Depends(get_ctx), account: dict = Depends(current_account)):
    response.headers['Cache-Control'] = 'no-store'
    value = ctx.status.build(account)
    restart = ctx.panel_config.restart
    value.update(boot=restart.boot, version=__version__, config_revision=restart.applied_revision,
                 onboarding_complete=ctx.panel_state.get('onboarding')['completed'], game_installed=ctx.paths.server_cfg.is_file())
    return value
