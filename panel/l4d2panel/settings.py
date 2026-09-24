"""panel.json -> Settings. The keys and defaults are those of the original single-file panel, so an existing
config keeps working; unknown keys are ignored. Relative paths (db, cert, key) resolve against the directory
panel.py lives in, as before."""
import json, os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

DEFAULT_PROTECTED_PLUGINS = ['sourcemod', 'basecommands', 'basetriggers', 'basechat', 'admin-flatfile', 'adminmenu',
                             'sm_whitelist', 'sipreset', 'ps_mapreset', 'l4d2_points_system']


class Settings(BaseModel):
    model_config = ConfigDict(extra='ignore')

    password: str = ''                  # seeds the first owner account once; '' = set it on the first visit (setup page)
    bootstrap_user: str = 'admin'
    port: int = 8080
    bind: str = '127.0.0.1'
    tls: bool = False
    cert: str = 'cert.pem'
    key: str = 'key.pem'
    session_days: int = 7
    db: str = 'panel.db'
    rcon_host: str = '127.0.0.1'
    rcon_port: int = 27015
    rcon_password: str = ''             # '' -> read from <game_dir>/cfg/server.cfg
    game_dir: str = '/home/l4d2server/serverfiles/left4dead2'
    lgsm_script: str = '/home/l4d2server/l4d2server'      # '' = no server control buttons
    console_log: str = '/home/l4d2server/log/console/l4d2server-console.log'
    perf_csv: str = '/home/l4d2server/log/perf-samples.csv'
    depotdownloader: str = '/home/l4d2server/tools/depotdownloader/DepotDownloader'
    steam_api_base: str = 'https://api.steampowered.com'
    steam_community_base: str = 'https://steamcommunity.com'
    steam_api_key: str = ''                # Steam Web API key: enables the workshop search card ('' = hidden)
    workshop_connections: int = 8
    workshop_retries: int = 8
    panel_title: str = 'L4D2 运维面板'
    display_host: str = ''
    max_upload_mb: int = 3072
    protected_addons: List[str] = ['admin_system.vpk']
    protected_plugins: List[str] = DEFAULT_PROTECTED_PLUGINS
    server_backend: Literal['lgsm', 'docker'] = 'lgsm'
    docker_project: str = Field(default='l4d2-panel', pattern=r'^[a-z0-9][a-z0-9_-]{0,62}$')
    install_dir: str = 'docker'


@dataclass(frozen=True)
class Paths:
    """Every file and directory the panel touches, derived once from Settings + the panel directory."""
    base: Path
    game: Path
    server_cfg: Path
    addons: Path
    sm_plugins: Path
    sm_disabled: Path
    sm_logs: Path
    whitelist: Path
    admins_ini: Path
    db: Path
    cert: Path
    key: Path
    downloads: Path
    workshop_tmp: Path
    install_dir: Path

    @classmethod
    def from_settings(cls, s: Settings, base: Path) -> 'Paths':
        def rel(p): return Path(p) if os.path.isabs(p) else base / p
        game = rel(s.game_dir).resolve(); sm = game / 'addons' / 'sourcemod'
        install_dir = rel(s.install_dir)
        return cls(base=base, game=game, server_cfg=game / 'cfg' / 'server.cfg', addons=game / 'addons',
                   sm_plugins=sm / 'plugins', sm_disabled=sm / 'plugins' / 'disabled', sm_logs=sm / 'logs',
                   whitelist=sm / 'configs' / 'whitelist.txt', admins_ini=sm / 'configs' / 'admins_simple.ini',
                   db=rel(s.db), cert=rel(s.cert), key=rel(s.key), downloads=base / 'downloads', workshop_tmp=base / 'workshop_tmp', install_dir=install_dir)


def load_settings(path) -> Settings:
    try:
        raw = json.load(open(path, encoding='utf-8'))
    except FileNotFoundError:
        raise SystemExit(f'config not found: {path} (copy panel.example.json to panel.json or run install.sh)')
    except ValueError as e:
        raise SystemExit(f'config is not valid JSON: {path}: {e}')
    try:
        return Settings.model_validate(raw)
    except ValidationError as e:
        raise SystemExit(f'config {path} is invalid:\n{e}')
