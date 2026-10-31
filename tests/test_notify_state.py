# -*- coding: utf-8 -*-
"""每日提醒去重 / 失败重试测试。

历史问题:sent 标记只存内存,08:30 推过之后中午重启服务,会立刻把当天汇总再推一次。
现在标记落盘(data/notify_state.json):重启不重复;推送失败则下一分钟重试,
最多 3 次后放弃,避免 webhook 长期不可用时无限重试。

运行:python tests/test_notify_state.py
"""
import json
import os
import shutil
import sys
import tempfile
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
    global bad
    tmp = tempfile.mkdtemp()
    real_state_file = app.NOTIFY_STATE_FILE
    real_cfg = app._notify_config
    real_daily = app._daily_notify
    app.NOTIFY_STATE_FILE = os.path.join(tmp, 'notify_state.json')
    calls = []

    def fake_cfg():
        return {'time': '08:30', 'evening': '', 'lead_days': 1, 'fav_only': False}

    def daily(now=None, evening=False):
        calls.append((now.strftime('%Y-%m-%d %H:%M'), evening))
        return daily.result

    daily.result = True
    app._notify_config = fake_cfg
    app._daily_notify = daily

    now = datetime(2026, 10, 31, 9, 0)
    try:
        check('未到点不推送', app._notify_once(datetime(2026, 10, 31, 8, 0)), {})
        marks = app._notify_once(now, {})
        check('到点推送一次', len(calls), 1)
        check('成功后标记 done', marks['2026-10-31:main']['done'], True)
        check('记录推送时间', marks['2026-10-31:main']['at'], '2026-10-31T09:00:00')
        check('标记已落盘', os.path.exists(app.NOTIFY_STATE_FILE), True)

        marks = app._notify_once(now, marks)
        check('同一天不重复推送', len(calls), 1)

        # 模拟重启:从文件读回标记,再次检查不应推送
        marks2 = app._load_notify_marks()
        check('重启读回标记', marks2.get('2026-10-31:main', {}).get('done'), True)
        app._notify_once(now, marks2)
        check('重启后不重复推送', len(calls), 1)

        # 晚间场次独立:主时段已过,晚间 20:00 到点
        calls.clear()
        app._notify_config = lambda: {'time': '21:00', 'evening': '20:00',
                                      'lead_days': 1, 'fav_only': False}
        marks = app._notify_once(datetime(2026, 10, 31, 20, 30), {})
        check('晚间到点推送一次', len(calls), 1)
        check('推送的是晚间场', calls[0][1], True)
        check('晚间独立标记', marks['2026-10-31:evening']['done'], True)

        # 失败重试:最多 3 次
        calls.clear()
        app._notify_config = fake_cfg
        daily.result = False
        marks = {}
        for i in range(4):
            marks = app._notify_once(now, marks)
        check('失败后最多重试 3 次', len(calls), 3)
        check('第 3 次后标记 done', marks['2026-10-31:main']['done'], True)
        check('标记 ok=False', marks['2026-10-31:main']['ok'], False)

        # 没有内容可推(None)视为完成,不重试
        calls.clear()
        daily.result = None
        marks = app._notify_once(now, {})
        check('无内容只检查一次', len(calls), 1)
        check('无内容也标记 done', marks['2026-10-31:main']['done'], True)
        check('无内容 ok 记为 None', marks['2026-10-31:main']['ok'], None)

        # 7 天前的标记会被裁掉
        old = (now - timedelta(days=8)).strftime('%Y-%m-%d')
        marks = app._notify_once(now, {old + ':main': {'done': True}, '2026-10-31:main': {'done': True}})
        check('裁剪 7 天前标记', old + ':main' in marks, False)
        check('保留当天标记', '2026-10-31:main' in marks, True)

        with open(app.NOTIFY_STATE_FILE, encoding='utf-8') as f:
            saved = json.load(f)
        check('状态文件结构', isinstance(saved.get('marks'), dict), True)
    finally:
        app.NOTIFY_STATE_FILE = real_state_file
        app._notify_config = real_cfg
        app._daily_notify = real_daily
        shutil.rmtree(tmp, ignore_errors=True)

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
