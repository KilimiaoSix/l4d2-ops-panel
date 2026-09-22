"""Wiring: one AppContext holds every store, integration and service, built from Settings. Routers reach it
through request.app.state.ctx; tests build one with fakes."""
from dataclasses import dataclass
from pathlib import Path

from .integrations.a2s import A2SClient
from .integrations.lgsm import Lgsm
from .integrations.rcon import RconClient
from .integrations.sm_files import read_rcon_password
from .integrations.steam import SteamClient
from .jobs import DownloadStore, JobRegistry
from .services.accounts import AccountService
from .services.addons import AddonService
from .services.auth import AuthService
from .services.features import FeatureDetector
from .services.game import GameService
from .services.monitoring import Monitoring
from .services.plugins import PluginService
from .services.server_control import ServerControl
from .services.status import StatusService
from .services.whitelist import WhitelistService
from .settings import Paths, Settings
from .store.accounts import AccountStore
from .store.audit import AuditLog
from .store.db import Database
from .store.sessions import SessionStore


@dataclass
class AppContext:
    settings: Settings
    paths: Paths
    db: Database
    audit: AuditLog
    auth: AuthService
    status: StatusService
    game: GameService
    whitelist: WhitelistService
    addons: AddonService
    plugins: PluginService
    accounts: AccountService
    monitoring: Monitoring
    server: ServerControl


def build_context(settings: Settings, base_dir: Path) -> AppContext:
    paths = Paths.from_settings(settings, Path(base_dir))
    db = Database(paths.db); db.init()
    account_store, sessions, audit = AccountStore(db), SessionStore(db, settings.session_days), AuditLog(db)
    rcon = RconClient(settings.rcon_host, settings.rcon_port, lambda: settings.rcon_password or read_rcon_password(paths.server_cfg))
    a2s = A2SClient(settings.rcon_host, settings.rcon_port)
    steam = SteamClient(settings.steam_api_base, settings.steam_community_base)
    lgsm = Lgsm(settings.lgsm_script)
    jobs, downloads = JobRegistry(), DownloadStore()
    features = FeatureDetector(settings, rcon, lgsm)
    monitoring = Monitoring(settings, paths)
    server = ServerControl(lgsm, audit)
    game = GameService(paths, rcon, audit)
    auth = AuthService(settings, account_store, sessions, audit); auth.seed()
    return AppContext(settings=settings, paths=paths, db=db, audit=audit, auth=auth,
                      status=StatusService(settings, a2s, game, features, monitoring, server), game=game,
                      whitelist=WhitelistService(paths, rcon, steam, game, audit),
                      addons=AddonService(settings, paths, rcon, steam, jobs, downloads, audit),
                      plugins=PluginService(settings, paths, rcon, audit),
                      accounts=AccountService(paths, account_store, sessions, audit, steam, rcon),
                      monitoring=monitoring, server=server)
