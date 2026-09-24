"""Console/error logs and performance samples for LinuxGSM or Docker game servers."""
import glob, math, os, threading, time
from collections import deque

from ..errors import ApiError
from ..integrations.lgsm import ANSI
from ..integrations.srcds import STATUS_SUMMARY
from ..integrations.system import sysinfo, tail
from ..settings import Paths, Settings


class Monitoring:
    def __init__(self, settings: Settings, paths: Paths, docker=None, rcon=None):
        self.settings, self.docker, self.rcon = settings, docker, rcon
        self.console_log, self.perf_csv, self.sm_logs = settings.console_log, settings.perf_csv, paths.sm_logs
        self._samples = deque(maxlen=120)
        self._sample_lock = threading.Lock()
        self._sample_time = float('-inf')

    @property
    def is_docker(self):
        return self.settings.server_backend == 'docker'

    def console(self, n=150):
        if self.is_docker:
            try: return self.docker.console(n) if self.docker else []
            except RuntimeError as exc: raise ApiError(503, str(exc)) from exc
        return tail(self.console_log, n)

    def errors(self, n=120):
        files = sorted(glob.glob(os.path.join(self.sm_logs, 'errors_*.log')))
        return tail(files[-1], n) if files else []

    def _docker_samples(self):
        # Poll-driven sampling avoids a permanent thread and preserves the existing API shape.
        with self._sample_lock:
            now = time.monotonic()
            if self.rcon and now - self._sample_time >= 15:
                self._sample_time = now
                try:
                    out = ANSI.sub('', self.rcon.run('stats'))
                    for line in reversed(out.splitlines()):
                        columns = line.split()
                        if len(columns) != 7: continue
                        try: values = [float(value) for value in columns]
                        except ValueError: continue
                        if not all(math.isfinite(value) and value >= 0 for value in values): continue
                        summary = STATUS_SUMMARY.search(self.rcon.run('status'))
                        if summary:
                            self._samples.append({'t': time.strftime('%H:%M:%S'), 'humans': int(summary.group(1)),
                                                  'cpu': values[0], 'in_bytes': values[1], 'out_bytes': values[2],
                                                  'fps': values[5], 'players': int(values[6])})
                        break
                except Exception:
                    pass  # Offline and unsupported stats produce no fabricated sample.
            return list(self._samples)

    def perf_lines(self, n=60):
        if self.is_docker:
            samples = self._docker_samples()
            lines = ['time,humans,cpu%,in_bytes,out_bytes,fps,players']
            lines.extend(','.join(str(row[key]) for key in ('t', 'humans', 'cpu', 'in_bytes', 'out_bytes', 'fps', 'players')) for row in samples)
            return lines[-n:]
        return tail(self.perf_csv, n)

    def perf_rows(self, n=120):
        if self.is_docker:
            return [{'t': row['t'], 'humans': row['humans'], 'cpu': row['cpu'], 'out_kb': round(row['out_bytes'] / 1024, 1), 'fps': row['fps']}
                    for row in self._docker_samples()[-n:]]
        rows = []
        for l in tail(self.perf_csv, n):
            c = l.split(',')
            if len(c) >= 7 and c[0] != 'time':
                try: rows.append({'t': c[0], 'humans': int(c[1]), 'cpu': float(c[2]), 'out_kb': round(float(c[4]) / 1024, 1), 'fps': float(c[5])})
                except ValueError: pass
        return rows

    def latest_perf(self):
        if self.is_docker:
            rows = self._docker_samples()
            return {'t': rows[-1]['t'], 'fps': str(rows[-1]['fps']), 'out_kb': round(rows[-1]['out_bytes'] / 1024, 1)} if rows else None
        rows = tail(self.perf_csv, 2); c = rows[-1].split(',') if len(rows) > 1 else []
        return {'t': c[0], 'fps': c[5], 'out_kb': round(float(c[4]) / 1024, 1)} if len(c) >= 7 else None

    def sysinfo(self):
        return sysinfo()
