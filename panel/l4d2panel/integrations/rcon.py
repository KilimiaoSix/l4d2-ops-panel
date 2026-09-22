"""Source RCON client. One TCP connection per command (connect, auth, exec, close) under a lock: srcds drops
idle RCON connections and answers out of order when several are open, so this is the robust shape for a panel
that sends a few commands a minute."""
import re, socket, struct, threading

from ..errors import IntegrationError

# server-log echo and cvar-change chatter that srcds mixes into command output
NOISE = re.compile(r'^(L \d\d/\d\d/\d{4} - [\d:]+:|\[SM\] (更改|Changed) cvar|server_cvar:)')


def _pkt(i, t, body: str) -> bytes:
    d = struct.pack('<ii', i, t) + body.encode() + b'\x00\x00'
    return struct.pack('<i', len(d)) + d


def _recv(s):
    raw = b''
    while len(raw) < 4:
        c = s.recv(4 - len(raw))
        if not c: raise ConnectionError('RCON connection closed')   # (2026-09-19) was an infinite spin holding the lock when the peer closed
        raw += c
    n = struct.unpack('<i', raw)[0]; d = b''
    while len(d) < n:
        c = s.recv(n - len(d))
        if not c: raise ConnectionError('RCON connection closed')
        d += c
    i, t = struct.unpack('<ii', d[:8]); return i, t, d[8:-2].decode('utf-8', 'replace')


class RconClient:
    def __init__(self, host: str, port: int, password_provider, timeout=6):
        self.host, self.port, self.password_provider, self.timeout = host, int(port), password_provider, timeout
        self.lock = threading.Lock()

    def run(self, cmd: str) -> str:
        """Send one command, return its output with log/cvar noise lines removed. Raises IntegrationError."""
        try:
            with self.lock:
                s = socket.create_connection((self.host, self.port), timeout=self.timeout)
                try:
                    s.sendall(_pkt(1, 3, self.password_provider()))
                    i, t, _ = _recv(s)
                    if t == 0: i, t, _ = _recv(s)          # servers send an empty RESPONSE_VALUE before the auth reply
                    if i == -1: raise IntegrationError('RCON 密码错误')
                    s.sendall(_pkt(2, 2, cmd)); s.sendall(_pkt(3, 2, ''))   # empty EXEC as terminator: replies come back in order
                    out = ''
                    while True:
                        i, t, b = _recv(s)
                        if i == 3: break
                        out += b
                finally:
                    s.close()
        except IntegrationError:
            raise
        except OSError as e:
            raise IntegrationError(f'RCON 连接失败: {e}')
        lines = [l for l in out.splitlines() if l.strip() and not NOISE.match(l.strip())]
        return '\n'.join(lines).strip()
