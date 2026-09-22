"""HTTP routes. Thin by design: parse the request, call one service, return its dict."""
from fastapi import FastAPI

from . import accounts, addons, auth, game, logs, players, plugins, status


def install_routes(app: FastAPI) -> None:
    for m in (auth, status, players, game, addons, plugins, accounts, logs):
        app.include_router(m.router)
