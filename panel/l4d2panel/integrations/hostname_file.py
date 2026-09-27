"""Canonical name bytes shared by persistence and the SourceMod hex receipt."""
import re
import unicodedata


def canonical_name(value):
    if not isinstance(value, str): raise ValueError('服务器名称必须是文本')
    value = unicodedata.normalize('NFC', value.strip())
    if any(unicodedata.category(c).startswith('C') or c in '";\\' for c in value):
        raise ValueError('服务器名称不能包含控制字符、引号、分号或反斜线')
    if not 1 <= len(value.encode('utf-8')) <= 96: raise ValueError('服务器名称应为 1–96 个 UTF-8 字节')
    return value


def read_name(data):
    if data is None: return None
    try:
        value = data.decode('utf-8')
        if value.endswith('\n'): value = value[:-1]
        if value.endswith('\r'): value = value[:-1]
        normalized = canonical_name(value)
        if normalized != value: raise ValueError('名称文件不是规范化 UTF-8，请重新保存')
        return value
    except UnicodeDecodeError: raise ValueError('名称文件不是有效 UTF-8') from None


def parse_name_receipt(text):
    match = re.search(r'^PANEL_HOSTNAME expected=([0-9a-f]*) actual=([0-9a-f]*) state=([a-z_]+)$', text, re.M)
    if not match: return None
    expected, actual, state = match.groups()
    try:
        return {'expected': bytes.fromhex(expected).decode('utf-8'),
                'actual': bytes.fromhex(actual).decode('utf-8'), 'state': state}
    except (ValueError, UnicodeDecodeError): return None
