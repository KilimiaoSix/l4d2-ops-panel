#!/usr/bin/env python3
"""Regression check for H.log_message in panel/panel.py (no server, no sockets).

http.server's own send_error() logs through log_error("code %d, message %s", HTTPStatus, msg) and a read
timeout logs log_error("Request timed out: %r", exc) — in both cases args[0] is not a str. The panel's
/api/status access-log filter used to do `'/api/status' in args[0]` unconditionally, which raised
TypeError there and dumped a traceback into the journal instead of the real error (seen live on
2026-09-19 and 2026-09-22 for malformed request lines).

Imports the real panel.py with a throwaway config + sqlite DB, builds handler instances without a socket
and drives handle_one_request() / send_error() / log_error() / log_request() the way http.server does.

用法: python3 tools/check_log_message.py   （退出码 0 = 全部通过）
"""
import contextlib, importlib.util, io, json, os, sys, tempfile
from http import HTTPStatus

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PANEL = os.path.join(ROOT, 'panel', 'panel.py')


def load_panel(tmp):
    conf = os.path.join(tmp, 'panel.json')
    with open(conf, 'w', encoding='utf-8') as f:
        json.dump({'password': 'check-only', 'db': os.path.join(tmp, 'panel.db')}, f)
    os.environ['L4D2PANEL_CONFIG'] = conf
    spec = importlib.util.spec_from_file_location('panel_under_test', PANEL)
    mod = importlib.util.module_from_spec(spec)
    with contextlib.redirect_stdout(io.StringIO()):      # hides the "[panel] seeded owner account" line
        spec.loader.exec_module(mod)
    return mod


def handler(cls, raw_request=b''):
    """A handler instance without a socket: just the state handle_one_request() / log_*() touch."""
    h = cls.__new__(cls)
    h.client_address = ('127.0.0.1', 54321)
    h.rfile = io.BytesIO(raw_request)
    h.wfile = io.BytesIO()
    return h


def logged(fn):
    """Run fn() and return what it wrote to stderr (where BaseHTTPRequestHandler.log_message writes)."""
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        fn()
    return buf.getvalue()


def main():
    failures = []

    def check(name, fn, expect):
        """fn() must not raise and its stderr output must satisfy expect(output)."""
        try:
            out = logged(fn)
            ok, detail = expect(out), repr(out)
        except Exception as e:                       # the bug: TypeError: argument of type 'HTTPStatus' is not iterable
            ok, detail = False, f'{type(e).__name__}: {e}'
        print(('PASS  ' if ok else 'FAIL  ') + name + ('' if ok else f'\n      -> {detail}'))
        if not ok:
            failures.append(name)

    with tempfile.TemporaryDirectory() as tmp:
        H = load_panel(tmp).H

        # 1. the live-server case: bad request line -> parse_request() -> send_error() -> log_error(HTTPStatus)
        h = handler(H, b'GET / HTTP/9.9\r\n')
        check('unsupported HTTP version is logged, no traceback', h.handle_one_request,
              lambda out: 'code 505, message Invalid HTTP version (9.9)' in out)

        # 2. send_error() with an HTTPStatus and a message, as http.server calls it for a malformed request
        h = handler(H)
        h.request_version, h.requestline, h.command = 'HTTP/1.1', 'garbage', 'GET'
        check('send_error(HTTPStatus.BAD_REQUEST) does not raise',
              lambda: h.send_error(HTTPStatus.BAD_REQUEST, 'Bad request syntax'),
              lambda out: 'code 400, message Bad request syntax' in out)

        # 3. read-timeout path: log_error("Request timed out: %r", exc) — args[0] is an exception
        h = handler(H)
        check('log_error with an exception argument does not raise',
              lambda: h.log_error('Request timed out: %r', TimeoutError('timed out')),
              lambda out: "Request timed out: TimeoutError('timed out')" in out)

        # 4. the filter itself must keep working: /api/status polls stay out, everything else stays in
        h = handler(H)
        h.requestline = 'GET /api/status HTTP/1.1'
        check('/api/status access log is suppressed', lambda: h.log_request(200), lambda out: out == '')
        h.requestline = 'GET /api/players HTTP/1.1'
        check('other access logs are still printed', lambda: h.log_request(200),
              lambda out: '"GET /api/players HTTP/1.1" 200' in out)

        # 5. a message with no arguments at all
        h = handler(H)
        check('log_message without arguments still works', lambda: h.log_message('plain message'),
              lambda out: 'plain message' in out)

    if failures:
        print(f'{len(failures)} check(s) FAILED')
        return 1
    print('all checks passed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
