from l4d2panel.integrations.srcds import parse_status
from tests.fakes.game import HUMANS, STATUS_BUSY, STATUS_IDLE


def test_busy_server():
    rows, summary = parse_status(STATUS_BUSY)
    assert rows == HUMANS                                           # bots, the header and #end are not players
    assert summary == {'humans': 2, 'bots': 5, 'max': 12, 'map': 'c2m1_highway'}


def test_hibernating_server():
    assert parse_status(STATUS_IDLE) == ([], {'humans': 0, 'bots': 0, 'max': 12, 'map': 'c2m1_highway'})


def test_reply_without_header_lines():
    trunc = '\n'.join(STATUS_BUSY.splitlines()[6:])
    assert parse_status(trunc) == (HUMANS, {'humans': 2, 'bots': 0, 'max': 0, 'map': ''})
