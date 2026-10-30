# -*- coding: utf-8 -*-
"""运行状态接口 /api/health 测试。

给每日自动化 / 云端 NPC / 外部监控用:一次拿到更新时间、是否陈旧、
事件数、各数据源成败与刷新中状态。内部错误源(_system)不对外暴露。

运行:python3 tests/test_health.py
"""
import os
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


def main():
    orig = {k: app._state[k] for k in ('updated', 'events', 'sources', 'refreshing')}
    c = app.app.test_client()
    try:
        app._state['events'] = [{'id': 'a', 'image': 'x.png'}, {'id': 'b'}, {'id': 'c'}]
        app._state['sources'] = {'hsr': {'ok': True, 'count': 10},
                                 'bilibili': {'ok': False, 'count': 0},
                                 '_system': {'ok': False, 'count': 0}}
        app._state['refreshing'] = False

        # 1. 新鲜数据
        app._state['updated'] = datetime.now().isoformat(timespec='seconds')
        d = c.get('/api/health').get_json()
        check("ok 恒为 true", d['ok'], True)
        check("事件数", d['events'], 3)
        check("缺图条数(有图的除外)", d['missing_images'], 2)
        check("新鲜数据不判陈旧", d['stale'], False)
        check("新鲜数据小时数约 0", d['stale_hours'], 0.0)
        check("刷新中状态", d['refreshing'], False)
        check("暴露正常数据源", sorted(d['sources'].keys()), ['bilibili', 'hsr'])
        check("数据源成败与条数", d['sources']['hsr'], {'ok': True, 'count': 10})
        check("内部错误源不外露", '_system' in d['sources'], False)
        check("带服务器时间", bool(d['server_time']), True)

        # 2. 超过 24 小时
        app._state['updated'] = (datetime.now() - timedelta(hours=30)).isoformat(timespec='seconds')
        d = c.get('/api/health').get_json()
        check("30 小时未更新判陈旧", d['stale'], True)
        check("陈旧小时数约 30", 29.9 <= d['stale_hours'] <= 30.1, True)

        # 3. 非法 / 缺失更新时间
        app._state['updated'] = 'not-a-date'
        d = c.get('/api/health').get_json()
        check("非法时间不判陈旧", d['stale'], False)
        check("非法时间小时数为 null", d['stale_hours'], None)
        app._state['updated'] = None
        d = c.get('/api/health').get_json()
        check("无更新时间不判陈旧", d['stale'], False)
        check("无更新时间小时数为 null", d['stale_hours'], None)

        # 4. 刷新中
        app._state['refreshing'] = True
        d = c.get('/api/health').get_json()
        check("刷新中状态透出", d['refreshing'], True)
    finally:
        for k, v in orig.items():
            app._state[k] = v

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
