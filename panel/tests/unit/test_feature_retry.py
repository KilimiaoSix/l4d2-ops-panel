from pathlib import Path

from l4d2panel.services.features import FeatureDetector
from l4d2panel.settings import Settings, Paths


class Tools:
    def available(self): return False


class Rcon:
    def __init__(self): self.calls = 0; self.error = False; self.names = ''
    def run(self, command):
        self.calls += 1
        if self.error: raise OSError('temporarily unavailable')
        return self.names


def test_transient_probe_failure_retries_without_waiting_120_seconds():
    rcon = Rcon(); detector = FeatureDetector(Settings(), rcon, Tools())
    rcon.error = True
    assert detector.get(True)['sourcemod'] is False and detector.t == 0
    rcon.error = False; rcon.names = '[SM] Listing 1 plugin:\n 01 "Private Whitelist" (1.0)'
    assert detector.get(True)['whitelist'] and rcon.calls == 2
    assert detector.get(True)['whitelist'] and rcon.calls == 2
    detector.invalidate(); detector.get(True); assert rcon.calls == 3


def test_preset_requires_runtime_and_real_data_and_failed_plugins_do_not_count(tmp_path):
    paths = Paths.from_settings(Settings(game_dir=str(tmp_path / 'game')), tmp_path)
    rcon = Rcon(); detector = FeatureDetector(Settings(), rcon, Tools(), paths=paths)
    rcon.names = '[SM] Listing 3 plugins:\n 01 "SI Preset"\n 02 "Infected Bots"\n 03 "Left 4 DHooks Direct"'
    assert not detector.get(True)['preset']
    data = paths.game / 'addons/sourcemod/data/l4dinfectedbots'; data.mkdir(parents=True)
    for name in ('coop', 'te8', 'te12', 'te16'): (data / (name + '.cfg')).touch()
    detector.invalidate(); assert detector.get(True)['preset']
    rcon.names = rcon.names.replace('02 "', '02 <Failed> "')
    detector.invalidate(); assert not detector.get(True)['preset']


def test_sourcemod_starting_up_does_not_cache_unknown_command():
    rcon = Rcon(); detector = FeatureDetector(Settings(), rcon, Tools())
    rcon.names = 'Unknown command "sm"'
    assert not detector.get(True)['sourcemod'] and detector.t == 0
    rcon.names = '[SM] Listing 1 plugin:\n 01 "Private Whitelist" (1.0)'
    assert detector.get(True)['whitelist'] and rcon.calls == 2
