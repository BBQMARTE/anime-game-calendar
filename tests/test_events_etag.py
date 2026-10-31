# -*- coding: utf-8 -*-
"""/api/events 的 ETag / 304 测试。

前端每 60 秒轮询一次全量(约 130KB)。带 ETag 后数据没变时浏览器只拿 304,
既省流量也省服务端序列化;刷新后 updated 变化,必须重新返回 200。

运行:python tests/test_events_etag.py
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


def main():
    global bad
    backup = dict(app._state)
    client = app.app.test_client()
    try:
        app._state.update({'updated': '2026-10-31T08:00:00',
                           'events': [{'id': 'a', 'title': '活动甲'}],
                           'changes': [], 'refreshing': False})
        r1 = client.get('/api/events')
        check('首次请求 200', r1.status_code, 200)
        etag = r1.headers.get('ETag')
        check('返回 ETag', bool(etag), True)
        check('Cache-Control 为 no-cache', r1.headers.get('Cache-Control'), 'no-cache')
        check('首包带事件数据', r1.get_json()['events'][0]['id'], 'a')

        r2 = client.get('/api/events', headers={'If-None-Match': etag})
        check('ETag 一致时返回 304', r2.status_code, 304)
        check('304 无响应体', len(r2.data), 0)
        check('304 也带 ETag', r2.headers.get('ETag'), etag)

        app._state['updated'] = '2026-10-31T09:00:00'
        r3 = client.get('/api/events', headers={'If-None-Match': etag})
        check('刷新后 ETag 变化 → 200', r3.status_code, 200)
        check('新 ETag 与旧不同', r3.headers.get('ETag') != etag, True)

        app._state['updated'] = '2026-10-31T09:00:00'
        app._state['events'] = [{'id': 'a'}, {'id': 'b'}]
        r4 = client.get('/api/events', headers={'If-None-Match': r3.headers.get('ETag')})
        check('事件数变化也触发 200', r4.status_code, 200)
    finally:
        app._state.clear()
        app._state.update(backup)

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
