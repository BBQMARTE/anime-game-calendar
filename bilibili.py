# -*- coding: utf-8 -*-
"""B站官方号动态抓取
使用公开动态接口(免登录、免签名),只读官方账号公开动态。
"""
import re
import time
from datetime import datetime

import requests

from scrapers import _classify, normalize_title_cat
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
    ('arknights', '明日方舟',       161775300),
    ('wuwa',      '鸣潮',           1955897084),
    ('ananta',    '异环',           3546636978489848),
    ('r1999',     '重返未来：1999', 1197454103),
]

_NOISE = re.compile(r'生日快乐|生日祝福|早安|晚安')
_HOT = re.compile(r'抽奖|活动|福利|预约|直播|前瞻|征稿|征集|联动|测试|签到|开启|版本|维护|更新')
_TAG = re.compile(r'#[^#\r\n]+#')


# 接口重试耗尽的统一文案:两端(本文件与 static/scraper.js)必须逐字一致,
# 否则同一 mock 场景下 PC/App 的 status.error 会分叉
NO_RESPONSE = '接口无响应(疑似风控 -352 或网络异常)'


class BiliUnavailable(Exception):
    """B站接口重试耗尽(风控 -352 / 网络异常)。

    以前 _get 静默返回 None,与「接口正常但该官号当天无动态」无法区分,
    于是接口全挂时 status 仍是 ok:true/count:0(绿色徽标),故障不可见(Issue #24)。
    """


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
        raise BiliUnavailable(NO_RESPONSE)

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


_TRIM = ' ,，。.'          # 与 static/scraper.js::biliTitle 的边界字符集逐字一致(含全角逗号)


def _u16len(s):
    """UTF-16 码元数:与 JS String.length 同口径(非 BMP 字符记 2)"""
    return len(s.encode('utf-16-le')) // 2


def _u16cut(s, n):
    """按 UTF-16 码元数截断(不切开代理对,避免产生孤立代理)"""
    if _u16len(s) <= n:
        return s
    out, used = [], 0
    for ch in s:
        w = 2 if ord(ch) > 0xFFFF else 1
        if used + w > n:
            break
        out.append(ch)
        used += w
    return ''.join(out)


_URL_RE = re.compile(r'https?://\S+')


def _title_of(clean):
    # 动态正文里夹带的链接不进标题(否则会出现「互动抽奖 https://...」这类无效标题)
    lines = [_URL_RE.sub('', l).strip(_TRIM) for l in clean.split('\n')]
    lines = [l for l in lines if l]
    if not lines:
        return ''
    title = lines[0]
    if _u16len(title) < 8 and len(lines) > 1:  # 「互动抽奖」之类太短,补一行
        title = f'{title} {lines[1]}'
    return _u16cut(title, 38) + ('…' if _u16len(title) > 38 else '')


def _status_error(failed):
    """接口失败时的 error 文案。

    只依赖「失败的官号名单」与固定词条,不含异常原文 —— 否则同一 mock 场景下
    Python 与 JS 的 status.error 会因异常类名/消息不同而分叉(Issue #24 验收 4)。
    与 static/scraper.js::biliStatusError 逐字一致。
    """
    if not failed:
        return ''
    if len(failed) == len(GAME_UIDS):
        return f'{len(failed)} 个官号全部{NO_RESPONSE}'
    return f'{len(failed)}/{len(GAME_UIDS)} 个官号{NO_RESPONSE}: ' + '、'.join(failed)


def fetch_all(per_game=6):
    """抓取各官号最新动态。返回 (events, status)"""
    cli = _Client()
    events, failed = [], []
    for gid, gname, uid in GAME_UIDS:
        try:
            # 时间戳映射只是锦上添花(该接口更不稳定):失败退化为「无发布时间」,
            # 不计入该官号「无响应」—— 数据源本身是 opus 接口
            try:
                tmap = cli.time_map(uid)
            except Exception:  # noqa: BLE001
                tmap = {}
            # opus 接口失败(重试耗尽)会抛 BiliUnavailable:该官号计为失败,
            # 不得静默当成「今天没发动态」
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
                # 复用统一归一化:折叠空白 + 签到分流(与 static/scraper.js::ev() 同口径, Issue #14)
                title, cat = normalize_title_cat(title, cat)
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
        except BiliUnavailable:
            failed.append(gname)
        except Exception as e:  # noqa: BLE001
            failed.append(f'{gname}: {str(e)[:60]}')
        time.sleep(0.3)
    # 口径:7 个官号都要有响应,任一账号无响应即 ok=False(徽标转红 + error 列出账号),
    # 正常的「当天无动态」(合法 JSON 且 items 为空)不产生 failed,仍为 ok=True
    status = {'name': 'B站动态', 'ok': not failed, 'count': len(events),
              'error': _status_error(failed)}
    return events, status


if __name__ == '__main__':
    evs, st = fetch_all()
    print(st)
    for e in evs[:12]:
        print(e['game'], '|', e['title'][:36], '|', e['date'][:16], '|', e['category'])
