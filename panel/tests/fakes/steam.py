"""Fake Steam for workshop tests: the Web API the panel queries, a CDN that serves the item file with Range
support (optionally failing the first N range requests or holding them until released), and the
steamcommunity vanity-URL XML used to resolve custom profile links.

`add_item(pubid, data, ...)` registers a published file and its bytes; `items[pubid]` is the JSON the
API returns, so tests can override fields (file_type=2 for a collection, consumer_app_id, ...).
"""
import json, re, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs


class FakeSteam:
    def __init__(self):
        self.items, self.files, self.vanity = {}, {}, {}
        self.fail_ranges = {}          # pubid -> number of range requests still to cut short
        self.hold = threading.Event()  # while set, range requests block (lets a test cancel a download mid-flight)
        self.hold.clear()
        self.requests = []             # (method, path, Range header)
        fake = self
        class H(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'
            def log_message(self, *a): pass
            def _json(self, obj, code=200):
                b = json.dumps(obj).encode(); self.send_response(code); self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(b))); self.end_headers(); self.wfile.write(b)
            def do_POST(self):
                fake.requests.append(('POST', self.path, None))
                body = parse_qs(self.rfile.read(int(self.headers.get('Content-Length', 0) or 0)).decode())
                if self.path.startswith('/ISteamRemoteStorage/GetPublishedFileDetails/'):
                    pid = body.get('publishedfileids[0]', [''])[0]
                    item = fake.items.get(pid) or {'publishedfileid': pid, 'result': 9}
                    return self._json({'response': {'result': 1, 'resultcount': 1, 'publishedfiledetails': [item]}})
                self.send_error(404)
            def do_GET(self):
                rng = self.headers.get('Range'); fake.requests.append(('GET', self.path, rng))
                m = re.fullmatch(r'/files/([^/?]+)', self.path)
                if m and m.group(1) in fake.files:
                    pid = m.group(1); data = fake.files[pid]
                    while fake.hold.is_set(): time.sleep(0.05)
                    if not rng: return self.send_error(400, 'Range required')
                    a, b = re.fullmatch(r'bytes=(\d+)-(\d+)', rng).groups(); a, b = int(a), min(int(b), len(data) - 1)
                    chunk = data[a:b + 1]
                    if fake.fail_ranges.get(pid, 0) > 0:      # cut the connection after half the range, like a flaky CDN edge
                        fake.fail_ranges[pid] -= 1; chunk = chunk[:len(chunk) // 2]
                        self.send_response(206); self.send_header('Content-Range', f'bytes {a}-{b}/{len(data)}'); self.send_header('Content-Length', str(b - a + 1))
                        self.end_headers(); self.wfile.write(chunk); self.wfile.flush(); self.connection.close(); return
                    self.send_response(206); self.send_header('Content-Type', 'application/octet-stream'); self.send_header('Content-Range', f'bytes {a}-{b}/{len(data)}')
                    self.send_header('Content-Length', str(len(chunk))); self.end_headers(); self.wfile.write(chunk); return
                m = re.fullmatch(r'/id/([^/?]+)/\?xml=1', self.path)
                if m:
                    id64 = fake.vanity.get(m.group(1)); b = (f'<profile><steamID64>{id64}</steamID64></profile>' if id64 else '<response><error>The specified profile could not be found.</error></response>').encode()
                    self.send_response(200); self.send_header('Content-Type', 'text/xml'); self.send_header('Content-Length', str(len(b))); self.end_headers(); self.wfile.write(b); return
                self.send_error(404)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), H); self.server.daemon_threads = True
        self.base = f'http://127.0.0.1:{self.server.server_address[1]}'
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def add_item(self, pubid, data, filename='campaign.vpk', title='A Campaign', **fields):
        self.files[pubid] = data
        item = {'publishedfileid': pubid, 'result': 1, 'consumer_app_id': 550, 'file_type': 0, 'filename': filename, 'file_size': len(data),
                'file_url': f'{self.base}/files/{pubid}', 'title': title, 'hcontent_file': '1234'}
        item.update(fields); self.items[pubid] = item; return item

    def range_requests(self, pubid):
        return [r for r in self.requests if r[0] == 'GET' and r[1] == f'/files/{pubid}']

    def stop(self):
        self.hold.clear(); self.server.shutdown(); self.server.server_close()
