"""Background jobs (workshop downloads, zip packaging) and the one-hour download tokens the zips are served under.

One shape for every job: state (running / done / error), msg, done / total / speed for progress, files / name /
title for what it produced, cancel as the co-operative stop flag. The registry runs each job in a daemon thread
and turns an exception into state=error with the exception text as msg."""
import os, threading, time


class Job:
    def __init__(self, id, kind):
        self.id, self.kind = id, kind
        self.state, self.msg = 'running', ''
        self.files, self.name, self.title = [], '', ''
        self.done, self.total, self.speed = 0, 0, 0.0
        self.cancel = False
        self.extra = {}            # kind-specific result fields (zip: token / size_mb)

    def to_dict(self):
        d = {'state': self.state, 'msg': self.msg, 'files': self.files, 'name': self.name, 'title': self.title,
             'done': self.done, 'total': self.total, 'speed': self.speed}
        if self.cancel: d['cancel'] = True
        d.update(self.extra)
        return d


class JobRegistry:
    def __init__(self):
        self.jobs = {}; self.lock = threading.Lock()

    def get(self, kind, id):
        return self.jobs.get((kind, id))

    def is_running(self, kind, id):
        j = self.get(kind, id); return bool(j and j.state == 'running')

    def start(self, kind, id, fn, initial_msg=''):
        """Run fn(job) in a background thread. Raises if a job with this kind/id is still running."""
        with self.lock:
            if self.is_running(kind, id): raise RuntimeError('already running')
            job = self.jobs[(kind, id)] = Job(id, kind); job.msg = initial_msg
        def work():
            try:
                fn(job)
                if job.state == 'running': job.state = 'done'
            except Exception as e:
                job.state, job.msg = 'error', str(e)
        threading.Thread(target=work, daemon=True, name=f'{kind}-{id}').start()
        return job

    def cancel(self, kind, id) -> bool:
        j = self.get(kind, id)
        if not j or j.state != 'running': return False
        j.cancel = True; return True

    def snapshot(self, kind):
        return {id: j.to_dict() for (k, id), j in self.jobs.items() if k == kind}


class DownloadStore:
    """token -> a file to serve once, deleted after ttl seconds."""
    def __init__(self, ttl=3600):
        self.ttl, self.items = ttl, {}

    def add(self, token, path, name):
        self.items[token] = {'path': str(path), 'name': name, 'expires': time.time() + self.ttl}

    def purge(self):
        now = time.time()
        for t, v in list(self.items.items()):
            if v['expires'] < now:
                try: os.remove(v['path'])
                except OSError: pass
                self.items.pop(t, None)

    def get(self, token):
        self.purge()
        v = self.items.get(token)
        return v if v and os.path.isfile(v['path']) else None
