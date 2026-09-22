"""Console log, SourceMod error log and performance samples."""
from tests.conftest import CONSOLE_LINES, ERROR_LINES, PERF_ROWS


def test_console_log_strips_ansi(api):
    assert api.get('/api/logs?console').json() == {'lines': ['L 09/22/2026 - 12:00:00: Log file started', 'Map loaded c2m1_highway', 'Client "桐喵Six" connected']}
    assert api.get('/api/logs').json()['lines'] == api.get('/api/logs?console').json()['lines']


def test_error_log(api):
    assert api.get('/api/logs?errors').json() == {'lines': ERROR_LINES}


def test_perf_raw_and_json(api):
    assert api.get('/api/logs?perf').json() == {'lines': PERF_ROWS}
    rows = api.get('/api/logs?perfjson').json()['rows']
    assert rows == [{'t': '12:00:00', 'humans': 1, 'cpu': 20.5, 'out_kb': 8.0, 'fps': 29.9},
                    {'t': '12:00:15', 'humans': 2, 'cpu': 30.0, 'out_kb': 10.0, 'fps': 30.1},
                    {'t': '12:00:30', 'humans': 2, 'cpu': 35.1, 'out_kb': 12.3, 'fps': 30.0}]
    assert len(CONSOLE_LINES) == 3
