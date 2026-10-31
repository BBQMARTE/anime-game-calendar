# -*- coding: utf-8 -*-
"""/api/calendar.ics 的 ETag / 304 测试。

日历客户端（Apple / Google）会周期拉取订阅源。每次重新生成整份 ICS（约 30KB）
既费服务端 CPU 也费流量；数据没变时应只回 304。ETag 需覆盖 data updated、
事件数,以及 ?games= / ?cats= 筛选(同一份数据不同筛选不能共用缓存)。

运行:python tests/test_ics_cache.py
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
    # 补足体积,让 gzip 阈值(≥1KB)生效
    {'id': 'c', 'game_id': 'wuwa', 'game': '鸣潮', 'title': '活动C', 'category': '活动',
     'kind': 'event', 'start': '2027-11-03T10:00', 'end': '2027-11-13T03:59'},
    {'id': 'd', 'game_id': 'wuwa', 'game': '鸣潮', 'title': '活动D', 'category': '活动',
     'kind': 'event', 'start': '2027-11-04T10:00', 'end': '2027-11-14T03:59'},
    {'id': 'e', 'game_id': 'wuwa', 'game': '鸣潮', 'title': '活动E', 'category': '活动',
     'kind': 'event', 'start': '2027-11-05T10:00', 'end': '2027-11-15T03:59'},
]


def main():
    backup = dict(app._state)
    client = app.app.test_client()
    try:
        app._state.update({'updated': '2026-10-31T11:00:00', 'events': list(EVS)})
        r1 = client.get('/api/calendar.ics')
        check('200', r1.status_code, 200)
        etag = r1.headers.get('ETag')
        check('返回 ETag', bool(etag), True)
        check('Cache-Control no-cache', r1.headers.get('Cache-Control'), 'no-cache')
        check('首包有内容', 'BEGIN:VEVENT' in r1.get_data(as_text=True), True)

        r2 = client.get('/api/calendar.ics', headers={'If-None-Match': etag})
        check('ETag 一致 → 304', r2.status_code, 304)
        check('304 无响应体', len(r2.data), 0)
        check('304 仍带 ETag', r2.headers.get('ETag'), etag)

        app._state['updated'] = '2026-10-31T11:30:00'
        r3 = client.get('/api/calendar.ics', headers={'If-None-Match': etag})
        check('刷新后 → 200', r3.status_code, 200)
        check('新 ETag 与旧不同', r3.headers.get('ETag') != etag, True)

        # 同一份数据,不同筛选:不能共用缓存(否则只订星铁的设备会拿到全量)
        e_all = client.get('/api/calendar.ics').headers.get('ETag')
        e_hsr = client.get('/api/calendar.ics?games=hsr').headers.get('ETag')
        check('?games= 生成独立 ETag', e_all != e_hsr, True)
        r4 = client.get('/api/calendar.ics?games=zzz', headers={'If-None-Match': e_hsr})
        check('筛选不一致时不误回 304', r4.status_code, 200)
        check('筛选响应只含指定游戏', '活动B' in r4.get_data(as_text=True)
              and '活动A' not in r4.get_data(as_text=True), True)

        # 顺序无关:?games=hsr,zzz 与 ?games=zzz,hsr 是同一个订阅
        e1 = client.get('/api/calendar.ics?games=hsr,zzz').headers.get('ETag')
        e2 = client.get('/api/calendar.ics?games=zzz,hsr').headers.get('ETag')
        check('筛选顺序不影响 ETag', e1, e2)

        # gzip 客户端同样能拿到 304
        zg = client.get('/api/calendar.ics', headers={'Accept-Encoding': 'gzip'})
        check('gzip 响应', zg.headers.get('Content-Encoding'), 'gzip')
        zg304 = client.get('/api/calendar.ics',
                           headers={'Accept-Encoding': 'gzip',
                                    'If-None-Match': zg.headers.get('ETag')})
        check('gzip 条件下 304 生效', zg304.status_code, 304)
    finally:
        app._state.clear()
        app._state.update(backup)

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
