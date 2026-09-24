"""Failure and overlapping requests at the multi-command mode boundary."""
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from l4d2panel.errors import ApiError, IntegrationError
from l4d2panel.services.game_modes import GameModes


class Audit:
    def __init__(self):
        self.rows = []

    def add(self, *args):
        self.rows.append(args)


class Rcon:
    def __init__(self):
        self.mode = 'coop'
        self.commands = []
        self.reload_error = None

    def run(self, command):
        self.commands.append(command)
        if command == 'sm_cvar mp_gamemode':
            return f'[SM] Value of cvar "mp_gamemode": "{self.mode}"'
        if command.startswith('sm_cvar mp_gamemode '):
            self.mode = command.split()[-1]
        if command.startswith('changelevel ') and self.reload_error:
            raise self.reload_error
        if command == 'status':
            return 'map : c1m1_hotel'
        return ''


def make_service(rcon, tmp_path):
    config = tmp_path / 'server.cfg'
    config.write_text('sm_cvar mp_gamemode "coop"\n')
    return GameModes(rcon, Audit(), config)


def test_disconnect_during_reload_is_uncertain_and_never_retried(tmp_path):
    rcon = Rcon()
    rcon.reload_error = IntegrationError('connection closed')
    service = make_service(rcon, tmp_path)
    result = service.switch('versus', 'admin')
    assert result['state'] == 'uncertain'
    assert rcon.commands.count('changelevel c1m1_hotel') == 1
    assert '结果待核对' in result['message']
    assert service.read()['mode'] == 'versus'
    assert service.read()['saved_mode'] == 'versus'
    assert result['persisted'] is True and result['backup']


def test_reload_timeout_still_blocks_an_immediate_second_switch(monkeypatch, tmp_path):
    clock = [0.0]
    monkeypatch.setattr('l4d2panel.services.game_modes.time.monotonic', lambda: clock[0])
    rcon = Rcon()
    original = rcon.run

    def timeout(command):
        if command.startswith('changelevel '):
            rcon.commands.append(command)
            clock[0] += 6.1
            raise IntegrationError('timed out')
        return original(command)

    rcon.run = timeout
    service = make_service(rcon, tmp_path)
    assert service.switch('versus', 'admin')['state'] == 'uncertain'
    with pytest.raises(ApiError) as caught:
        service.switch('versus', 'admin')
    assert caught.value.status == 409
    assert rcon.commands.count('changelevel c1m1_hotel') == 1


def test_no_interleaving_between_mode_requests_and_state_reads(tmp_path):
    entered, release = threading.Event(), threading.Event()
    rcon = Rcon()
    original = rcon.run

    def blocked(command):
        if command == 'sm_cvar mp_gamemode versus':
            entered.set()
            assert release.wait(5)
        return original(command)

    rcon.run = blocked
    service = make_service(rcon, tmp_path)
    with ThreadPoolExecutor(max_workers=1) as executor:
        work = executor.submit(service.switch, 'versus', 'admin')
        try:
            assert entered.wait(5)
            with pytest.raises(ApiError) as caught:
                service.switch('survival', 'admin')
            assert caught.value.status == 409
            state = service.read()
            assert state['mode'] is None and state['read_error']
        finally:
            release.set()
        assert work.result()['state'] == 'switching'
    assert 'sm_cvar mp_gamemode survival' not in rcon.commands


def test_read_failure_clears_previous_values_and_offers_catalog(tmp_path):
    rcon = Rcon()
    service = make_service(rcon, tmp_path)
    assert service.read()['mode'] == 'coop'

    def offline(command):
        raise IntegrationError('offline')

    rcon.run = offline
    state = service.read()
    assert state['mode'] is None and state['map'] is None and state['read_error'] == 'offline'
    assert len(state['modes']) == 24


def test_write_connection_failure_never_reloads_and_releases_lock(tmp_path):
    rcon = Rcon()
    original = rcon.run

    def failing_write(command):
        if command == 'sm_cvar mp_gamemode versus':
            raise IntegrationError('offline')
        return original(command)

    rcon.run = failing_write
    service = make_service(rcon, tmp_path)
    with pytest.raises(ApiError) as caught:
        service.switch('versus', 'admin')
    assert caught.value.status == 502
    assert not any(command.startswith('changelevel ') for command in rcon.commands)
    assert service.read()['read_error'] is None
    assert (tmp_path / 'server.cfg').read_text() == 'sm_cvar mp_gamemode "coop"\n'


def test_external_config_edit_is_not_overwritten_during_rollback(tmp_path):
    rcon = Rcon()
    service = make_service(rcon, tmp_path)
    original = rcon.run
    external = 'hostname "other admin edit"\nsm_cvar mp_gamemode "survival"\n'

    def edit_during_write(command):
        result = original(command)
        if command == 'sm_cvar mp_gamemode versus':
            (tmp_path / 'server.cfg').write_text(external)
        return result

    rcon.run = edit_during_write
    with pytest.raises(ApiError) as caught:
        service.switch('versus', 'admin')
    assert caught.value.status == 409
    assert '配置回滚失败' in str(caught.value)
    assert (tmp_path / 'server.cfg').read_text() == external
    assert rcon.mode == 'coop'
    assert not any(command.startswith('changelevel ') for command in rcon.commands)
