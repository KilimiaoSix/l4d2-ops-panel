"""A single validated, secret-free game endpoint for the guide and footer."""
import ipaddress
import re


def endpoint(host, default_port):
    if not isinstance(host, str) or not host or len(host) > 300 or any(c.isspace() for c in host):
        raise ValueError('请填写游戏域名或 IP，可附带端口')
    if type(default_port) is not int or not 1 <= default_port <= 65535: raise ValueError('游戏端口无效')
    port, name = default_port, host
    if host.startswith('['):
        match = re.fullmatch(r'\[([0-9A-Fa-f:.]+)\](?::([0-9]{1,5}))?', host)
        if not match: raise ValueError('IPv6 地址格式无效')
        name = str(ipaddress.IPv6Address(match[1]))
        if match[2] is not None: port = int(match[2])
        name = '[' + name + ']'
    elif host.count(':') > 1:
        # An unbracketed IPv6 literal never has an inferred port suffix.
        if not re.fullmatch(r'[0-9A-Fa-f:.]+', host): raise ValueError('IPv6 地址格式无效')
        name = '[' + str(ipaddress.IPv6Address(host)) + ']'
    else:
        if ':' in host:
            name, number = host.split(':')
            if not re.fullmatch(r'[0-9]{1,5}', number): raise ValueError('游戏端口无效')
            port = int(number)
        try: name = str(ipaddress.IPv4Address(name))
        except ValueError:
            if re.fullmatch(r'[0-9.]+', name): raise ValueError('IPv4 地址无效') from None
            try: name = name.encode('idna').decode('ascii').lower()
            except UnicodeError: raise ValueError('游戏域名无效') from None
            if len(name) > 253 or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label)
                                    for label in name.rstrip('.').split('.')):
                raise ValueError('游戏地址不能包含协议、路径、空格或命令字符')
    if not 1 <= port <= 65535: raise ValueError('游戏端口必须为 1–65535')
    return f'{name}:{port}', port


def join_info(settings):
    result = {'address': '', 'command': '', 'port': settings.rcon_port, 'engine_port': settings.rcon_port,
              'error': '', 'public_access': 'unverified'}
    try:
        result['address'], result['port'] = endpoint(settings.display_host, settings.rcon_port)
        result['command'] = 'connect ' + result['address']
    except ValueError as error: result['error'] = str(error)
    return result
