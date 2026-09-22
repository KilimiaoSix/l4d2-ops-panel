"""Files of the game / SourceMod install the panel reads and writes: server.cfg, whitelist.txt,
admins_simple.ini and the plugin directories."""
import os, re, shutil, time

ADM_BEGIN = '// ==== panel-managed BEGIN (the web panel maintains this block; do not edit inside) ===='
ADM_END = '// ==== panel-managed END ===='
ADM_BLOCK_RE = re.compile(r'(?://|;) ==== panel-managed BEGIN.*?(?://|;) ==== panel-managed END[^\n]*', re.S)   # also matches a legacy ; block


def read_rcon_password(server_cfg) -> str:
    try:
        m = re.search(r'rcon_password\s+"([^"]+)"', open(server_cfg, encoding='utf-8', errors='replace').read())
        return m.group(1) if m else ''
    except FileNotFoundError:
        return ''


def read_whitelist(path):
    try:
        return [l.rstrip('\n') for l in open(path, encoding='utf-8', errors='replace') if l.strip() and not l.strip().startswith('//')]
    except FileNotFoundError:
        return []


def write_admins_block(path, rows):
    """Replace (or append) the panel-managed block of admins_simple.ini. rows: (id, username, steamid, flags)."""
    lines = [ADM_BEGIN]
    for aid, username, steamid, flags in rows:
        cmt = re.sub(r'[^\x20-\x7e]', '?', username or '').replace('\\', '')
        lines.append(f'"{steamid}" "{flags or "99:z"}"    // panel#{aid} {cmt}')
    lines.append(ADM_END)
    block = '\n'.join(lines)
    try: txt = open(path, encoding='utf-8', errors='replace').read()
    except FileNotFoundError: txt = ''
    if ADM_BLOCK_RE.search(txt):
        txt = ADM_BLOCK_RE.sub(lambda _: block, txt, count=1)
    else:
        txt = (txt.rstrip() + '\n\n' + block + '\n') if txt.strip() else (block + '\n')
    tmp = str(path) + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f: f.write(txt)
    os.replace(tmp, path)


def persist_cvars(server_cfg, pairs):
    """Write name/value pairs into server.cfg so a restart keeps them: replaces an existing line (with or without the
    sm_cvar prefix), otherwise appends. Read/written as latin-1 so the round trip is byte-exact whatever the file
    holds; the lines added are pure ASCII (the engine chokes on multibyte characters). Keeps a timestamped backup."""
    text = open(server_cfg, encoding='latin-1').read()
    shutil.copy(server_cfg, str(server_cfg) + '.bak-panel-' + time.strftime('%Y%m%d-%H%M%S'))
    for name, val in pairs:
        line = f'sm_cvar {name} {val}'
        pat = re.compile(r'^[ \t]*(?:sm_cvar[ \t]+)?' + re.escape(name) + r'[ \t]+\S.*$', re.M)
        text, n = pat.subn(line, text, count=1)
        if n == 0:
            text = text.rstrip('\n') + '\n' + line + '\n'
    open(server_cfg, 'w', encoding='latin-1').write(text)


def list_smx(directory):
    try: return sorted(f for f in os.listdir(directory) if f.endswith('.smx'))
    except FileNotFoundError: return []
