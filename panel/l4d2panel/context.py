"""Wiring: one AppContext holds every store, integration and service, built from Settings. Routers reach it
through request.app.state.ctx; tests build one with fakes."""
from dataclasses import dataclass
from pathlib import Path

from .integrations.a2s import A2SClient
from .integrations.lgsm import Lgsm
from .integrations.docker import DockerServer
from .integrations.game_installer import DockerGameInstaller
from .integrations.panel_config import PanelConfigFile
from .integrations.rcon import RconClient
from .integrations.sm_files import read_rcon_password
from .integrations.steam import SteamClient
from .jobs import DownloadStore, JobRegistry
from .operations import OperationGate
from .services.accounts import AccountService
from .services.addons import AddonService
from .services.auth import AuthService
from .services.basic_settings import BasicSettingsService
from .services.features import FeatureDetector
from .services.game import GameService
from .services.game_install import GameInstallService
from .services.monitoring import Monitoring
from .services.onboarding import OnboardingService
from .services.plugins import PluginService
from .services.plugin_packs import PluginPackService
from .services.plugin_config import PluginConfigService
from .services.panel_config import PanelConfigService
from .services.panel_restart import PanelRestart
from .services.server_control import ServerControl
from .services.status import StatusService
from .services.whitelist import WhitelistService
from .settings import Paths, Settings
from .store.accounts import AccountStore
from .store.audit import AuditLog
from .store.db import Database
from .store.sessions import SessionStore
from .store.panel_state import PanelStateStore


@dataclass
class AppContext:
    settings: Settings
    config_path: Path
    panel_state: PanelStateStore
    operations: OperationGate
    panel_config: PanelConfigService
    onboarding: OnboardingService
    paths: Paths
    db: Database
    audit: AuditLog
    auth: AuthService
    status: StatusService
    game: GameService
    whitelist: WhitelistService
    addons: AddonService
    plugins: PluginService
    plugin_packs: PluginPackService
    plugin_config: PluginConfigService
    basic_settings: BasicSettingsService
    accounts: AccountService
    monitoring: Monitoring
    server: ServerControl
    game_install: GameInstallService


def build_context(settings: Settings, base_dir: Path, conf: Path) -> AppContext:
    paths = Paths.from_settings(settings, Path(base_dir))
    installer = DockerGameInstaller(paths.install_dir, paths.game, settings.docker_project)
    def configure_docker(metadata):
        settings.server_backend = 'docker'
        settings.rcon_host = '127.0.0.1'
        settings.rcon_port = int(metadata['game_port'])
        settings.rcon_password = ''
    if installer.installed():
        configure_docker(installer.metadata())
    db = Database(paths.db); db.init()
    panel_state = PanelStateStore(db); panel_state.init()
    account_store, sessions, audit = AccountStore(db), SessionStore(db, settings.session_days), AuditLog(db)
    rcon = RconClient(settings.rcon_host, settings.rcon_port, lambda: settings.rcon_password or read_rcon_password(paths.server_cfg))
    a2s = A2SClient(settings.rcon_host, settings.rcon_port)
    steam = SteamClient(settings.steam_api_base, settings.steam_community_base, settings.steam_api_key)
    lgsm = Lgsm(settings.lgsm_script)
    operations = OperationGate()
    jobs, downloads = JobRegistry(operations), DownloadStore()
    docker = DockerServer(settings, paths)
    server = ServerControl(lgsm, audit, docker=docker, settings=settings, gate=operations)
    features = FeatureDetector(settings, rcon, lgsm, server=server, paths=paths)
    monitoring = Monitoring(settings, paths, docker=docker, rcon=rcon)
    game = GameService(paths, rcon, audit)
    def invalidate_game():
        features.invalidate()
        game.invalidate_flags()
    server.invalidate = invalidate_game
    plugin_packs = PluginPackService(Path(__file__).resolve().parents[1] / 'packs', paths, jobs, server, rcon, panel_state, audit, invalidate_game)
    basic_settings = BasicSettingsService(paths, settings, rcon, server, plugin_packs, panel_state, audit, invalidate_game)
    game.preset_guard = basic_settings.guard_preset
    server.start_guard = lambda: not (plugin_packs.files.pending() or basic_settings.config.transaction.pending())
    auth = AuthService(settings, account_store, sessions, audit); auth.seed()
    def activate_docker(metadata):
        with rcon.lock:
            configure_docker(metadata)
            rcon.host, rcon.port = settings.rcon_host, settings.rcon_port
        a2s.host, a2s.port = settings.rcon_host, settings.rcon_port
        a2s.cache.clear()
        features.t, features.v = 0, {}
        game.invalidate_flags()
    game_install = GameInstallService(settings, paths, jobs, audit, installer=installer,
                                      operation_lock=server.operation_lock, activate=activate_docker)
    config_file = PanelConfigFile(conf, paths.base)
    restart = PanelRestart(config_file, operations)
    def has_install_data():
        return (game_install.installer.installed() or paths.game.exists() and any(paths.game.iterdir())
                or paths.install_dir.exists() and any(paths.install_dir.iterdir()))
    panel_config = PanelConfigService(settings, config_file, restart, audit, steam, features, has_install_data)
    return AppContext(settings=settings, config_path=Path(conf).resolve(), panel_state=panel_state,
                      operations=operations, panel_config=panel_config,
                      onboarding=OnboardingService(panel_state, paths, settings, audit), paths=paths, db=db, audit=audit, auth=auth,
                      status=StatusService(settings, a2s, game, features, monitoring, server, game_ready=paths.server_cfg.is_file), game=game,
                      whitelist=WhitelistService(paths, rcon, steam, game, audit),
                      addons=AddonService(settings, paths, rcon, steam, jobs, downloads, audit),
                      plugins=PluginService(settings, paths, rcon, audit),
                      plugin_packs=plugin_packs,
                      basic_settings=basic_settings,
                      plugin_config=PluginConfigService(paths, rcon, audit),
                      accounts=AccountService(paths, account_store, sessions, audit, steam, rcon),
                      monitoring=monitoring, server=server, game_install=game_install)
