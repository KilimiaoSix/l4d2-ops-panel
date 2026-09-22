"""VPK directory reader (v1 / v2), best effort: the list of file paths inside a .vpk, and what it amounts to."""
import struct

VPK_MAGIC = b'\x34\x12\xaa\x55'


def vpk_entries(path):
    out = []
    try:
        with open(path, 'rb') as f:
            sig, ver, tree = struct.unpack('<III', f.read(12))
            if sig != 0x55aa1234: return out
            f.seek(12 if ver == 1 else 28)
            def cstr():
                b = bytearray()
                while True:
                    c = f.read(1)
                    if not c or c == b'\x00': return b.decode('utf-8', 'replace')
                    b += c
            while True:
                ext = cstr()
                if not ext: break
                while True:
                    d = cstr()
                    if not d: break
                    while True:
                        n = cstr()
                        if not n: break
                        crc, pre, ai, off, ln, term = struct.unpack('<IHHIIH', f.read(18)); f.read(pre)
                        out.append((d + '/' if d != ' ' else '') + n + '.' + ext)
    except Exception:
        pass
    return out


def vpk_summary(path):
    """What a vpk holds: its campaign maps, its mission file, and a one-line description of the contents for the 'not a map' message."""
    ents = vpk_entries(path)
    maps = sorted(e.split('/')[-1][:-4] for e in ents if e.startswith('maps/') and e.endswith('.bsp'))
    mission = next((e.split('/')[-1][:-4] for e in ents if e.startswith('missions/') and e.endswith('.txt')), '')
    tops = sorted(set(e.split('/')[0] + '/' if '/' in e else e for e in ents))
    kind = f'{len(ents)} 个文件：' + '、'.join(tops[:5]) + ('…' if len(tops) > 5 else '') if ents else '解析不到任何文件'
    return {'maps': maps, 'mission': mission, 'kind': kind}
