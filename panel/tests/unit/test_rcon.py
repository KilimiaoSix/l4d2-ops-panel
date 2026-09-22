import socket, threading, time

import pytest

from l4d2panel.errors import IntegrationError
from l4d2panel.integrations.rcon import RconClient


def test_run_returns_filtered_output(fake_game):
    rc = RconClient('127.0.0.1', fake_game.port, lambda: 'fakerc0n')
    assert rc.run('sm version') == 'echo: sm version'
    fake_game.status_text = 'L 09/22/2026 - 12:00:00: log echo\n[SM] Changed cvar "x" to "1".\nserver_cvar: "a" "b"\nkeep me\n\n  \nand me'
    assert rc.run('status') == 'keep me\nand me'
    assert fake_game.commands == ['sm version', 'status']


def test_wrong_password(fake_game):
    with pytest.raises(IntegrationError, match='密码'):
        RconClient('127.0.0.1', fake_game.port, lambda: 'nope').run('status')


def test_connection_refused():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0)); port = s.getsockname()[1]
    with pytest.raises(IntegrationError, match='RCON 连接失败'):
        RconClient('127.0.0.1', port, lambda: 'x').run('status')


def test_peer_closing_mid_reply_does_not_hang():
    srv = socket.socket(); srv.bind(('127.0.0.1', 0)); srv.listen(1)
    def close_on_connect():
        c, _ = srv.accept(); c.recv(64); c.close()
    threading.Thread(target=close_on_connect, daemon=True).start()
    rc = RconClient('127.0.0.1', srv.getsockname()[1], lambda: 'x', timeout=3)
    t0 = time.time()
    with pytest.raises(IntegrationError):
        rc.run('status')
    assert time.time() - t0 < 5
    assert not rc.lock.locked()      # the lock is released on failure: the next command can run
    srv.close()
