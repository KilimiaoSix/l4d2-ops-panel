"""Container fixture: protocol-compatible fake, explicitly not the L4D2 engine."""
import re
import sys
import time
from pathlib import Path

from game import FakeGame

root = Path('/l4d2/left4dead2')
config = (root / 'cfg/server.cfg').read_text()
password = re.search(r'^rcon_password "([^"]+)"', config, re.M).group(1)
args = sys.argv[1:]
port = int(args[args.index('-port') + 1])


class Game(FakeGame):
    def reply(self, cmd):
        print('RCON command: ' + cmd, flush=True)
        if cmd == 'stats': return 'CPU In Out Uptime Users FPS Players\n12.0 2048 4096 1 2 30.0 2'
        if cmd.startswith('sm_cvar '):
            cmd = re.sub(r'"([^"\n]*)"', r'\1', cmd)
        return super().reply(cmd)


game = Game(password=password, whitelist_path=root / 'addons/sourcemod/configs/whitelist.txt', port=port)
for name, value in re.findall(r'^(?:sm_cvar\s+)?(\w+)\s+"?([^"\s]+)', config, re.M):
    if name == 'mp_gamemode' or name.startswith('survivor_'):
        game.state['cvars'][name] = value
print('Docker protocol fixture ready', flush=True)
while True: time.sleep(1)
