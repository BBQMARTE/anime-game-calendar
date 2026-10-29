# -*- coding: utf-8 -*-
"""ICS 订阅按游戏筛选(?games=)测试。

离线跑:直接注入 _state['events'],用 test_client 请求,断言产出的事件归属。
运行:python3 tests/test_ics_filter.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app  # noqa: E402

bad = 0


def check(label, got, expect):
    global bad
    ok = got == expect
    if not ok:
        bad += 1
    print("[%s] %s: got=%r expect=%r" % ('OK ' if ok else 'FAIL', label, got, expect))


def ics(events, qs=''):
    app._state['events'] = events
    with app.app.test_client() as c:
        r = c.get('/api/calendar.ics' + qs)
    return r.status_code, r.get_data(as_text=True)


def main():
    evs = [
        {'id': 'a', 'game_id': 'hsr', 'game': '崩坏：星穹铁道', 'title': '活动A',
         'kind': 'event', 'start': '2026-11-01T10:00', 'end': '2026-11-10T03:59'},
        {'id': 'b', 'game_id': 'zzz', 'game': '绝区零', 'title': '活动B',
         'kind': 'event', 'start': '2026-11-02T10:00', 'end': '2026-11-12T03:59'},
        {'id': 'c', 'game_id': 'hsr', 'game': '崩坏：星穹铁道', 'title': '公告C',
         'kind': 'info', 'start': None, 'end': None},
    ]

    st, body = ics(evs)
    check("不带参数返回 200", st, 200)
    check("不带参数含全部真活动", body.count('BEGIN:VEVENT'), 2)
    check("公告(info)不进 ICS", '公告C' in body, False)

    st, body = ics(evs, '?games=hsr')
    check("games=hsr 只留星铁", body.count('BEGIN:VEVENT'), 1)
    check("games=hsr 含活动A", '活动A' in body, True)
    check("games=hsr 不含活动B", '活动B' in body, False)

    st, body = ics(evs, '?games=zzz,hsr')
    check("多游戏逗号分隔", body.count('BEGIN:VEVENT'), 2)

    st, body = ics(evs, '?games=%20zzz%20')
    check("URL 编码/空格容错", body.count('BEGIN:VEVENT'), 1)

    st, body = ics(evs, '?games=unknown')
    check("未知游戏不产出事件", body.count('BEGIN:VEVENT'), 0)

    st, body = ics(evs, '?games=')
    check("空参数视为不过滤", body.count('BEGIN:VEVENT'), 2)

    st, body = ics(evs, '?games=,,')
    check("只有逗号视为不过滤", body.count('BEGIN:VEVENT'), 2)

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
