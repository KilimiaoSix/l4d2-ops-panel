"""Local development environment without a game server: a throwaway game_dir tree, a fake L4D2 (RCON + A2S)
and a panel.json pointing at both. Prints the command that starts the panel against it.

    cd panel && python3 -m tests.fakes.devenv [DIR]      # DIR defaults to ./devenv (ignored by git)

Then, in another shell:  python3 panel.py --config devenv/panel.json   and open http://127.0.0.1:8080
(owner login admin / admin). For the Vite dev server (frontend/, npm run dev) the panel must run on :8080.
"""
import json, os, sys, time
from pathlib import Path

from tests.conftest import LGSM_SCRIPT, CONSOLE_LINES, PERF_ROWS, PROTECTED_PLUGINS, RCON_PASSWORD, GameDir
from tests.fakes.game import FakeGame


def main():
    root = Path(sys.argv[1] if len(sys.argv) > 1 else 'devenv').resolve(); root.mkdir(parents=True, exist_ok=True)
    game_dir = GameDir(root / 'game')
    (root / 'console.log').write_text('\n'.join(CONSOLE_LINES) + '\n', encoding='utf-8')
    (root / 'perf.csv').write_text('\n'.join(PERF_ROWS) + '\n', encoding='utf-8')
    lgsm = root / 'lgsm'; lgsm.write_text(LGSM_SCRIPT); lgsm.chmod(0o755)
    game = FakeGame(password=RCON_PASSWORD, whitelist_path=game_dir.whitelist)
    conf = {'password': 'admin', 'port': 8080, 'bind': '127.0.0.1', 'db': str(root / 'panel.db'),
            'rcon_host': '127.0.0.1', 'rcon_port': game.port, 'rcon_password': '',
            'game_dir': str(game_dir.root), 'lgsm_script': str(lgsm), 'console_log': str(root / 'console.log'), 'perf_csv': str(root / 'perf.csv'),
            'depotdownloader': '', 'panel_title': 'L4D2 面板（开发）', 'display_host': 'dev.local:27015',
            'protected_addons': ['admin_system.vpk'], 'protected_plugins': PROTECTED_PLUGINS}
    (root / 'panel.json').write_text(json.dumps(conf, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'fake L4D2 on 127.0.0.1:{game.port}; game_dir {game_dir.root}\nstart the panel with:\n  python3 panel.py --config {root / "panel.json"}\nlogin admin / admin; Ctrl-C here stops the fake game', flush=True)
    try:
        while True: time.sleep(3600)
    except KeyboardInterrupt:
        game.stop()


if __name__ == '__main__':
    os.chdir(Path(__file__).resolve().parents[2])
    main()
