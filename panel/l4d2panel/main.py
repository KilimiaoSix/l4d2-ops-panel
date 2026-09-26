"""App factory and the process entry point (python3 panel.py [--config panel.json], or L4D2PANEL_CONFIG=...)."""
import logging, os, sys, threading
from pathlib import Path

import uvicorn
from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api import install_routes
from .context import AppContext, build_context
from .deps import current_account
from .errors import ApiError, error_response, install_error_handlers
from .settings import Settings, load_settings
from .integrations.panel_config import check_config, ConfigError, PanelConfigFile
from .services.panel_restart import RestartJournal, supported_supervisor

STATIC = Path(__file__).parent / 'static'            # the built frontend (frontend/ -> npm run build); not in git
PLACEHOLDER = Path(__file__).parent / 'placeholder.html'


def create_app(ctx: AppContext) -> FastAPI:
    app = FastAPI(title=ctx.settings.panel_title, version=__version__, docs_url='/api/docs', redoc_url=None, openapi_url='/api/openapi.json')
    app.state.ctx = ctx
    install_error_handlers(app)
    install_routes(app)

    @app.middleware('http')
    async def write_admission(request, call_next):
        # The configuration service reserves the exclusive restart itself. All other writes
        # remain admitted until the endpoint finishes (including streamed uploads/RCON).
        guarded = request.method not in ('GET', 'HEAD', 'OPTIONS') and request.url.path != '/api/panel-config'
        if not guarded: return await call_next(request)
        try: ctx.operations.enter()
        except ApiError as exc: return error_response(exc.status, exc.message)
        # Manual plugin writes must not interleave with stopped-game file transactions.
        plugin_write = request.url.path in ('/api/plugins', '/api/plugin_upload', '/api/plugin-config', '/api/plugin-config/restore')
        locked = plugin_write and ctx.server.operation_lock.acquire(blocking=False)
        try:
            if plugin_write and not locked: return error_response(409, '插件安装或服务器操作正在进行，请稍后重试')
            return await call_next(request)
        finally:
            if locked: ctx.server.operation_lock.release()
            ctx.operations.leave()

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
    if '--config' in argv:
        index = argv.index('--config') + 1
        if index >= len(argv) or argv[index].startswith('--'): raise SystemExit('--config requires a file path')
        return argv[index]
    return str(base_dir / 'panel.json')


def run(settings: Settings, base_dir: Path, conf: str) -> None:
    ctx = build_context(settings, base_dir, Path(conf))
    app = create_app(ctx)
    logging.getLogger('uvicorn.access').addFilter(_NoStatusPolls())
    print(f'L4D2 panel {__version__} listening on {settings.bind}:{settings.port} tls={settings.tls} config={conf}', flush=True)
    kw = {'ssl_certfile': str(ctx.paths.cert), 'ssl_keyfile': str(ctx.paths.key)} if settings.tls else {}
    server = uvicorn.Server(uvicorn.Config(app, host=settings.bind, port=int(settings.port), log_level='info',
                                         timeout_graceful_shutdown=15, **kw))
    restart = ctx.panel_config.restart
    restart.exit_callback = lambda: setattr(server, 'should_exit', True)
    stopped = threading.Event()
    def confirm_boot():
        while not stopped.wait(0.1):
            if server.started:
                try: restart.journal.healthy(restart.applied_revision)
                except ConfigError as exc: logging.getLogger('l4d2panel').error('%s', exc)
                return
    watcher = threading.Thread(target=confirm_boot, daemon=True); watcher.start()
    try: server.run()
    finally:
        stopped.set(); watcher.join(timeout=1)


def main(argv=None, base_dir=None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    base_dir = Path(base_dir or Path(sys.argv[0]).resolve().parent)
    conf = config_path(argv, base_dir)
    journal = RestartJournal(PanelConfigFile(Path(conf), base_dir))
    if '--restore-config' in argv:
        try: journal.restore()
        except ConfigError as exc: raise SystemExit(str(exc)) from None
        print('Configuration restored; restart l4d2panel.service', flush=True)
        return
    if '--check-config' in argv:
        try: check_config(Path(conf), base_dir)
        except ConfigError as exc: raise SystemExit(str(exc)) from None
        print('Configuration valid', flush=True)
        return
    if supported_supervisor():
        try: journal.before_start()
        except ConfigError as exc:
            print(str(exc), file=sys.stderr, flush=True)
            raise SystemExit(78) from None
    run(load_settings(conf), base_dir, conf)
