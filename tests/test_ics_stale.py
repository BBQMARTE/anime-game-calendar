# -*- coding: utf-8 -*-
"""ICS 订阅边界测试:过去/过老条目不应塞进日历。

状态里通常已被 _drop_expired 过滤,但缓存异常或直接注入时仍可能漏网:
- 已结束(end 早于今天)的条目不进订阅
- 开始超过 30 天且没有结束时间的(前端同样折叠为「更早开始·结束未知」)
  不再补默认 2 天窗口,避免订阅日历里堆一堆过去事件

运行:python tests/test_ics_stale.py
"""
import os
import re
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app  # noqa: E402

bad = 0


def check(label, got, expect):
    global bad
    ok = got == expect
    if not ok:
        bad += 1
    print("[%s] %s: got=%r expect=%r" % ('OK ' if ok else 'FAIL', label, got, expect))


def ev(eid, start, end=None):
    return {'id': eid, 'game_id': 'zzz', 'game': '绝区零', 'title': eid,
            'category': '活动', 'start': start, 'end': end, 'date': start,
            'kind': 'event', 'src': ''}


def main():
    global bad
    backup = app._state['events']
    base = app._bj_now().replace(tzinfo=None)

    def iso(days=0, hour=10):
        d = base + timedelta(days=days)
        return d.replace(hour=hour, minute=0, second=0, microsecond=0).isoformat(timespec='seconds')

    events = [
        ev('fresh', iso(-5), None),          # 5 天前开始、结束未知 → 仍保留
        ev('today', iso(0), None),           # 今天开始、结束未知 → 保留
        ev('future', iso(2), None),          # 后天开始 → 保留
        ev('stale', iso(-40), None),         # 40 天前开始、结束未知 → 不订阅
        ev('ended', iso(-3), iso(-1, 23)),   # 已结束 → 不订阅
    ]
    try:
        app._state['events'] = events
        ics = app.app.test_client().get('/api/calendar.ics').get_data(as_text=True)
        uids = set(re.findall(r'UID:(\S+)@ycal', ics))
        check('订阅数只含 3 条有效活动', len(uids), 3)
        check('5 天前开始的无结束条目保留', 'fresh' in uids, True)
        check('今天开始的无结束条目保留', 'today' in uids, True)
        check('未来条目保留', 'future' in uids, True)
        check('40 天前的无结束条目剔除', 'stale' in uids, False)
        check('已结束条目剔除', 'ended' in uids, False)
        check('每个事件都有 SEQUENCE', len(re.findall(r'^SEQUENCE:', ics, re.M)), 3)
    finally:
        app._state['events'] = backup

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
