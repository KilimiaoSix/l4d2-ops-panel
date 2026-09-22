"""python -m l4d2panel [--config panel.json]"""
from pathlib import Path

from .main import main

main(base_dir=Path.cwd())
