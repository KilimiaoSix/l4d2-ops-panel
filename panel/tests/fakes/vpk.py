"""Minimal VPK v1 writer: just the directory tree the panel's parser walks (ext -> dir -> name).

Entries carry no payload (archive index 0x7fff, length 0), which is all the panel looks at
when it lists a campaign's maps and mission file.
"""
import struct

VPK_MAGIC = b'\x34\x12\xaa\x55'   # 0x55aa1234 little-endian


def build_vpk(entries):
    """entries: iterable of 'dir/name.ext' (or 'name.ext' for the root). Returns the bytes of a v1 VPK."""
    tree = {}
    for p in entries:
        d, _, fn = p.rpartition('/')
        name, _, ext = fn.rpartition('.')
        tree.setdefault(ext, {}).setdefault(d or ' ', []).append(name)
    body = b''
    for ext, dirs in tree.items():
        body += ext.encode() + b'\0'
        for d, names in dirs.items():
            body += d.encode() + b'\0'
            for n in names:
                body += n.encode() + b'\0' + struct.pack('<IHHIIH', 0, 0, 0x7fff, 0, 0, 0xffff)
            body += b'\0'
        body += b'\0'
    body += b'\0'
    return struct.pack('<III', 0x55aa1234, 1, len(body)) + body
