"""HTTP routes. Thin by design: parse the request, call one service, return its dict."""
from fastapi import FastAPI

from . import accounts, addons, auth, basic_settings, game, install, logs, onboarding, panel_config, players, plugins, plugin_packs, status


def install_routes(app: FastAPI) -> None:
    for m in (auth, status, players, game, addons, install, plugins, plugin_packs, basic_settings, onboarding, panel_config, accounts, logs):
        app.include_router(m.router)
