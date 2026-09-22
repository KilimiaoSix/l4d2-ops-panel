#!/usr/bin/env python3
"""Offline tests for the panel's campaign install paths (upload vpk / zip, Steam Workshop download + search).

Runs panel.py against a scratch config, a scratch game_dir and a fake Steam Web API + CDN on localhost,
so nothing here touches a real server. Run:  python3 tools/test_panel.py
"""
import http.client, importlib.util, io, json, os, shutil, struct, sys, tempfile, threading, unittest, zipfile
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix='l4d2panel-test-')
ADDONS = os.path.join(TMP, 'game', 'addons')
STEAM_KEY = 'testkey'


# ---- minimal VPK v2 writer (single-file addon layout, what L4D2 loads from addons/) ----
def make_vpk(paths):
    """Build a VPK v2 whose directory tree lists `paths` (e.g. 'maps/c1m1_x.bsp'); file bodies are 4 bytes each."""
    tree = {}
    for p in paths:
        d, _, fn = p.rpartition('/'); name, _, ext = fn.rpartition('.')
        tree.setdefault(ext, {}).setdefault(d or ' ', []).append(name)
    out, data, off = io.BytesIO(), b'', 0
    for ext, dirs in tree.items():
        out.write(ext.encode() + b'\0')
        for d, names in dirs.items():
            out.write(d.encode() + b'\0')
            for n in names:
                out.write(n.encode() + b'\0'); out.write(struct.pack('<IHHIIH', 0, 0, 0x7fff, off, 4, 0xffff)); data += b'DATA'; off += 4
            out.write(b'\0')
        out.write(b'\0')
    out.write(b'\0'); tree_b = out.getvalue()
    return struct.pack('<IIIIIII', 0x55aa1234, 2, len(tree_b), len(data), 0, 0, 0) + tree_b + data

MAP_VPK = make_vpk(['maps/c1m1_test.bsp', 'maps/c1m2_test.bsp', 'missions/testcamp.txt', 'materials/vgui/x.vtf'])
SKIN_VPK = make_vpk(['materials/models/survivors/coach.vtf', 'models/survivors/coach.mdl', 'addoninfo.txt'])


# ---- fake Steam Web API + UGC CDN ----
QUERIES = []   # QueryFiles requests the panel made: list of {param: [values]}
ITEMS = {'100100100': ('Test Campaign', 'testcamp.vpk', MAP_VPK), '100200200': ('Coach Skin', 'coach.vpk', SKIN_VPK)}
class FakeSteam(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _json(self, obj, code=200):
        b = json.dumps(obj).encode(); self.send_response(code); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        u = urlparse(self.path); qs = parse_qs(u.query)
        if u.path == '/IPublishedFileService/QueryFiles/v1/':
            QUERIES.append(qs)
            if qs.get('key') != [STEAM_KEY]:
                b = b'<html><body>Access is denied</body></html>'; self.send_response(403); self.send_header('Content-Length', str(len(b))); self.end_headers(); self.wfile.write(b); return
            if qs.get('page') == ['2']: return self._json({'response': {'total': 57, 'publishedfiledetails': []}})
            return self._json({'response': {'total': 57, 'publishedfiledetails': [
                {'result': 1, 'publishedfileid': '2396847377', 'title': '广州增城 （Zengcheng）Lv8.06', 'file_size': '867196936', 'preview_url': 'https://images.example/zc.jpg',
                 'subscriptions': 1553836, 'time_updated': 1782860476, 'tags': [{'tag': 'Campaigns'}, {'tag': 'Single Player'}, {'tag': 'Co-op'}], 'vote_data': {'score': 0.91}, 'short_description': 'A campaign'},
                {'result': 1, 'publishedfileid': '100100100', 'title': 'Test Campaign', 'file_size': str(len(MAP_VPK)), 'subscriptions': 12, 'tags': [{'tag': 'Campaigns'}]},
                {'result': 9, 'publishedfileid': '9999'}]}})
        if u.path.startswith('/ugc/'):
            body = ITEMS[u.path[5:]][2]; rng = self.headers.get('Range')
            if rng:
                s, e = rng.replace('bytes=', '').split('-'); s = int(s); e = int(e) if e else len(body) - 1; part = body[s:e + 1]
                self.send_response(206); self.send_header('Content-Range', f'bytes {s}-{e}/{len(body)}'); self.send_header('Content-Length', str(len(part))); self.end_headers(); self.wfile.write(part); return
            self.send_response(200); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body); return
        self.send_response(404); self.end_headers()
    def do_POST(self):
        n = int(self.headers.get('Content-Length', 0)); qs = parse_qs(self.rfile.read(n).decode())
        if urlparse(self.path).path == '/ISteamRemoteStorage/GetPublishedFileDetails/v1/':
            pid = qs.get('publishedfileids[0]', [''])[0]; it = ITEMS.get(pid)
            if not it: return self._json({'response': {'publishedfiledetails': [{'publishedfileid': pid, 'result': 9}]}})
            return self._json({'response': {'publishedfiledetails': [{'publishedfileid': pid, 'result': 1, 'consumer_app_id': 550, 'file_type': 0, 'title': it[0], 'filename': it[1],
                                                                       'file_size': len(it[2]), 'file_url': STEAM_BASE + '/ugc/' + pid, 'hcontent_file': '1'}]}})
        self.send_response(404); self.end_headers()

