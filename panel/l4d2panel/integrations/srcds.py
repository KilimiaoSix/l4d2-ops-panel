"""Parsing of srcds `status` output. (2026-09-22) real L4D2 rows: humans carry an extra number between userid
and name, bots have no connected/ping/loss at all —
    # 26 1 "name" STEAM_1:0:x 05:40 99 0 active 30000 ip:port     /     #27 "Coach" BOT active
Bots stay out of the player list; their count comes from the `players : N humans, M bots (K max)` line."""
import re, subprocess

STATUS_ROW = re.compile(r'^#\s*(\d+)\s+(?:\d+\s+)?"(.*)"\s+(STEAM_\S+)\s+(\S+)\s+(\d+)\s+(\d+)\s+(\w+)')
STATUS_SUMMARY = re.compile(r'^players\s*:\s*(\d+)\s+humans?,\s*(\d+)\s+bots?\s*\((\d+)\s+max\)', re.M)
STATUS_MAP = re.compile(r'^map\s*:\s*(\S+)', re.M)


def parse_status(out: str):
    """-> (human rows, {'humans', 'bots', 'max', 'map'}); unknown counts are 0, unknown map ''."""
    rows = [dict(zip(('userid', 'name', 'steamid', 'time', 'ping', 'loss', 'state'), m.groups())) for m in map(STATUS_ROW.match, out.splitlines()) if m]
    s = STATUS_SUMMARY.search(out); mm = STATUS_MAP.search(out)
    return rows, {'humans': int(s.group(1)) if s else len(rows), 'bots': int(s.group(2)) if s else 0, 'max': int(s.group(3)) if s else 0, 'map': mm.group(1) if mm else ''}


def srcds_running() -> bool:
    """Is a srcds_linux process alive on this host? (the panel runs on the game host)"""
    try:
        return subprocess.run(['pgrep', '-f', 'srcds_linux'], capture_output=True).returncode == 0
    except OSError:
        return False
