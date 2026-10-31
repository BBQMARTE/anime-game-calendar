# -*- coding: utf-8 -*-
"""爬虫条目 ID 稳定化测试。

条目的 id 同时是 ICS 的 UID 与收藏/打钩的键。此前 id 由「标题|开始时间」哈希
派生,官方改期后 ID 变化 → 日历订阅端多出一条旧时间的条目、收藏丢失。
_stabilize_event_ids 按「游戏+归一化标题」登记首次 ID 并复用。

运行:python tests/test_event_ids.py
"""
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
bad = 0


def check(label, got, expect):
    global bad
    ok = got == expect
    if not ok:
        bad += 1
    print("[%s] %s: got=%r expect=%r" % ('OK ' if ok else 'FAIL', label, got, expect))


def ev(gid, title, start='2026-11-05T10:00', end='2026-11-12T03:59', src='', eid=None):
    return {'id': eid or '%s-x1' % gid, 'game_id': gid, 'game': gid, 'title': title,
            'category': '活动', 'start': start, 'end': end, 'date': start,
            'link': '', 'image': '', 'src': src, 'kind': 'event'}


def main():
    global bad
    tmp = tempfile.mkdtemp()
    real = app.EVENT_IDS_FILE
    real_state = app._state['events']
    app.EVENT_IDS_FILE = os.path.join(tmp, 'event_ids.json')
    try:
        # ---- 首次登记:ID 不变 ----
        a = ev('hsr', '活动甲', eid='hsr-a1')
        app._stabilize_event_ids([a], now=datetime(2026, 10, 31, 9, 0))
        check('首次登记不改变 ID', a['id'], 'hsr-a1')
        reg = app._load_event_ids()
        check('登记表写入', reg[app._change_key(a)]['id'], 'hsr-a1')

        # ---- 改期:开始时间变了,ID 复用历史值 ----
        a2 = ev('hsr', '活动甲', start='2026-11-08T10:00', end='2026-11-15T03:59', eid='hsr-a2')
        app._stabilize_event_ids([a2], now=datetime(2026, 10, 31, 9, 0))
        check('改期后 ID 复用', a2['id'], 'hsr-a1')

        # ---- 新活动:用自己的派生 ID ----
        b = ev('wuwa', '活动乙', eid='wuwa-b1')
        app._stabilize_event_ids([a2, b], now=datetime(2026, 10, 31, 9, 0))
        check('新活动保留派生 ID', b['id'], 'wuwa-b1')

        # ---- 人工 / B站条目不动 ----
        m = ev('hsr', '人工活动', src='manual', eid='manual-fixed')
        s = ev('hsr', 'B站动态', src='bilibili', eid='bili-123')
        app._stabilize_event_ids([m, s], now=datetime(2026, 10, 31, 9, 0))
        check('人工条目 ID 不动', m['id'], 'manual-fixed')
        check('B站条目 ID 不动', s['id'], 'bili-123')

        # ---- 同一轮同名两条:不能产出重复 ID ----
        app._save_event_ids({app._change_key(b): {'id': 'wuwa-b1',
                                                   'last_seen': '2026-10-31'}})
        d1 = ev('wuwa', '活动乙', eid='wuwa-b1')
        d2 = ev('wuwa', '活动乙', start='2026-11-09T10:00', eid='wuwa-b2')
        app._stabilize_event_ids([d1, d2], now=datetime(2026, 10, 31, 9, 0))
        check('同轮同名时 ID 不重复', len({d1['id'], d2['id']}), 2)

        # ---- 180 天前的登记被裁剪 ----
        app._save_event_ids({
            app._change_key(a2): {'id': 'hsr-a1', 'last_seen': '2026-10-31'},
            'hsr|旧活动': {'id': 'hsr-old', 'last_seen': '2025-01-01'},
        })
        app._stabilize_event_ids([a2], now=datetime(2026, 10, 31, 9, 0))
        check('过期登记被裁剪', 'hsr|旧活动' in app._load_event_ids(), False)

        # ---- 端到端:改期后 ICS UID 不变 ----
        app._save_event_ids({app._change_key(a2): {'id': 'hsr-a1', 'last_seen': '2026-10-31'}})
        city = ev('hsr', '活动甲', start='2026-11-08T10:00', end='2026-11-15T03:59', eid='hsr-a2')
        app._stabilize_event_ids([city], now=datetime(2026, 10, 31, 9, 0))
        app._state['events'] = [city]
        ics = app.app.test_client().get('/api/calendar.ics').get_data(as_text=True)
        check('ICS UID 用复用后的 ID', re.search(r'UID:(\S+)@ycal', ics).group(1), 'hsr-a1')
        check('DTSTART 已更新', 'DTSTART:20261108T' in ics, True)
    finally:
        app.EVENT_IDS_FILE = real
        app._state['events'] = real_state
        shutil.rmtree(tmp, ignore_errors=True)

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