steam_srv = ThreadingHTTPServer(('127.0.0.1', 0), FakeSteam); threading.Thread(target=steam_srv.serve_forever, daemon=True).start()
STEAM_BASE = f'http://127.0.0.1:{steam_srv.server_address[1]}'

# ---- import panel.py against the scratch config ----
os.makedirs(ADDONS); os.makedirs(os.path.join(TMP, 'game', 'cfg'))
CONF_FILE = os.path.join(TMP, 'panel.json')
with open(CONF_FILE, 'w') as f:
    json.dump({'game_dir': os.path.join(TMP, 'game'), 'db': os.path.join(TMP, 'panel.db'), 'rcon_host': '127.0.0.1', 'rcon_port': 1, 'rcon_password': 'x',
               'lgsm_script': '', 'console_log': '', 'perf_csv': '', 'depotdownloader': '', 'steam_api_base': STEAM_BASE, 'steam_api_key': STEAM_KEY,
               'workshop_connections': 2, 'workshop_retries': 1, 'protected_addons': ['admin_system.vpk']}, f)
os.environ['L4D2PANEL_CONFIG'] = CONF_FILE
spec = importlib.util.spec_from_file_location('panel', os.path.join(ROOT, 'panel', 'panel.py')); panel = importlib.util.module_from_spec(spec); spec.loader.exec_module(panel)
panel.WS_TMP = os.path.join(TMP, 'workshop_tmp'); panel.H.log_message = lambda *a: None

srv = ThreadingHTTPServer(('127.0.0.1', 0), panel.H); threading.Thread(target=srv.serve_forever, daemon=True).start()
PORT = srv.server_address[1]
COOKIE = {}
def req(method, path, body=None, headers=None):
    c = http.client.HTTPConnection('127.0.0.1', PORT, timeout=60); h = dict(headers or {})
    if COOKIE: h['Cookie'] = COOKIE['v']
    if isinstance(body, (dict, list)): body = json.dumps(body).encode(); h['Content-Type'] = 'application/json'
    c.request(method, path, body=body, headers=h); r = c.getresponse(); data = r.read(); c.close()
    sc = r.getheader('Set-Cookie')
    if sc: COOKIE['v'] = sc.split(';')[0]
    try: return r.status, json.loads(data)
    except ValueError: return r.status, data
