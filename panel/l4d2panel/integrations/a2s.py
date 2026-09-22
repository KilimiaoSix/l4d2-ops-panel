"""A2S_INFO query (UDP). L4D2 rate-limits A2S and a public server is scanned constantly, so a single query often
lands in a throttled window: query() retries a few times, and the caller falls back to RCON `status` when the
process is up but A2S still stays silent. name/map/max of the last good reply are kept in .cache for that path."""
import socket, time


class A2SClient:
    def __init__(self, host: str, port: int):
        self.host, self.port = host, int(port); self.cache = {}

    def _once(self, timeout=1.5):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.settimeout(timeout)
        req = b'\xFF\xFF\xFF\xFFTSource Engine Query\x00'
        try:
            addr = (self.host, self.port)
            s.sendto(req, addr); d, _ = s.recvfrom(4096)
            if d[4:5] == b'A': s.sendto(req + d[5:9], addr); d, _ = s.recvfrom(4096)   # challenge round
            p = 6; f = []
            for _ in range(4):
                e = d.index(b'\x00', p); f.append(d[p:e].decode('utf-8', 'replace')); p = e + 1
            self.cache.update(name=f[0], map=f[1], max=d[p + 3])
            return {'online': True, 'name': f[0], 'map': f[1], 'players': d[p + 2], 'max': d[p + 3], 'bots': d[p + 4]}
        finally:
            s.close()

    def query(self, attempts=3) -> dict:
        for i in range(attempts):
            try:
                return self._once()
            except Exception:
                if i < attempts - 1: time.sleep(0.35)
        return {'online': False}
