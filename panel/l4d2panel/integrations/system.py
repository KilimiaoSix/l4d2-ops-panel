"""Host-level reads: log tails and /proc system info."""
import re

ANSI = re.compile(r'\x1b\[[0-9;]*m')


def tail(path, n):
    """Last n lines of a text file with ANSI colour codes stripped; [] if it does not exist."""
    if not path: return []
    try:
        with open(path, 'rb') as f:
            f.seek(0, 2); size = f.tell(); block = min(size, 65536 * max(1, n // 200))
            f.seek(size - block); data = f.read().decode('utf-8', 'replace')
        return [ANSI.sub('', l) for l in data.splitlines()[-n:]]
    except FileNotFoundError:
        return []


def sysinfo():
    try:
        load = open('/proc/loadavg').read().split()[:3]
        mem = {}
        for l in open('/proc/meminfo'):
            k, v = l.split(':'); mem[k] = int(v.split()[0])
        up = float(open('/proc/uptime').read().split()[0])
        return {'load': ' '.join(load), 'mem_used_mb': (mem['MemTotal'] - mem['MemAvailable']) // 1024, 'mem_total_mb': mem['MemTotal'] // 1024, 'uptime_h': round(up / 3600, 1)}
    except Exception:
        return {}
