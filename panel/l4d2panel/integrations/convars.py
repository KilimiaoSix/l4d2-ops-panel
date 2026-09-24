"""Read a single SourceMod ConVar without depending on translated prose."""
import re

from ..errors import IntegrationError


class ConVarReadError(IntegrationError):
    """A response arrived, but it did not contain an unambiguous scalar value."""


def read_convar(rcon, name: str) -> str:
    output = rcon.run('sm_cvar ' + name)
    # SourceMod translations and the engine surround both the name and value in
    # quotes. Do not mistake an error mentioning only the name for a zero value.
    pattern = re.compile(r'^[^"\r\n]*"' + re.escape(name) + r'"[^"\r\n]*"([^"\r\n]*)"[ \t.。]*$', re.M)
    match = pattern.search(output)
    if not match:
        raise ConVarReadError('无法读取运行值（变量不存在、插件未加载或返回格式不支持）')
    return match.group(1)
