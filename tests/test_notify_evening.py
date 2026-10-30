# -*- coding: utf-8 -*-
"""晚间二次提醒(_daily_notify(evening=True))测试。

晚安提醒只覆盖「明天开始」与「今天结束」,避免和早间汇总重复。
运行:python3 tests/test_notify_evening.py
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app  # noqa: E402

bad = 0


def check(label, got, expect):
    global bad
    ok = got == expect
    if not ok:
        bad += 1
    print("[%s] %s: got=%r expect=%r" % ('OK ' if ok else 'FAIL', label, got, expect))


def ev(title, start=None, end=None):
    return {'game_id': 'zzz', 'game': '绝区零', 'title': title,
            'kind': 'event', 'start': start, 'end': end}


def collected(now, events, evening):
    sent = []
    app._state['events'] = events
    app._state['sources'] = {}
    app._send_notify = lambda t, b: sent.append((t, b)) or True
    app._notify_config = lambda: {'time': '08:30', 'webhook': 'http://example.invalid/hook',
                                  'lead_days': 1, 'evening': '20:30'}
    app._daily_notify(now, evening=evening)
    return sent


def main():
    now = datetime(2026, 10, 31, 20, 30, tzinfo=app._CST)
    evs = [
        ev('今天开始', start='2026-10-31T10:00'),
        ev('明天开始', start='2026-11-01T10:00'),
        ev('后天开始', start='2026-11-02T10:00'),
        ev('今天结束', start='2026-10-20T10:00', end='2026-10-31T23:59'),
        ev('明天结束', start='2026-10-20T10:00', end='2026-11-01T03:59'),
    ]

    sent = collected(now, evs, evening=False)
    title, body = sent[0] if sent else ('', '')
    check("早间:标题前缀", title.startswith('二游活动提醒:'), True)
    check("早间:含今天开始", '今天开始' in body, True)
    check("早间:含明天结束", '明天结束' in body, True)

    sent = collected(now, evs, evening=True)
    title, body = sent[0] if sent else ('', '')
    check("晚间:标题前缀", title.startswith('晚安提醒:'), True)
    check("晚间:只推明天开始", '· 明天 10:00 【绝区零】明天开始' in body, True)
    check("晚间:不推今天开始", '今天开始' in body, False)
    check("晚间:不推后天开始", '后天开始' in body, False)
    check("晚间:推今天结束", '· 今天 23:59 截止 【绝区零】今天结束' in body, True)
    check("晚间:不推明天结束", '明天结束' in body, False)

    # 晚间无内容时给出专用文案,而不是复用早间的「没有新活动开始」
    sent = collected(now, [ev('后天开始', start='2026-11-02T10:00')], evening=True)
    check("晚间空内容仍有推送", len(sent), 1)
    check("晚间空内容文案", sent[0][1], '今晚没有需要注意的活动。')

    # 早间空内容文案保持历史口径(既有测试依赖此前缀)
    sent = collected(now, [ev('很久以前', start='2026-09-01T10:00', end='2026-09-10T03:59')],
                     evening=False)
    check("早间空内容文案不变", (sent[0][1] if sent else '').startswith('今明两天没有新活动开始'), True)

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
