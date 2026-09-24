"""Steam Web API (workshop item details and search) and steamcommunity vanity-URL lookup."""
import json, re, urllib.error, urllib.parse, urllib.request

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

    def query_files(self, api_key: str, q: str, page: int = 1, per: int = 20) -> dict:
        """Search all L4D2 Workshop items: text search when q is given, else most-subscribed.
        Needs a Steam Web API key (free, https://steamcommunity.com/dev/apikey); the key never leaves the server."""
        params = {'key': api_key, 'appid': 550, 'creator_appid': 550, 'page': page, 'numperpage': per,
                  'query_type': 12 if q else 9, 'return_metadata': 1, 'return_tags': 1, 'return_vote_data': 1, 'return_short_description': 1}
        if q: params['search_text'] = q
        req = urllib.request.Request(self.api_base + '/IPublishedFileService/QueryFiles/v1/?' + urllib.parse.urlencode(params), headers={'User-Agent': self.ua})
        try:
            with urllib.request.urlopen(req, timeout=20) as r: resp = json.loads(r.read().decode('utf-8', 'replace')).get('response') or {}
        except urllib.error.HTTPError as e:
            if e.code in (401, 403): raise IntegrationError('Steam 拒绝了这个 API Key（检查 panel.json 里的 steam_api_key）')
            raise IntegrationError(f'Steam Web API 返回 HTTP {e.code}')
        except ValueError:
            raise IntegrationError('Steam Web API 返回了无法解析的内容')
        except OSError as e:
            raise IntegrationError(f'查询 Steam Web API 失败（{e}）')
        items = []
        for d in resp.get('publishedfiledetails') or []:
            if int(d.get('result', 1)) != 1: continue
            items.append({'id': str(d.get('publishedfileid', '')), 'title': d.get('title', ''), 'size_mb': round(int(d.get('file_size') or 0) / 1048576, 1),
                          'subs': int(d.get('subscriptions') or 0), 'updated': int(d.get('time_updated') or 0), 'preview': d.get('preview_url', ''),
                          'tags': [t.get('tag', '') for t in d.get('tags') or [] if t.get('tag') != 'Campaigns'],
                          'score': round(float((d.get('vote_data') or {}).get('score') or 0), 2), 'desc': (d.get('short_description') or '')[:200]})
        return {'items': items, 'total': int(resp.get('total') or 0), 'page': page}

    def resolve_vanity(self, vanity: str):
        """SteamID64 of a custom profile name, or None when it cannot be resolved."""
        try:
            with urllib.request.urlopen(self.community_base + '/id/' + urllib.parse.quote(vanity) + '/?xml=1', timeout=6) as r:
                m = re.search(r'<steamID64>(\d{17})</steamID64>', r.read().decode('utf-8', 'replace'))
                return m.group(1) if m else None
        except Exception:
            return None
