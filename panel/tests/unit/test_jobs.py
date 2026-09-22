import threading, time

import pytest

from l4d2panel.jobs import DownloadStore, JobRegistry


def wait(pred, timeout=5):
    end = time.time() + timeout
    while not pred():
        assert time.time() < end, 'timed out'
        time.sleep(0.01)


def test_job_lifecycle_and_snapshot():
    reg = JobRegistry(); gate = threading.Event()
    def work(job):
        job.name = 'x.vpk'; job.total = 10; gate.wait(5); job.done = 10; job.files = ['x.vpk']
    j = reg.start('workshop', '1', work, initial_msg='starting')
    assert j.state == 'running' and reg.is_running('workshop', '1')
    with pytest.raises(RuntimeError): reg.start('workshop', '1', work)
    snap = reg.snapshot('workshop')['1']
    assert snap['state'] == 'running' and snap['msg'] == 'starting' and 'cancel' not in snap
    gate.set(); wait(lambda: j.state == 'done')
    assert reg.snapshot('workshop')['1'] == {'state': 'done', 'msg': 'starting', 'files': ['x.vpk'], 'name': 'x.vpk', 'title': '', 'done': 10, 'total': 10, 'speed': 0.0}
    assert reg.snapshot('zip') == {}
    gate.clear(); reg.start('workshop', '1', work); assert reg.is_running('workshop', '1')   # finished jobs can be restarted
    gate.set()


def test_exception_becomes_error_state():
    reg = JobRegistry()
    def boom(job): raise RuntimeError('no disk')
    j = reg.start('zip', 't', boom); wait(lambda: j.state != 'running')
    assert j.state == 'error' and j.msg == 'no disk'


def test_cancel_flag():
    reg = JobRegistry(); seen = {}
    def work(job):
        wait(lambda: job.cancel); seen['cancelled'] = True
    j = reg.start('workshop', '9', work)
    assert reg.cancel('workshop', '9') is True and reg.snapshot('workshop')['9']['cancel'] is True
    wait(lambda: j.state == 'done'); assert seen['cancelled']
    assert reg.cancel('workshop', '9') is False and reg.cancel('workshop', 'nope') is False


def test_download_store_expiry(tmp_path):
    f = tmp_path / 'a.zip'; f.write_bytes(b'zip')
    ds = DownloadStore(ttl=0.2); ds.add('tok', f, 'a.zip')
    assert ds.get('tok')['name'] == 'a.zip' and ds.get('other') is None
    time.sleep(0.3)
    assert ds.get('tok') is None and not f.exists()
