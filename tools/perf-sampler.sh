#!/bin/bash
# Lightweight LinuxGSM sampler. Reuses the installed panel's RCON integration.
set -eu
L4D2_HOME=${L4D2_HOME:-$HOME}
PANEL_DIR=${PANEL_DIR:-$L4D2_HOME/panel}
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec "$PANEL_DIR/venv/bin/python" -B "$SCRIPT_DIR/perf-sampler.py" --config "$PANEL_DIR/panel.json" "$@"
