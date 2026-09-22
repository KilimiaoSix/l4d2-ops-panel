"""Console log, SourceMod error log, perf samples (tools/perf-sampler.sh CSV) and host load."""
import glob, os

from ..integrations.system import sysinfo, tail
from ..settings import Paths, Settings


class Monitoring:
    def __init__(self, settings: Settings, paths: Paths):
        self.console_log, self.perf_csv, self.sm_logs = settings.console_log, settings.perf_csv, paths.sm_logs

    def console(self, n=150):
        return tail(self.console_log, n)

    def errors(self, n=120):
        files = sorted(glob.glob(os.path.join(self.sm_logs, 'errors_*.log')))
        return tail(files[-1], n) if files else []

    def perf_lines(self, n=60):
        return tail(self.perf_csv, n)

    def perf_rows(self, n=120):
        rows = []
        for l in tail(self.perf_csv, n):
            c = l.split(',')
            if len(c) >= 7 and c[0] != 'time':
                try: rows.append({'t': c[0], 'humans': int(c[1]), 'cpu': float(c[2]), 'out_kb': round(float(c[4]) / 1024, 1), 'fps': float(c[5])})
                except ValueError: pass
        return rows

    def latest_perf(self):
        rows = tail(self.perf_csv, 2); c = rows[-1].split(',') if len(rows) > 1 else []
        return {'t': c[0], 'fps': c[5], 'out_kb': round(float(c[4]) / 1024, 1)} if len(c) >= 7 else None

    def sysinfo(self):
        return sysinfo()
