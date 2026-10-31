# -*- coding: utf-8 -*-
"""收藏活动「改期」推送测试。

官方改期后,除了列表角标,每天早间的 webhook 推送也应提醒收藏的活动挪了时间。
只取最近 24 小时的 moved 记录,晚间不重复推。

运行:python tests/test_notify_changes.py
"""
import json
import os
import sys
import tempfile
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


def moved(title, at='2026-10-30T04:00:00', frm='2026-11-05T10:00', to='2026-11-07T10:00',
          gid='zzz'):
    return {'type': 'moved', 'at': at, 'game_id': gid, 'title': title,
            'from': {'start': frm, 'end': ''}, 'to': {'start': to, 'end': ''}}


def run(now, events, changes, fav, fav_only=True, evening=False):
    sent = []
    app._state['events'] = events
    app._state['changes'] = changes
    app._state['sources'] = {}
    app._send_notify = lambda title, body: sent.append((title, body)) or True
    app._notify_config = lambda: {'time': '08:30', 'webhook': 'http://example.invalid/hook',
                                  'lead_days': 1, 'fav_only': fav_only}
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, 'userstate.json')
        with open(p, 'w', encoding='utf-8') as f:
            json.dump({'done': {}, 'fav': fav}, f, ensure_ascii=False)
        real, app.USERSTATE_FILE = app.USERSTATE_FILE, p
        try:
            app._daily_notify(now, evening=evening)
        finally:
            app.USERSTATE_FILE = real
    return sent


def main():
    global bad
    backup_ev, backup_ch = app._state['events'], app._state['changes']
    real_send, real_cfg = app._send_notify, app._notify_config
    try:
        now = datetime(2026, 10, 30, 8, 30, tzinfo=app._CST)
        fav = {'zzz|收藏活动': 1700000000000}

        # 1) 收藏活动改期:即使没有开始/结束提醒也要推
        sent = run(now, [], [moved('收藏活动')], fav)
        check('改期也发推送', len(sent), 1)
        title, body = sent[0] if sent else ('', '')
        check('标题含改期计数', '1 个收藏活动改期' in title, True)
        check('正文含原→现', '11月5日 10:00 → 11月7日 10:00' in body, True)
        check('正文带游戏名', '【绝区零】收藏活动' in body, True)

        # 2) 未收藏的活动改期不推(开启 fav_only 时没有其它命中 → 静默)
        sent = run(now, [], [moved('没收藏的活动')], fav)
        check('未收藏的改期不推', len(sent), 0)

        # 3) 超过 24 小时的改期不重复推
        sent = run(now, [], [moved('收藏活动', at='2026-10-28T04:00:00')], fav)
        check('24 小时前的改期不推', len(sent), 0)

        # 4) 晚间不推改期(避免与早间重复)
        sent = run(now, [], [moved('收藏活动')], fav, evening=True)
        check('晚间不推改期', len(sent), 0)

        # 5) 与开始提醒合并:标题同时出现两类计数
        today_ev = {'game_id': 'zzz', 'game': '绝区零', 'title': '今天开始',
                    'kind': 'event', 'start': '2026-10-30T10:00', 'end': None}
        both_fav = dict(fav, **{'zzz|今天开始': 1700000000001})
        sent = run(now, [today_ev], [moved('收藏活动')], both_fav)
        check('合并为一条推送', len(sent), 1)
        check('标题含开始计数', '1 个活动开始' in (sent[0][0] if sent else ''), True)
        check('标题含改期计数', '1 个收藏活动改期' in (sent[0][0] if sent else ''), True)
        check('正文含改期段落', '🔁 收藏活动改期' in (sent[0][1] if sent else ''), True)

        # 6) 关闭 fav_only 也不会给未收藏活动推改期
        sent = run(now, [], [moved('没收藏的活动')], fav, fav_only=False)
        check('关闭 fav_only 不推未收藏改期', '改期' in (sent[0][1] if sent else ''), False)
    finally:
        app._state['events'] = backup_ev
        app._state['changes'] = backup_ch
        app._send_notify = real_send
        app._notify_config = real_cfg

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
