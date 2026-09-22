"""Steam identity parsing: SteamID2 / SteamID3 / SteamID64 / profile URL / vanity name -> canonical STEAM_1:Y:Z."""
import re

STEAMID64_BASE = 76561197960265728


def from_accountid(acc: int) -> str:
    if acc < 0: raise ValueError('不是有效的 Steam 账号')
    return f'STEAM_1:{acc & 1}:{acc >> 1}'   # L4D2 reports universe 1; match that


def parse_steamid(raw, resolve_vanity=None) -> str:
    """Canonical STEAM_1:Y:Z, or '' for blank input. resolve_vanity(name) -> SteamID64 string or None is only
    called for custom profile names / links. Raises ValueError with a message meant for the user."""
    s = str(raw or '').strip()
    if not s: return ''
    m = re.fullmatch(r'STEAM_[0-5]:([01]):(\d+)', s, re.I)
    if m: return f'STEAM_1:{m.group(1)}:{m.group(2)}'
    m = re.fullmatch(r'\[?U:1:(\d+)\]?', s, re.I)
    if m: return from_accountid(int(m.group(1)))
    u = re.search(r'/profiles/(\d{17})', s)
    if u: s = u.group(1)
    if re.fullmatch(r'\d{17}', s): return from_accountid(int(s) - STEAMID64_BASE)
    v = re.search(r'/id/([^/?#]+)', s)
    vanity = v.group(1) if v else (s if re.fullmatch(r'[A-Za-z0-9_.\-]{2,64}', s) else None)
    if vanity:
        id64 = resolve_vanity(vanity) if resolve_vanity else None
        if id64: return from_accountid(int(id64) - STEAMID64_BASE)
        raise ValueError('无法解析自定义主页链接（服务器可能连不上 steamcommunity.com）；请改用 SteamID、17 位好友码，或 /profiles/数字 链接')
    raise ValueError('无法识别的 Steam 标识')
