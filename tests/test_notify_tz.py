# -*- coding: utf-8 -*-
"""提醒链路时区口径测试（覆盖 Issue #12）。

`data/manual.json` 与抓取结果都是北京时间，而 `_daily_notify` / `_notify_loop`
原先用服务器本地时间的裸 `datetime.now()` 判定「今天/明天」与「是否到点」，
非 UTC+8 服务器会错报漏报。本脚本离线跑（不起服务、不联网）：把 now 注入进去断言判定结果。

运行：python3 tests/test_notify_tz.py
"""
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app  # noqa: E402

_REAL_SEND = app._send_notify
bad = 0


def check(label, got, expect):
    global bad
    ok = got == expect
    if not ok:
        bad += 1
    print("[%s] %s: got=%s expect=%s" % ('OK ' if ok else 'FAIL', label, got, expect))


def ev(title, start):
    return {'game_id': 'zzz', 'game': '绝区零', 'title': title,
            'kind': 'event', 'start': start, 'end': None}


def collected(now, events):
    """注入 _state / _send_notify，跑一次 _daily_notify，返回 [(标题, 正文)]。"""
    sent = []
    app._state['events'] = events
    app._state['sources'] = {}
    app._send_notify = lambda title, body: sent.append((title, body)) or True
    app._notify_config = lambda: {'time': '08:30', 'webhook': 'http://example.invalid/hook'}
    app._daily_notify(now)
    return sent


# 1. 「今天/明天」按北京时间判定（北京 09-23 01:00，UTC 服务器当时还是 09-22 17:00）
bj = datetime(2026, 9, 23, 1, 0, tzinfo=app._CST)
sent = collected(bj, [ev('凌晨开始的活动', '2026-09-23T00:30'),
                      ev('次日的活动', '2026-09-24T00:30')])
body = sent[0][1] if sent else ''
check("_bj_now 偏移为 +8", app._bj_now().utcoffset(), timedelta(hours=8))
check("推送条数", len(sent), 1)
check("北京 09-23 00:30 判为「今天」", '· 今天 00:30 【绝区零】凌晨开始的活动' in body, True)
check("北京 09-24 00:30 判为「明天」", '· 明天 00:30 【绝区零】次日的活动' in body, True)

# 2. 反证：同一时刻若按「服务器本地时间」（UTC）判定，会把「今天」错判成「明天」
utc_local = datetime(2026, 9, 22, 17, 0, tzinfo=timezone.utc)
check("同一物理时刻的 UTC 本地日期", utc_local.strftime('%Y-%m-%d'), '2026-09-22')
check("北京日期与之不同（说明旧口径会判错）", bj.strftime('%Y-%m-%d') != utc_local.strftime('%Y-%m-%d'), True)
old_body = '· %s 00:30' % ('今天' if '2026-09-23' == utc_local.strftime('%Y-%m-%d') else '明天')
check("旧口径（本地时间）会写成「明天」", old_body, '· 明天 00:30')

# 3. 北京跨日边界：北京 09-24 00:01 时，09-23 的活动已不在「今明两天」
sent = collected(datetime(2026, 9, 24, 0, 1, tzinfo=app._CST), [ev('昨天的活动', '2026-09-23T00:30')])
check("跨日后过期活动不推送",
      (sent[0][1] if sent else '').startswith('今明两天没有新活动开始'), True)

# 4. 到点判定（notify.json 的 time 按北京时间，跨日不串）
check("未到点 (07:59)", app._notify_due(bj.replace(hour=7, minute=59), '08:30'), None)
check("到点 (08:30)", app._notify_due(bj.replace(hour=8, minute=30), '08:30'), '2026-09-23')
check("当日 23:59 仍记北京当天", app._notify_due(bj.replace(hour=23, minute=59), '08:30'), '2026-09-23')
check("次日 00:01 未到点（等 08:30）", app._notify_due(bj.replace(day=24, hour=0, minute=1), '08:30'), None)
check("次日 08:30 记为新的北京日期", app._notify_due(bj.replace(day=24, hour=8, minute=30), '08:30'), '2026-09-24')
check("配置非法回落 08:30", app._notify_due(bj.replace(hour=8, minute=45), ''), '2026-09-23')

# 5. 不回归：webhook 空值不推送；飞书 / 通用 JSON 载荷格式不变
app._send_notify = _REAL_SEND   # 前面几段用 lambda 注入过，这里恢复真实实现


class _Resp:
    def __init__(self):
        self.calls = []

    def post(self, url, json=None, timeout=None):
        self.calls.append((url, json))
        return self


_resp = _Resp()
_orig_requests = app.requests
app.requests = _resp
try:
    app._notify_config = lambda: {'time': '08:30', 'webhook': ''}
    app._state['events'] = [ev('活动', '2026-09-23T00:30')]
    app._daily_notify(datetime(2026, 9, 23, 8, 30, tzinfo=app._CST))
    check("webhook 为空不推送", _resp.calls, [])

    app._notify_config = lambda: {'webhook': 'https://open.feishu.cn/open-apis/bot/v2/hook/x'}
    app._send_notify('标题', '正文')
    check("飞书载荷格式", _resp.calls[-1][1], {'msg_type': 'text', 'content': {'text': '标题\n正文'}})

    app._notify_config = lambda: {'webhook': 'https://api.day.app/xxx'}
    app._send_notify('标题', '正文')
    check("通用 JSON 载荷格式", _resp.calls[-1][1], {'title': '标题', 'body': '正文'})
finally:
    app.requests = _orig_requests


# 6. 提醒链路不得再用裸 datetime.now()（防止口径回退）
src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'app.py'),
           encoding='utf-8').read()
notify_src = src[src.index('def _daily_notify('):src.index('def _port_in_use(')]
check("提醒链路已无裸 datetime.now()", 'datetime.now()' in notify_src, False)
check("提醒链路使用 _bj_now()", '_bj_now()' in notify_src or '_notify_due(' in notify_src, True)

print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
sys.exit(0 if bad == 0 else 1)