def make_zip(members):
    b = io.BytesIO()
    with zipfile.ZipFile(b, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, data in members.items(): z.writestr(name, data)
    return b.getvalue()
def write_tmp(name, data):
    p = os.path.join(ADDONS, name + '.uploading')
    with open(p, 'wb') as f: f.write(data)
    return p


class PanelTests(unittest.TestCase):
    def setUp(self):
        for f in os.listdir(ADDONS): os.remove(os.path.join(ADDONS, f))
        shutil.rmtree(panel.WS_TMP, ignore_errors=True); panel.JOBS.clear(); del QUERIES[:]

    # -- computation: what a vpk holds --
    def test_vpk_summary_reports_maps_mission_and_contents(self):
        p = write_tmp('camp.vpk', MAP_VPK); s = panel.vpk_summary(p)
        self.assertEqual(s['maps'], ['c1m1_test', 'c1m2_test']); self.assertEqual(s['mission'], 'testcamp'); self.assertIn('maps/', s['kind'])

    # -- install gate: only campaign vpks reach addons/ --
    def test_install_vpk_accepts_campaign(self):
        info = panel.install_vpk(write_tmp('camp.vpk', MAP_VPK), 'camp.vpk')
        self.assertEqual(info['maps'], ['c1m1_test', 'c1m2_test']); self.assertEqual(os.listdir(ADDONS), ['camp.vpk'])
    def test_install_vpk_rejects_vpk_without_maps_and_deletes_it(self):
        with self.assertRaises(ValueError) as cm: panel.install_vpk(write_tmp('coach.vpk', SKIN_VPK), 'coach.vpk')
        self.assertIn('maps/*.bsp', str(cm.exception)); self.assertIn('materials/', str(cm.exception)); self.assertEqual(os.listdir(ADDONS), [])
    def test_install_vpk_rejects_non_vpk_bytes(self):
        with self.assertRaises(ValueError) as cm: panel.install_vpk(write_tmp('x.vpk', b'PK\x03\x04 not a vpk'), 'x.vpk')
        self.assertIn('VPK', str(cm.exception)); self.assertEqual(os.listdir(ADDONS), [])
    def test_install_vpk_refuses_to_overwrite_protected_addon(self):
        with self.assertRaises(ValueError) as cm: panel.install_vpk(write_tmp('admin_system.vpk', MAP_VPK), 'admin_system.vpk')
        self.assertIn('受保护', str(cm.exception)); self.assertEqual(os.listdir(ADDONS), [])

    # -- zip (what gamemaps.com serves): every campaign vpk inside gets installed, the rest is reported --
    def test_install_zip_installs_map_vpks_and_skips_the_rest(self):
        z = write_tmp('pack.zip', make_zip({'Some Campaign/camp.vpk': MAP_VPK, 'Some Campaign/coach.vpk': SKIN_VPK, 'readme.txt': b'hi', '__MACOSX/._camp.vpk': b'junk'}))
        r = panel.install_zip(z)
        self.assertEqual([a['name'] for a in r['installed']], ['camp.vpk']); self.assertEqual(r['skipped'][0]['name'], 'coach.vpk'); self.assertIn('maps/*.bsp', r['skipped'][0]['reason'])
        self.assertEqual(sorted(os.listdir(ADDONS)), ['camp.vpk'])   # the zip and the rejected vpk are gone
    def test_install_zip_without_any_vpk_names_what_it_found(self):
        with self.assertRaises(ValueError) as cm: panel.install_zip(write_tmp('pack.zip', make_zip({'readme.txt': b'hi', 'shot.jpg': b'x'})))
        self.assertIn('readme.txt', str(cm.exception)); self.assertEqual(os.listdir(ADDONS), [])
    def test_install_zip_with_only_non_map_vpks_fails_with_reasons(self):
        with self.assertRaises(ValueError) as cm: panel.install_zip(write_tmp('pack.zip', make_zip({'coach.vpk': SKIN_VPK})))
        self.assertIn('coach.vpk', str(cm.exception)); self.assertIn('maps/*.bsp', str(cm.exception)); self.assertEqual(os.listdir(ADDONS), [])
    def test_install_zip_rejects_corrupt_archive(self):
        with self.assertRaises(ValueError) as cm: panel.install_zip(write_tmp('pack.zip', b'Rar!\x1a\x07\x00 not a zip'))
        self.assertIn('zip', str(cm.exception)); self.assertEqual(os.listdir(ADDONS), [])

    # -- HTTP: the upload route takes .vpk and .zip, nothing else --
    def test_upload_route(self):
        st, j = req('GET', '/api/setup')
        if j.get('needed'): st, j = req('POST', '/api/setup', {'password': 'test1234'}); self.assertEqual(st, 200, j)
        st, j = req('POST', '/api/upload?name=pack.zip', make_zip({'a/camp.vpk': MAP_VPK, 'a/coach.vpk': SKIN_VPK}))
        self.assertEqual(st, 200, j); self.assertEqual([a['name'] for a in j['installed']], ['camp.vpk']); self.assertEqual(len(j['skipped']), 1); self.assertIn('camp.vpk', os.listdir(ADDONS))
        st, j = req('POST', '/api/upload?name=coach.vpk', SKIN_VPK)
        self.assertEqual(st, 400); self.assertIn('maps/*.bsp', j['error']); self.assertNotIn('coach.vpk', os.listdir(ADDONS))
        st, j = req('POST', '/api/upload?name=camp.rar', b'Rar!')
        self.assertEqual(st, 400); self.assertIn('.zip', j['error'])
        st, j = req('POST', '/api/upload?name=camp2.vpk', MAP_VPK)
        self.assertEqual(st, 200, j); self.assertEqual(j['installed'][0]['maps'], ['c1m1_test', 'c1m2_test'])

    # -- HTTP: Workshop search goes to IPublishedFileService/QueryFiles with the campaign tag --
    def test_workshop_search_route(self):
        st, j = req('GET', '/api/setup')
        if j.get('needed'): req('POST', '/api/setup', {'password': 'test1234'})
        st, j = req('GET', '/api/workshop_search?q=helm')
        self.assertEqual(st, 200, j); self.assertEqual(j['total'], 57); self.assertEqual([i['id'] for i in j['items']], ['2396847377', '100100100'])   # result!=1 rows dropped
        it = j['items'][0]
        self.assertEqual(it['size_mb'], 827.0); self.assertEqual(it['subs'], 1553836); self.assertEqual(it['tags'], ['Single Player', 'Co-op']); self.assertEqual(it['preview'], 'https://images.example/zc.jpg')
        q = QUERIES[-1]
        self.assertEqual(q['appid'], ['550']); self.assertEqual(q['requiredtags[0]'], ['Campaigns']); self.assertEqual(q['query_type'], ['12']); self.assertEqual(q['search_text'], ['helm']); self.assertEqual(q['page'], ['1'])
        st, j = req('GET', '/api/workshop_search?q=&page=2')
        self.assertEqual(st, 200, j); self.assertEqual(j['items'], []); self.assertEqual(j['page'], 2)
        q = QUERIES[-1]; self.assertEqual(q['query_type'], ['9']); self.assertNotIn('search_text', q); self.assertEqual(q['page'], ['2'])   # empty query = most subscribed campaigns
    def test_workshop_search_needs_a_key(self):
        st, j = req('GET', '/api/setup')
        if j.get('needed'): req('POST', '/api/setup', {'password': 'test1234'})
        old = panel.CONF['steam_api_key']
        try:
            panel.CONF['steam_api_key'] = ''
            self.assertFalse(panel.features(False)['workshop_search'])
            st, j = req('GET', '/api/workshop_search?q=x'); self.assertEqual(st, 400); self.assertIn('steam_api_key', j['error'])
            panel.CONF['steam_api_key'] = 'wrong'
            st, j = req('GET', '/api/workshop_search?q=x'); self.assertGreaterEqual(st, 400); self.assertIn('Key', j['error']); self.assertNotIn('wrong', j['error'])
        finally:
            panel.CONF['steam_api_key'] = old
        self.assertTrue(panel.features(False)['workshop_search'])

    # -- Workshop download: same gate, the whole real path (Web API -> ranged CDN download -> install) --
    def test_workshop_job_installs_campaign(self):
        panel.workshop_job('100100100'); j = panel.JOBS['100100100']
        self.assertEqual(j['state'], 'done', j['msg']); self.assertEqual(j['files'], ['testcamp.vpk']); self.assertEqual(os.listdir(ADDONS), ['testcamp.vpk'])
    def test_workshop_job_rejects_non_map_item(self):
        panel.workshop_job('100200200'); j = panel.JOBS['100200200']
        self.assertEqual(j['state'], 'error'); self.assertIn('maps/*.bsp', j['msg']); self.assertNotIn('已保留', j['msg'])
        self.assertEqual(os.listdir(ADDONS), []); self.assertFalse(os.path.exists(os.path.join(panel.WS_TMP, '1002.part')))


if __name__ == '__main__':
    try:
        unittest.main(verbosity=2)
    finally:
        for s_ in (srv, steam_srv): s_.shutdown(); s_.server_close()
        shutil.rmtree(TMP, ignore_errors=True)
