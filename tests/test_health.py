# -*- coding: utf-8 -*-
"""/api/health 监控字段测试。

外部脚本/监控现在能一次拿到:真活动数、进行中、更早开始·结束未知、
近 14 天变更条数——口径必须与前端列表/统计页/ICS 一致,不能各算各的。

运行:python tests/test_health.py
"""
import os
import sys
from datetime import timedelta

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
    backup_state = dict(app._state)
    backup_changes = app._load_changes
    now = app._bj_now().replace(tzinfo=None, microsecond=0)
    iso = lambda d: (now + timedelta(days=d)).isoformat(timespec='seconds')
    day = lambda d: (now + timedelta(days=d)).strftime('%Y-%m-%d')

    events = [
        # 进行中:两天前开始,明天结束
        {'id': 'run', 'kind': 'event', 'start': iso(-2), 'end': iso(1), 'image': 'x.jpg'},
        # 进行中:5 天前开始,结束未知(未到 30 天)
        {'id': 'noend', 'kind': 'event', 'start': iso(-5)},
        # 已结束(防御性:状态里通常已被 _drop_expired 清理)
        {'id': 'done', 'kind': 'event', 'start': iso(-9), 'end': day(-1)},
        # 未来
        {'id': 'future', 'kind': 'event', 'start': iso(3)},
        # 更早开始·结束未知:40 天前开始且无结束
        {'id': 'stale', 'kind': 'event', 'start': day(-40)},
        # 资讯:不计入真活动,也不算进行中(即使今天开始)
        {'id': 'info', 'kind': 'info', 'start': iso(0), 'date': iso(0)},
    ]
    changes = {
        'fresh': {'type': 'new', 'at': iso(-1)},
        'edge': {'type': 'moved', 'at': iso(-13), 'rev': 2},
        'old': {'type': 'new', 'at': iso(-20)},
    }

    app._load_changes = lambda: dict(changes)
    client = app.app.test_client()
    try:
        app._state.update({'updated': iso(0), 'events': events,
                           'sources': {'manual': {'ok': True, 'count': 3}},
                           'refreshing': False})
        r = client.get('/api/health')
        check('200', r.status_code, 200)
        d = r.get_json()
        check('总条目含资讯', d['events'], 6)
        check('真活动数', d['events_real'], 5)
        check('进行中:2 条(有结束 + 未超 30 天无结束)', d['ongoing'], 2)
        check('更早开始·结束未知', d['stale_unknown'], 1)
        check('近 14 天变更', d['changes_recent'], 2)
        check('缺结束时间:noend / future / stale 共 3 条', d['missing_end'], 3)
        check('缺图:除 run 外 4 条', d['missing_images'], 4)
        check('默认无刷新错误', d['last_error'], None)
        check('默认无错误时间', d['last_error_at'], None)
        check('数据源状态保留', d['sources']['manual'], {'ok': True, 'count': 3})
        check('未过期', d['stale'], False)

        # 辅助函数边界:开始超过 30 天但已有结束时间 → 不算「结束未知」
        check('有结束时间的不算 stale_unknown',
              app._is_stale_unknown({'start': day(-40), 'end': day(-39)}), False)
        check('无开始时间的不算 stale_unknown', app._is_stale_unknown({'start': None}), False)
        # 与前端一致按时刻比较(不是只看日期):正好 30 天前同刻不算,早 1 分钟就算
        check('刚好 30 天前(同刻)不算 stale',
              app._is_stale_unknown({'start': iso(-30)}, now=now), False)
        check('30 天前再多 1 分钟算 stale',
              app._is_stale_unknown({'start': (now - timedelta(days=30, minutes=1))
                                     .isoformat(timespec='seconds')}, now=now), True)
        check('31 天前算 stale', app._is_stale_unknown({'start': day(-31)}, now=now), True)

        # updated 超过 24 小时 → stale
        app._state['updated'] = iso(-2)
        d2 = client.get('/api/health').get_json()
        check('超过 24 小时标记 stale', d2['stale'], True)
        check('stale_hours 约为 48', round(d2['stale_hours']), 48)

        # 全链路刷新失败:旧数据沿用,但 health 必须能看到失败原因
        # (失败明细原先只写进 sources._system,而 health 会过滤下划线开头的内部源)
        real_fetch = app.scrapers.fetch_all

        def boom():
            raise RuntimeError('fetch boom')
        app.scrapers.fetch_all = boom
        try:
            app.do_refresh()
        finally:
            app.scrapers.fetch_all = real_fetch
        d3 = client.get('/api/health').get_json()
        check('失败原因可见', 'fetch boom' in (d3.get('last_error') or ''), True)
        check('失败时间已记录', bool(d3.get('last_error_at')), True)
        check('内部源仍不对外', '_system' in (d3.get('sources') or {}), False)
    finally:
        app._load_changes = backup_changes
        app._state.clear()
        app._state.update(backup_state)

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
