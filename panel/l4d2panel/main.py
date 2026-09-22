"""App factory and the process entry point (python3 panel.py [--config panel.json], or L4D2PANEL_CONFIG=...)."""
import logging, os, sys
from pathlib import Path

import uvicorn
from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api import install_routes
from .context import AppContext, build_context
from .deps import current_account
from .errors import ApiError, install_error_handlers
from .settings import Settings, load_settings

STATIC = Path(__file__).parent / 'static'            # the built frontend (frontend/ -> npm run build); not in git
PLACEHOLDER = Path(__file__).parent / 'placeholder.html'


def create_app(ctx: AppContext) -> FastAPI:
    app = FastAPI(title=ctx.settings.panel_title, version=__version__, docs_url='/api/docs', redoc_url=None, openapi_url='/api/openapi.json')
    app.state.ctx = ctx
    install_error_handlers(app)
    install_routes(app)

    @app.get('/api/{rest:path}')
    @app.post('/api/{rest:path}')
    def unknown_api(rest: str, account: dict = Depends(current_account)):   # any other /api path: 401 without a session, else 404
        raise ApiError(404, 'not found')

    if (STATIC / 'assets').is_dir():
        app.mount('/assets', StaticFiles(directory=STATIC / 'assets'), name='assets')

    @app.get('/', include_in_schema=False)
    def index():
        page = STATIC / 'index.html'
        return FileResponse(page if page.is_file() else PLACEHOLDER, media_type='text/html; charset=utf-8', headers={'Cache-Control': 'no-store'})

    return app


class _NoStatusPolls(logging.Filter):
    """The UI polls /api/status every 10 s; keep that out of the access log."""
    def filter(self, record):
        return '/api/status' not in record.getMessage()


def config_path(argv, base_dir: Path) -> str:
    env = os.environ.get('L4D2PANEL_CONFIG')
    if env: return env
    if '--config' in argv: return argv[argv.index('--config') + 1]
    return str(base_dir / 'panel.json')


def run(settings: Settings, base_dir: Path, conf: str) -> None:
    ctx = build_context(settings, base_dir)
    app = create_app(ctx)
    logging.getLogger('uvicorn.access').addFilter(_NoStatusPolls())
    print(f'L4D2 panel {__version__} listening on {settings.bind}:{settings.port} tls={settings.tls} config={conf}', flush=True)
    kw = {'ssl_certfile': str(ctx.paths.cert), 'ssl_keyfile': str(ctx.paths.key)} if settings.tls else {}
    uvicorn.run(app, host=settings.bind, port=int(settings.port), log_level='info', **kw)


def main(argv=None, base_dir=None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    base_dir = Path(base_dir or Path(sys.argv[0]).resolve().parent)
    conf = config_path(argv, base_dir)
    run(load_settings(conf), base_dir, conf)
