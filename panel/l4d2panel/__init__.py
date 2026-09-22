"""L4D2 Ops Panel — FastAPI backend for the web panel of a Left 4 Dead 2 dedicated server.

Layers: api (HTTP routes) -> services (workflows, permissions, audit) -> integrations (RCON / A2S / Steam /
LinuxGSM / SourceMod files) and store (SQLite). `context.build_context()` wires them from a Settings object;
nothing is created at import time, so every piece can be built with fakes in tests.
"""
__version__ = '2.0.0'
