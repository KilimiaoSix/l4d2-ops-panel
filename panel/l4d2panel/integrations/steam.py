"""Steam Web API (workshop item details) and steamcommunity vanity-URL lookup."""
import json, re, urllib.parse, urllib.request

from ..errors import IntegrationError


class SteamClient:
    def __init__(self, api_base: str, community_base: str, user_agent='l4d2panel'):
        self.api_base, self.community_base, self.ua = api_base.rstrip('/'), community_base.rstrip('/'), user_agent

    def pubfile_details(self, pubid: str) -> dict:
        req = urllib.request.Request(self.api_base + '/ISteamRemoteStorage/GetPublishedFileDetails/v1/',
                                     data=urllib.parse.urlencode({'itemcount': 1, 'publishedfileids[0]': pubid}).encode(), headers={'User-Agent': self.ua})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                lst = json.loads(r.read().decode('utf-8', 'replace'))['response'].get('publishedfiledetails') or []
        except Exception as e:
            raise IntegrationError(f'查询 Steam Web API 失败（{e}）')
        if not lst: raise IntegrationError('Steam 没有返回这个物品')
        return lst[0]

    def resolve_vanity(self, vanity: str):
        """SteamID64 of a custom profile name, or None when it cannot be resolved."""
        try:
            with urllib.request.urlopen(self.community_base + '/id/' + urllib.parse.quote(vanity) + '/?xml=1', timeout=6) as r:
                m = re.search(r'<steamID64>(\d{17})</steamID64>', r.read().decode('utf-8', 'replace'))
                return m.group(1) if m else None
        except Exception:
            return None
