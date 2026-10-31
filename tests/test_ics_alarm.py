# -*- coding: utf-8 -*-
"""ICS 订阅「开始前 N 分钟提醒」(?alarm=30)测试。

订阅日历的好处是官方改期后原地更新;但活动开始没人提醒也容易错过。
?alarm=30 会在每条 VEVENT 里写一个 VALARM(提前 30 分钟 DISPLAY),
由日历客户端本地提醒。ETag 必须带上 alarm,否则开关提醒后客户端仍拿 304。

运行:python tests/test_ics_alarm.py
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


EVS = [
    {'id': 'a', 'game_id': 'hsr', 'game': '星铁', 'title': '活动A', 'category': '活动',
     'kind': 'event', 'start': '2027-11-01T10:00', 'end': '2027-11-10T03:59'},
    {'id': 'b', 'game_id': 'zzz', 'game': '绝区零', 'title': '活动B', 'category': '活动',
     'kind': 'event', 'start': '2027-11-02T10:00', 'end': '2027-11-12T03:59'},
]


def main():
    backup = dict(app._state)
    client = app.app.test_client()
    try:
        app._state.update({'updated': '2026-10-31T12:00:00', 'events': list(EVS)})
        plain = client.get('/api/calendar.ics')
        ptxt = plain.get_data(as_text=True)
        check('默认不带提醒', 'BEGIN:VALARM' in ptxt, False)
        check('默认 ETag 无 alarm 标记', '-a30' in (plain.headers.get('ETag') or ''), False)
        petag = plain.headers.get('ETag')

        r = client.get('/api/calendar.ics?alarm=30')
        txt = r.get_data(as_text=True)
        check('alarm=30 每条事件都有 VALARM', txt.count('BEGIN:VALARM'), 2)
        check('提前 30 分钟触发', 'TRIGGER:-PT30M' in txt, True)
        check('DISPLAY 动作与描述', 'ACTION:DISPLAY' in txt and '活动开始提醒' in txt, True)
        check('alarm ETag 与默认不同', r.headers.get('ETag') != petag, True)
        check('alarm ETag 带 a30 标记', '-a30' in (r.headers.get('ETag') or ''), True)
        e = r.headers.get('ETag')
        r304 = client.get('/api/calendar.ics?alarm=30', headers={'If-None-Match': e})
        check('提醒参数未变 → 304', r304.status_code, 304)

        rmax = client.get('/api/calendar.ics?alarm=1440')
        check('1440 分钟(24h)也有效', 'BEGIN:VALARM' in rmax.get_data(as_text=True), True)

        for q, label in (('alarm=abc', '非数字'), ('alarm=0', '0 分钟'),
                         ('alarm=-5', '负值'), ('alarm=2000', '超过 1440')):
            rr = client.get('/api/calendar.ics?' + q)
            check('非法 alarm(%s)按不提醒' % label,
                  'BEGIN:VALARM' in rr.get_data(as_text=True), False)
            check('非法 alarm(%s) ETag 与默认一致' % label,
                  rr.headers.get('ETag'), petag)

        src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                'static', 'index.html'), encoding='utf-8').read()
        check('设置里有「订阅带提前提醒」', '订阅带提前提醒' in src, True)
        check('开关函数已实现', 'function toggleIcsAlarm(' in src, True)
        check('订阅链接会追加 alarm=30', "settings.icsAlarm?'alarm=30':''" in src, True)
    finally:
        app._state.clear()
        app._state.update(backup)

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
