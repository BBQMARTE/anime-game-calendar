# -*- coding: utf-8 -*-
"""「即将结束」提醒测试(_daily_notify 的结束分支)。

离线跑:注入 _state / _send_notify,断言今天/明天结束的活动进入推送,已结束与更远的不进。
运行:python3 tests/test_notify_ending.py
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


def ev(title, start=None, end=None, kind='event'):
    return {'game_id': 'zzz', 'game': '绝区零', 'title': title,
            'kind': kind, 'start': start, 'end': end}


def collected(now, events):
    sent = []
    app._state['events'] = events
    app._state['sources'] = {}
    app._send_notify = lambda title, body: sent.append((title, body)) or True
    app._notify_config = lambda: {'time': '08:30', 'webhook': 'http://example.invalid/hook',
                                  'lead_days': 1}
    app._daily_notify(now)
    return sent


def main():
    now = datetime(2026, 10, 30, 8, 30, tzinfo=app._CST)
    evs = [
        ev('今天开始的活动', start='2026-10-30T10:00'),
        ev('明天结束的活动', start='2026-10-20T10:00', end='2026-10-31T03:59'),
        ev('今天结束的活动', start='2026-10-20T10:00', end='2026-10-30T23:59'),
        ev('今天凌晨已结束', start='2026-10-20T10:00', end='2026-10-30T03:59'),
        ev('后天结束的活动', start='2026-10-20T10:00', end='2026-11-01T03:59'),
        ev('长期无结束', start='2026-10-20T10:00', end=None),
    ]
    sent = collected(now, evs)
    check("只推一条汇总", len(sent), 1)
    title, body = sent[0] if sent else ('', '')
    check("标题含开始数", '1 个活动开始' in title, True)
    check("标题含即将结束数", '2 个活动即将结束' in title, True)
    check("正文有结束分区", '⏰ 即将结束' in body, True)
    check("明天结束按「明天」显示", '· 明天 03:59 截止 【绝区零】明天结束的活动' in body, True)
    check("今天结束按「今天」显示", '· 今天 23:59 截止 【绝区零】今天结束的活动' in body, True)
    check("今天凌晨已结束不推送", '今天凌晨已结束' in body, False)
    check("后天结束不推送", '后天结束的活动' in body, False)
    check("长期活动不进结束区", '长期无结束' in body, False)

    # 只有结束、没有开始:仍要推送(否则「最后一天」最容易漏)
    sent = collected(now, [ev('只剩结束', start='2026-09-01T10:00', end='2026-10-30T23:59')])
    check("仅结束也推送", len(sent), 1)
    check("仅结束标题", '1 个活动即将结束' in (sent[0][0] if sent else ''), True)
    check("仅结束不含开始计数", '个活动开始' in (sent[0][0] if sent else ''), False)

    # 都没有:保持历史文案(供既有测试/用户习惯)
    sent = collected(now, [ev('很久以前', start='2026-09-01T10:00', end='2026-09-10T03:59')])
    check("全空仍有推送", len(sent), 1)
    check("全空文案保持", (sent[0][1] if sent else '').startswith('今明两天没有新活动开始'), True)

    # info 类不参与
    sent = collected(now, [ev('公告今天结束', start='2026-10-01T10:00',
                              end='2026-10-30T23:59', kind='info')])
    check("info 不进结束提醒", '公告今天结束' in (sent[0][1] if sent else ''), False)

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
