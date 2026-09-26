from concurrent.futures import ThreadPoolExecutor
import json
import threading
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from l4d2panel.errors import ApiError
from l4d2panel.integrations.panel_config import ConfigConflict, ConfigError, PanelConfigFile
from l4d2panel.jobs import JobRegistry
from l4d2panel.operations import OperationGate
from l4d2panel.services.panel_restart import RestartJournal
from l4d2panel.settings import Settings


def test_job_and_restart_admission_race_has_one_winner():
    for _ in range(40):
        gate = OperationGate(); jobs = JobRegistry(gate)
        barrier = threading.Barrier(2); finish = threading.Event(); finished = threading.Event()
        def work(job):
            finish.wait(2)
            finished.set()
        def admit_job():
            barrier.wait()
            try: jobs.start('test', 'one', work); return True
            except ApiError: return False
        def admit_restart():
            barrier.wait()
            try: gate.begin_restart(); return True
            except ApiError: return False
        with ThreadPoolExecutor(2) as pool:
            a, b = pool.submit(admit_job), pool.submit(admit_restart)
            assert (a.result(), b.result()) in ((True, False), (False, True))
        finish.set()
        if not gate.pending: assert finished.wait(2)


def test_jobs_snapshot_and_thread_start_failure_release_admission(monkeypatch):
    gate = OperationGate(); jobs = JobRegistry(gate)
    def fail(*args): raise RuntimeError('cannot start')
    monkeypatch.setattr(threading.Thread, 'start', fail)
    with pytest.raises(RuntimeError): jobs.start('test', 'failed', lambda job: None)
    assert jobs.snapshot('test')['failed']['state'] == 'error'
    assert gate.active == 0
    gate.begin_restart()
    with pytest.raises(ApiError): jobs.start('test', 'pending', lambda job: None)
    assert 'pending' not in jobs.snapshot('test')


@pytest.fixture
def pending(tmp_path):
    path = tmp_path / 'panel.json'; path.write_text('{"port":8080}')
    file = PanelConfigFile(path, tmp_path); journal = RestartJournal(file)
    before = file.read()
    saved = file.save(before.revision, {'port': 8081}, Settings(), before_commit=journal.prepare)
    return file, journal, before, saved


def test_candidate_gets_one_start_attempt_then_one_rollback(pending):
    file, journal, before, saved = pending
    journal.before_start()
    assert file.read().revision == saved.snapshot.revision and journal.read()['attempts'] == 1
    journal.before_start()
    assert file.read().data == before.data and journal.read()['stage'] == 'rollback'
    with pytest.raises(ConfigError, match='停止'): journal.before_start()
    journal.healthy(before.revision)
    assert not journal.path.exists()


def test_successful_candidate_clears_journal_only_after_verified_boot(pending):
    file, journal, before, saved = pending
    journal.before_start()
    with pytest.raises(ConfigConflict): journal.healthy(before.revision)
    assert journal.path.exists()
    journal.healthy(saved.snapshot.revision)
    assert not journal.path.exists()


def test_recovery_refuses_external_edits_and_explicit_restore_is_exact(pending):
    file, journal, before, saved = pending
    file.path.write_text('{"port":8082}')
    with pytest.raises(ConfigConflict): journal.before_start()
    with pytest.raises(ConfigConflict): journal.restore()
    assert json.loads(file.path.read_text())['port'] == 8082
    file.path.write_bytes(saved.snapshot.data)
    journal.restore()
    assert file.read().data == before.data and not journal.path.exists()


def test_crash_before_configuration_commit_preserves_original(pending):
    file, journal, before, saved = pending
    file.path.write_bytes(before.data)
    journal.before_start()
    assert file.read().data == before.data and not journal.path.exists()


def test_restore_cli_reads_the_exact_pending_external_configuration(pending):
    file, journal, before, saved = pending
    source = Path(__file__).resolve().parents[2]
    entry = file.base / 'panel.py'; shutil.copy(source / 'panel.py', entry)
    env = dict(os.environ, PYTHONPATH=str(source), L4D2PANEL_CONFIG=str(file.path))
    result = subprocess.run([sys.executable, str(entry), '--restore-config'], capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr
    assert file.read().data == before.data and not journal.path.exists()
