#!/usr/bin/env python3
"""Bounded CSV sampling through read-only RCON, without console reads or profiling."""
import argparse
import csv
import io
import json
import math
import os
from pathlib import Path
import re
import signal
import sys
import threading
import time

HEADER = 'time,humans,cpu%,in_bytes,out_bytes,fps,players\n'
ACTIVE_INTERVAL = 15
IDLE_INTERVAL = 60
MAX_BYTES = 4 * 1024 * 1024
ANSI = re.compile(r'\x1b\[[0-9;]*m')


def create_client(config_path):
    """Read only the existing configuration; do not construct an AppContext or DB."""
    config_path = Path(config_path).resolve()
    sys.path.insert(0, str(config_path.parent))
    from l4d2panel.integrations.rcon import RconClient
    from l4d2panel.integrations.sm_files import read_rcon_password

    config = json.loads(config_path.read_text(encoding='utf-8'))
    if config.get('server_backend', 'lgsm') != 'lgsm':
        raise ValueError('This sampler is for LinuxGSM; Docker uses panel sampling')
    def relative(value):
        path = Path(value)
        return path if path.is_absolute() else config_path.parent / path
    server_cfg = relative(config.get('game_dir', '/home/l4d2server/serverfiles/left4dead2')) / 'cfg/server.cfg'
    def password():
        # Re-read server.cfg to support password changes without restarting the sampler.
        value = config.get('rcon_password') or read_rcon_password(server_cfg)
        if not value:
            raise ValueError('No RCON password configured')
        return value
    password()  # Fail early without sending repeated unauthenticated requests.
    output = relative(os.environ.get('OUT') or config.get('perf_csv', '/home/l4d2server/log/perf-samples.csv'))
    return RconClient(config.get('rcon_host', '127.0.0.1'), config.get('rcon_port', 27015), password, timeout=2), output


def sample(client, include_empty=False):
    from l4d2panel.integrations.srcds import STATUS_SUMMARY
    status = STATUS_SUMMARY.search(ANSI.sub('', client.run('status')))
    if status is None:
        raise ValueError('Unrecognized status')
    humans = int(status.group(1))
    if not humans and not include_empty:
        return None
    for line in reversed(ANSI.sub('', client.run('stats')).splitlines()):
        columns = line.split()
        if len(columns) != 7:
            continue
        try:
            values = [float(value) for value in columns]
        except ValueError:
            continue
        if not all(math.isfinite(value) and value >= 0 for value in values):
            continue
        if not values[6].is_integer():
            continue
        return [time.strftime('%H:%M:%S'), humans, values[0], values[1], values[2], values[5], int(values[6])]
    raise ValueError('Unrecognized stats')


def append_sample(path, row, max_bytes=MAX_BYTES):
    buffer = io.StringIO(newline='')
    csv.writer(buffer, lineterminator='\n').writerow(row)
    line = buffer.getvalue()
    if len((HEADER + line).encode()) > max_bytes:
        raise ValueError('Sample exceeds file size limit')
    path = Path(path)
    if path.exists() and path.stat().st_size + len(line.encode()) > max_bytes:
        previous = path.with_name(path.name + '.1')
        if previous.exists():
            previous.replace(path.with_name(path.name + '.2'))
        path.replace(previous)
    is_empty = not path.exists() or path.stat().st_size == 0
    with path.open('a', encoding='utf-8', newline='') as target:
        if is_empty:
            target.write(HEADER)
        target.write(line)


def main():
    import fcntl  # Linux process lock, held for the lifetime of the open descriptor.
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--once', action='store_true', help='Read one sample and exit; shares the normal singleton lock')
    parser.add_argument('--include-empty', action='store_true', help='With --once, permit one empty-server stats query for verification')
    args = parser.parse_args()
    if args.include_empty and not args.once:
        parser.error('--include-empty requires --once')
    os.umask(0o027)
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    try:
        client, output = create_client(args.config)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.with_name(output.name + '.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                print('Sampler already running for this CSV', file=sys.stderr, flush=True)
                return 1
            last_error = float('-inf')
            while not stop.is_set():
                started = time.monotonic()
                try:
                    row = sample(client, include_empty=args.include_empty)
                    if row is not None:
                        append_sample(output, row)
                    delay = ACTIVE_INTERVAL if row is not None and row[1] else IDLE_INTERVAL
                except Exception as exc:
                    # Log only a class name: exception text may contain sensitive configuration.
                    if started - last_error >= 600:
                        print(f'Sample unavailable ({type(exc).__name__}); retry in {IDLE_INTERVAL}s', file=sys.stderr, flush=True)
                        last_error = started
                    if args.once:
                        return 1
                    delay = IDLE_INTERVAL
                if args.once:
                    return 0
                stop.wait(max(0, delay - (time.monotonic() - started)))
    except Exception as exc:
        print(f'Sampler startup failed ({type(exc).__name__})', file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
