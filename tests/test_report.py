# -*- coding: utf-8 -*-
"""用户报错/缺图反馈(/api/report)测试。

离线跑:临时文件替换真实 data/reports.json,不产生副作用。
运行:python3 tests/test_report.py
"""
import os
import sys
import tempfile

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
    tmp = tempfile.mkdtemp(prefix='ycal_rp_')
    app.REPORT_FILE = os.path.join(tmp, 'reports.json')
    c = app.app.test_client()
    H = {'X-Requested-With': 'ycal'}

    check("初始为空", c.get('/api/report').get_json()['items'], [])

    # CSRF
    r = c.post('/api/report', json={'title': '活动A', 'game_id': 'zzz', 'kind': 'missing-image'})
    check("无 CSRF 头被拒", r.status_code, 403)

    # 缺标题
    r = c.post('/api/report', json={'game_id': 'zzz'}, headers=H)
    check("缺标题返回 400", r.status_code, 400)

    # 正常写入
    r = c.post('/api/report', json={'title': '活动A', 'game_id': 'zzz',
                                    'kind': 'missing-image', 'note': '封面没有'}, headers=H)
    j = r.get_json()
    check("写入 ok", j.get('ok'), True)
    items = c.get('/api/report').get_json()['items']
    check("记录条数", len(items), 1)
    check("字段落盘", (items[0]['game_id'], items[0]['title'], items[0]['kind'], items[0]['done']),
          ('zzz', '活动A', 'missing-image', False))

    # 10 分钟内同类型重复 → 去重,不重复计数
    c.post('/api/report', json={'title': '活动A', 'game_id': 'zzz', 'kind': 'missing-image'}, headers=H)
    check("重复反馈被去重", len(c.get('/api/report').get_json()['items']), 1)

    # 不同类型允许并存
    c.post('/api/report', json={'title': '活动A', 'game_id': 'zzz', 'kind': 'wrong-time'}, headers=H)
    check("不同类型单独记", len(c.get('/api/report').get_json()['items']), 2)

    # 非法 kind 回落 other
    c.post('/api/report', json={'title': '活动B', 'game_id': 'hsr', 'kind': 'boom'}, headers=H)
    items = c.get('/api/report').get_json()['items']
    check("非法 kind 回落 other", items[-1]['kind'], 'other')

    # 标题超长截断
    c.post('/api/report', json={'title': 'x' * 300, 'game_id': 'wuwa'}, headers=H)
    items = c.get('/api/report').get_json()['items']
    check("标题截断到 120", len(items[-1]['title']), 120)

    # 上限:写入 400 条,只保留最近 300
    for i in range(400):
        c.post('/api/report', json={'title': '批量%d' % i, 'game_id': 'hsr', 'kind': 'other'}, headers=H)
    items = c.get('/api/report').get_json()['items']
    check("上限截断 300", len(items), 300)
    check("保留最新的一条", items[-1]['title'], '批量399')

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
