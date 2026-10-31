# -*- coding: utf-8 -*-
"""ICS 订阅「只含收藏」(?fav=1)测试。

日历客户端会长期缓存订阅源,所以收藏变化必须让 ETag 变化——不能只靠 data updated,
否则用户改了收藏,订阅日历还是旧内容(304)。

运行:python tests/test_ics_fav.py
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
    backup_state = dict(app._state)
    real_userstate = app._load_userstate
    client = app.app.test_client()
    fav = {'hsr|活动A': 1690000000000, 'zzz|活动B': -1690000000001}   # B 已取消收藏
    app._load_userstate = lambda: {'fav': dict(fav)}
    try:
        app._state.update({'updated': '2026-10-31T12:00:00', 'events': list(EVS)})
        r_all = client.get('/api/calendar.ics')
        check('全量订阅含两条', r_all.get_data(as_text=True).count('BEGIN:VEVENT'), 2)
        check('全量 ETag 标记 all', '-all-' in r_all.headers.get('ETag'), True)

        r_fav = client.get('/api/calendar.ics?fav=1')
        body = r_fav.get_data(as_text=True)
        check('收藏订阅只剩已收藏', body.count('BEGIN:VEVENT'), 1)
        check('包含收藏的 A', '活动A' in body, True)
        check('排除未收藏/已取消的 B', '活动B' in body, False)
        check('收藏 ETag 与全量不同', r_fav.headers.get('ETag') != r_all.headers.get('ETag'), True)
        check('收藏 ETag 标记 fav', '-fav-' in r_fav.headers.get('ETag'), True)
        etag = r_fav.headers.get('ETag')

        r304 = client.get('/api/calendar.ics?fav=1', headers={'If-None-Match': etag})
        check('收藏未变 → 304', r304.status_code, 304)

        # 只改收藏(事件数据与 updated 不变),ETag 必须变化,否则日历永远不更新
        fav.clear()
        fav['zzz|活动B'] = 1690000000002
        r_new = client.get('/api/calendar.ics?fav=1', headers={'If-None-Match': etag})
        check('改收藏后 → 200', r_new.status_code, 200)
        body2 = r_new.get_data(as_text=True)
        check('改收藏后只剩 B', '活动B' in body2 and '活动A' not in body2, True)
        check('新 ETag 不同', r_new.headers.get('ETag') != etag, True)

        r_combo = client.get('/api/calendar.ics?fav=1&games=hsr')
        check('收藏+游戏筛选组合为空', r_combo.get_data(as_text=True).count('BEGIN:VEVENT'), 0)
        r_off = client.get('/api/calendar.ics?fav=0')
        check('fav=0 保持全量口径', r_off.get_data(as_text=True).count('BEGIN:VEVENT'), 2)
    finally:
        app._load_userstate = real_userstate
        app._state.clear()
        app._state.update(backup_state)

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
