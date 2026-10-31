# -*- coding: utf-8 -*-
"""单点里程碑口径测试(后端)。

版本上线 / 前瞻直播只有开始时刻,没有持续期:
- 不该算「缺结束时间」,也不该算「更早开始·结束未知」
- 不该冒充「进行中」
- 已经过去的日子不再进 ICS 订阅(避免补 2 天窗口后塞回旧直播)
普通无结束时间的活动口径保持不变。

运行:python tests/test_point_items.py
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
    now = app._bj_now().replace(tzinfo=None, microsecond=0)
    iso = lambda d: (now + timedelta(days=d)).isoformat(timespec='seconds')
    day = lambda d: (now + timedelta(days=d)).strftime('%Y-%m-%d')

    check('版本上线识别为单点', app._is_point_item({'title': '4.7版本「此刻将群星付之一笑」上线'}), True)
    check('前瞻通讯识别为单点', app._is_point_item({'title': '3.7版本前瞻通讯（直播）'}), True)
    check('正式上线识别为单点', app._is_point_item({'title': '云·终末地 10.15 正式上线'}), True)
    check('普通活动不算单点', app._is_point_item({'title': '限时活动「画外遗光」'}), False)
    check('资讯不算单点(本就无结束)', app._is_point_item({'title': '4.1版本上线', 'kind': 'info'}), False)

    check('过去的前瞻直播不算更早未知', app._is_stale_unknown({'title': '前瞻特别节目（直播）', 'start': day(-40)},
                                                        now=now), False)
    check('过去的版本上线不算进行中', app._is_ongoing({'title': '1.6版本上线', 'start': day(-20)}, now=now), False)
    check('普通无结束近期活动仍算进行中', app._is_ongoing({'title': '普通活动', 'start': iso(-5)}, now=now), True)

    events = [
        {'id': 'normal', 'kind': 'event', 'title': '普通活动', 'start': iso(-5)},
        {'id': 'point_future', 'kind': 'event', 'title': '4.6版本上线', 'start': iso(3)},
        {'id': 'point_old', 'kind': 'event', 'title': '3.9版本前瞻通讯（直播）', 'start': day(-35)},
        {'id': 'info', 'kind': 'info', 'title': '公告', 'date': iso(0)},
    ]

    app._state.update({'updated': iso(0), 'events': events,
                       'sources': {'manual': {'ok': True, 'count': 1}},
                       'refreshing': False})
    client = app.app.test_client()
    try:
        h = client.get('/api/health').get_json()
        check('缺结束时间只算普通活动', h['missing_end'], 1)
        check('更早开始未知不含单点', h['stale_unknown'], 0)
        check('进行中不含单点', h['ongoing'], 1)
        check('dq=noend 与 health 同口径',
              len(app._dq_filter(events, 'noend', now)), 1)
        ics = client.get('/api/calendar.ics').get_data(as_text=True)
        check('过去的前瞻直播不进订阅', '3.9版本前瞻通讯' not in ics, True)
        check('未来的版本上线仍在订阅', '4.6版本上线' in ics, True)
    finally:
        app._state['events'] = []
        app._state['sources'] = {}

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
