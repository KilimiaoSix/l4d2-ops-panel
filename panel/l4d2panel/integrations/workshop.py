"""Steam Workshop file transfer (2026-09-22): parallel ranged HTTP with per-range retry and on-disk resume, plus
the DepotDownloader fallback for depot-based items.

L4D2 workshop items are plain UGC files on an Akamai CDN. From a Chinese cloud host one connection gets anywhere
between ~1 and 20 Mbps depending on the edge DNS hands out, and DepotDownloader fetched the whole file with ONE GET
(no retry, no resume), so 800 MB campaigns kept dying. This downloads 8 MB ranges over several connections, retries
each range on its own and records finished ranges in <dest>.parts.json, so a failed or cancelled job continues
where it stopped. Progress goes into a jobs.Job (done / total / speed / msg)."""
import json, os, subprocess, threading, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

CHUNK = 8 * 1048576
CANCELLED = '已取消'


class Cancelled(Exception):
    pass


def _range_get(url, start, end, fd, stop, bump, min_rate=0, user_agent='l4d2panel'):
    """GET one byte range straight into fd at its offset; bump(n) reports bytes as they land. Raises unless the whole range arrived."""
    req = urllib.request.Request(url, headers={'Range': f'bytes={start}-{end}', 'User-Agent': user_agent})
    with urllib.request.urlopen(req, timeout=30) as r:
        if r.status != 206: raise RuntimeError(f'HTTP {r.status}（CDN 不支持 Range）')
        want = end - start + 1; got = 0; t0 = time.time()
        while got < want:
            if stop(): raise Cancelled()
            piece = r.read(min(262144, want - got))
            if not piece: raise RuntimeError(f'连接提前断开（{got}/{want} 字节）')
            os.pwrite(fd, piece, start + got); got += len(piece); bump(len(piece))
            el = time.time() - t0
            if min_rate and el > 15 and got / el < min_rate: raise RuntimeError(f'太慢（{got / el / 1024:.0f} KB/s），换个连接重试')


def download_ranged(url, size, dest, job, connections, retries, log):
    """Parallel ranged download of url into dest; progress in job; log(msg) records retries. Raises on failure / cancel."""
    state_path = dest + '.parts.json'; n = (size + CHUNK - 1) // CHUNK
    def csize(i): return min(size, (i + 1) * CHUNK) - i * CHUNK
    done = set()
    try:
        st = json.load(open(state_path))
        if st.get('url') == url and st.get('size') == size and os.path.getsize(dest) == size: done = set(int(i) for i in st['done'])
    except Exception: pass
    if not done:
        with open(dest, 'wb') as f: f.truncate(size)
    job.total, job.done, job.speed = size, sum(csize(i) for i in done), 0.0
    lock = threading.Lock(); hist = [(time.time(), job.done)]; meta = {'t': 0.0, 'err': ''}
    def stop(): return bool(job.cancel or meta['err'])
    def bump(nb):
        with lock:
            job.done += nb; now = time.time(); hist.append((now, job.done))
            while len(hist) > 2 and now - hist[0][0] > 15: hist.pop(0)
            if now - meta['t'] >= 0.5:
                meta['t'] = now; job.speed = max(0.0, (job.done - hist[0][1]) / max(0.001, now - hist[0][0]))
                job.msg = f'{job.name} {job.done / 1048576:.1f}/{size / 1048576:.1f} MB ({100 * job.done // size}%) {job.speed / 1048576:.1f} MB/s'
    fd = os.open(dest, os.O_RDWR)
    try:
        def fetch(i):
            s = i * CHUNK; e = s + csize(i) - 1; last = ''
            for attempt in range(1, int(retries) + 1):
                if stop(): return
                acc = {'n': 0}
                def bump_acc(nb): acc['n'] += nb; bump(nb)
                try:
                    _range_get(url, s, e, fd, stop, bump_acc, min_rate=150 * 1024 if attempt <= 2 else 0)
                    with lock:
                        done.add(i); tmp_ = state_path + '.tmp'
                        with open(tmp_, 'w') as f: json.dump({'url': url, 'size': size, 'done': sorted(done)}, f)
                        os.replace(tmp_, state_path)
                    return
                except Cancelled:
                    bump(-acc['n']); return
                except Exception as ex:
                    last = str(ex); bump(-acc['n'])   # this range will be fetched again from its start
                    if stop(): return
                    log(f'块 {i + 1}/{n} 第 {attempt} 次失败: {last}')
                    time.sleep(min(15, 2 * attempt))
            meta['err'] = meta['err'] or f'块 {i + 1}/{n} 重试 {retries} 次仍失败（{last}）'
        with ThreadPoolExecutor(max_workers=max(1, int(connections))) as ex:
            list(ex.map(fetch, [i for i in range(n) if i not in done]))
    finally:
        os.close(fd)
    if job.cancel: raise RuntimeError(CANCELLED)
    if meta['err']: raise RuntimeError(meta['err'])
    if len(done) != n: raise RuntimeError('下载不完整')
    os.remove(state_path)


def depot_download(depotdownloader, pubid, into_dir, log_path):
    """DepotDownloader fallback for items without a direct file_url. Returns the subprocess exit code; files land in into_dir."""
    os.makedirs(into_dir, exist_ok=True)
    with open(log_path, 'a', encoding='utf-8') as lf:
        r = subprocess.run([depotdownloader, '-app', '550', '-pubfile', pubid, '-dir', into_dir], stdout=lf, stderr=subprocess.STDOUT, text=True, timeout=6 * 3600)
    return r.returncode
