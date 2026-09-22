"""VPK directory reader (v1 / v2), best effort: the list of file paths inside a .vpk."""
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
