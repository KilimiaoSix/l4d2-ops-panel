#!/usr/bin/env python3
"""L4D2 Ops Panel entry point:  python3 panel.py [--config panel.json]   (or L4D2PANEL_CONFIG=/path/panel.json)

The application lives in the l4d2panel package next to this file; relative paths in panel.json (db, cert, key)
resolve against this directory, and downloads/ + workshop_tmp/ are kept here too."""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from l4d2panel.main import main  # noqa: E402

if __name__ == '__main__':
    main(base_dir=os.path.dirname(os.path.abspath(__file__)))
