"""LinuxGSM instance script (start / stop / restart / monitor)."""
import os, re, subprocess

ANSI = re.compile(r'\x1b\[[0-9;]*m')


class Lgsm:
    def __init__(self, script: str):
        self.script = script

    def available(self) -> bool:
        return bool(self.script) and os.path.exists(self.script)

    def run(self, action: str) -> str:
        """Blocking; returns the last non-empty output line (LinuxGSM prints a status line last)."""
        env = dict(os.environ, TERM='screen', PATH='/usr/local/bin:/usr/bin:/bin')
        r = subprocess.run([self.script, action], cwd=os.path.dirname(self.script), env=env, capture_output=True, text=True, timeout=240)
        out = ANSI.sub('', r.stdout + r.stderr).strip()
        return out.splitlines()[-1] if out else f'{action} done'
