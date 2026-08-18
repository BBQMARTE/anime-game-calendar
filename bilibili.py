# -*- coding: utf-8 -*-
"""B站官方号动态抓取
使用公开动态接口(免登录、免签名),只读官方账号公开动态。
"""
import re
import time
from datetime import datetime

import requests

from scrapers import _classify
from timeparse import extract_range

UA = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/126.0 Safari/537.36',
}

# (game_id, 游戏名, 官方号UID)
GAME_UIDS = [
    ('hsr',       '崩坏：星穹铁道', 1340190821),
    ('zzz',       '绝区零',         1636034895),
    ('endfield',  '明日方舟：终末地', 1265652806),
    ('wuwa',      '鸣潮',           1955897084),
    ('ananta',    '异环',           3546636978489848),
]

_NOISE = re.compile(r'生日快乐|生日祝福|早安|晚安')
_HOT = re.compile(r'抽奖|活动|福利|预约|直播|前瞻|征稿|征集|联动|测试|签到|开启|版本|维护|更新')
_TAG = re.compile(r'#[^#\r\n]+#')


class _Client:
    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update(UA)

    def _get(self, url, **kw):
        kw.setdefault('timeout', 15)
        for _ in range(2):
            try:
                r = self.s.get(url, **kw)
                if r.status_code == 200 and r.text.strip().startswith('{'):
                    return r.json()
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.4)
        return None

    def opus_feed(self, uid, n=6):
        """图文动态(稳定,但无时间戳)"""
        d = self._get('https://api.bilibili.com/x/polymer/web-dynamic/v1/opus/feed/space',
                      params={'host_mid': uid, 'page_num': 0, 'page_size': max(n, 6)},
                      headers={'Referer': f'https://space.bilibili.com/{uid}/dynamic'})
        return ((d or {}).get('data') or {}).get('items') or []

    def time_map(self, uid):
        """完整动态流(不稳定但带 pub_ts),用于建立 动态ID->发布时间 映射"""
        d = self._get('https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space',
                      params={'host_mid': uid},
                      headers={'Referer': f'https://space.bilibili.com/{uid}/dynamic'})
        out = {}
        for it in ((d or {}).get('data') or {}).get('items') or []:
            ts = ((it.get('modules') or {}).get('module_author') or {}).get('pub_ts')
            if it.get('id_str') and ts:
                out[it['id_str']] = int(ts)
        return out


def _title_of(clean):
    lines = [l.strip(' ,,。.') for l in clean.split('\n') if l.strip(' ,,。.')]
    if not lines:
        return ''
    title = lines[0]
    if len(title) < 8 and len(lines) > 1:  # 「互动抽奖」之类太短,补一行
        title = f'{title} {lines[1]}'
    return title[:38] + ('…' if len(title) > 38 else '')


def fetch_all(per_game=6):
    """抓取各官号最新动态。返回 (events, status)"""
    cli = _Client()
    events, errs = [], []
    for gid, gname, uid in GAME_UIDS:
        try:
            tmap = cli.time_map(uid)
            for it in cli.opus_feed(uid, per_game)[:per_game]:
                text = (it.get('content') or '').strip()
                if not text:
                    continue
                clean = _TAG.sub('', text).strip()
                title = _title_of(clean)
                if not title:
                    continue
                if _NOISE.search(title) and not _HOT.search(clean):
                    continue
                ts = tmap.get(it['opus_id'])
                flat = re.sub(r'\s+', ' ', clean)
                start, end = extract_range(flat, datetime.now())
                # 发布时间:动态流映射 > 正文解析出的开始时间 > 现在
                pub = datetime.fromtimestamp(ts) if ts else (start or datetime.now())
                cat = _classify(title, '活动' if _HOT.search(clean) else '资讯')
                img = (it.get('cover') or {}).get('url') or ''
                if img.startswith('http://'):
                    img = 'https://' + img[7:]
                jump = it.get('jump_url') or ''
                link = ('https:' + jump) if jump.startswith('//') else jump
                events.append({
                    'id': f'bili-{it["opus_id"]}',
                    'game_id': gid, 'game': gname,
                    'title': title, 'category': cat,
                    'start': start.isoformat() if start else None,
                    'end': end.isoformat() if end else None,
                    'date': pub.isoformat(),
                    'link': link or f'https://space.bilibili.com/{uid}/dynamic',
                    'image': img, 'src': 'bilibili',
                    'kind': 'info',  # B站动态一律不上月历,仅进资讯列表
                })
        except Exception as e:  # noqa: BLE001
            errs.append(f'{gname}: {str(e)[:60]}')
        time.sleep(0.3)
    status = {'name': 'B站动态', 'ok': not errs, 'count': len(events),
              'error': '; '.join(errs)[:150] if errs else ''}
    return events, status


if __name__ == '__main__':
    evs, st = fetch_all()
    print(st)
    for e in evs[:12]:
        print(e['game'], '|', e['title'][:36], '|', e['date'][:16], '|', e['category'])
