# -*- coding: utf-8 -*-
"""「只推送收藏的活动」测试。

每日推送默认推全部活动;开启 fav_only 后只推 userstate.json 里点过 ★ 的活动,
没有命中就静默(不再每天发「没有新活动」的空推送)。

运行:python3 tests/test_notify_fav.py
"""
import json
import os
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app  # noqa: E402

REAL_NOTIFY_CONFIG = app._notify_config   # run() 会替换成桩,API 用例前需还原
bad = 0


def check(label, got, expect):
    global bad
    ok = got == expect
    if not ok:
        bad += 1
    print("[%s] %s: got=%r expect=%r" % ('OK ' if ok else 'FAIL', label, got, expect))


def ev(title, start='2026-10-30T10:00', end=None):
    return {'game_id': 'zzz', 'game': '绝区零', 'title': title,
            'kind': 'event', 'start': start, 'end': end}


def run(now, events, fav, fav_only=True, userstate_path=None):
    sent = []
    app._state['events'] = events
    app._state['sources'] = {}
    app._send_notify = lambda title, body: sent.append((title, body)) or True
    app._notify_config = lambda: {'time': '08:30', 'webhook': 'http://example.invalid/hook',
                                  'lead_days': 1, 'fav_only': fav_only}
    if userstate_path:
        with open(userstate_path, 'w', encoding='utf-8') as f:
            json.dump({'done': {}, 'fav': fav}, f, ensure_ascii=False)
        real, app.USERSTATE_FILE = app.USERSTATE_FILE, userstate_path
        try:
            app._daily_notify(now)
        finally:
            app.USERSTATE_FILE = real
    else:
        app._daily_notify(now)
    return sent


def main():
    global bad
    now = datetime(2026, 10, 30, 8, 30, tzinfo=app._CST)
    evs = [ev('收藏的活动'), ev('未收藏的活动')]
    tdir = tempfile.mkdtemp()
    ust = os.path.join(tdir, 'userstate.json')

    # 1) fav_only:只推收藏
    sent = run(now, evs, {'zzz|收藏的活动': 1700000000000}, userstate_path=ust)
    check('只推一条汇总', len(sent), 1)
    title, body = sent[0] if sent else ('', '')
    check('计数只含收藏活动', '1 个活动开始' in title, True)
    check('正文含收藏活动', '收藏的活动' in body, True)
    check('正文不含未收藏活动', '未收藏的活动' in body, False)

    # 2) fav_only 且没有收藏:静默,不空推
    sent = run(now, evs, {}, userstate_path=ust)
    check('没有收藏时不发空推送', len(sent), 0)

    # 3) 收藏被取消(负时间戳墓碑)视为未收藏
    sent = run(now, evs, {'zzz|收藏的活动': -1700000000000}, userstate_path=ust)
    check('取消收藏后不再推送', len(sent), 0)

    # 4) 关闭 fav_only:恢复推送全部
    sent = run(now, evs, {'zzz|收藏的活动': 1700000000000}, fav_only=False, userstate_path=ust)
    check('关闭后推送全部', '2 个活动开始' in (sent[0][0] if sent else ''), True)

    # 5) 配置 API 接受 fav_only(局部更新,不动其它字段)
    cfg_file = os.path.join(tdir, 'notify.json')
    real_nf, app.NOTIFY_FILE = app.NOTIFY_FILE, cfg_file
    app._notify_config = REAL_NOTIFY_CONFIG
    try:
        client = app.app.test_client()
        r = client.post('/api/notify-config', json={'fav_only': True},
                        headers={'X-Requested-With': 'ycal'})
        d = r.get_json() or {}
        check('POST 返回 fav_only=true', d.get('fav_only'), True)
        g = client.get('/api/notify-config').get_json() or {}
        check('GET 读回 fav_only=true', g.get('fav_only'), True)
        cfg = json.load(open(cfg_file, encoding='utf-8'))
        check('落盘字段保存', cfg.get('fav_only'), True)
        r2 = client.post('/api/notify-config', json={'fav_only': False},
                         headers={'X-Requested-With': 'ycal'})
        check('可再关闭', (r2.get_json() or {}).get('fav_only'), False)
    finally:
        app.NOTIFY_FILE = real_nf

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
