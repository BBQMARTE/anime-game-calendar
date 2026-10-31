# -*- coding: utf-8 -*-
"""CSV 导出接口 /api/export.csv 测试。

导出要能直接双击用 Excel 打开:必须带 UTF-8 BOM,否则中文乱码。
筛选口径与 ICS 订阅一致(games / cats),含所有条目并用「类型」列区分活动与资讯。

运行:python3 tests/test_export_csv.py
"""
import csv
import io
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


EVENTS = [
    {'game_id': 'hsr', 'game': '崩坏：星穹铁道', 'title': '活动, "限定"', 'category': '活动',
     'kind': 'event', 'start': '2026-11-01T10:00', 'end': '2026-11-10T03:59',
     'src': 'manual', 'link': 'https://example.com/a?b=1,2',
     'image': 'https://example.com/cover.jpg'},
    {'game_id': 'zzz', 'game': '绝区零', 'title': '签到活动', 'category': '签到',
     'kind': 'event', 'start': '2026-10-30T10:00', 'src': 'bilibili'},
    {'game_id': 'hsr', 'game': '崩坏：星穹铁道', 'title': '自动资讯', 'category': '资讯',
     'kind': 'info', 'date': '2026-10-20T10:00'},
    {'game_id': 'wuwa', 'game': '鸣潮', 'title': '无日期活动', 'category': '活动',
     'kind': 'event', '_nodate': True, 'date': '2026-10-21T10:00'},
    {'game_id': 'arknights', 'game': '明日方舟', 'title': '老活动·结束未知', 'category': '活动',
     'kind': 'event', 'start': '2026-08-01T10:00', 'src': 'bilibili'},
]


def rows_of(resp):
    text = resp.data.decode('utf-8-sig')
    return list(csv.reader(io.StringIO(text)))


def main():
    app._state['events'] = EVENTS
    c = app.app.test_client()

    r = c.get('/api/export.csv')
    check("导出返回 200", r.status_code, 200)
    check("带 UTF-8 BOM", r.data[:3], b'\xef\xbb\xbf')
    check("Content-Type 为 UTF-8 CSV", r.headers.get('Content-Type'), 'text/csv; charset=utf-8')
    check("附件下载头", 'attachment' in (r.headers.get('Content-Disposition') or ''), True)

    rows = rows_of(r)
    check("表头", rows[0], ['游戏', '标题', '分类', '开始', '结束', '类型', '来源', '链接'])
    check("全部条目都导出(含资讯/无日期)", len(rows) - 1, 5)
    check("按开始时间升序,无 start 用 date", [x[1] for x in rows[1:]],
          ['老活动·结束未知', '自动资讯', '无日期活动', '签到活动', '活动, "限定"'])
    by_title = {x[1]: x for x in rows[1:]}
    check("逗号/引号标题原样还原", by_title['活动, "限定"'][1], '活动, "限定"')
    check("人工条目来源标为已核实", by_title['活动, "限定"'][6], '已核实')
    check("B站条目来源标为 B站", by_title['签到活动'][6], 'B站')
    check("爬虫条目来源标为自动", by_title['自动资讯'][6], '自动')
    check("资讯条目标为资讯", by_title['自动资讯'][5], '资讯')
    check("带逗号的链接完整还原", by_title['活动, "限定"'][7], 'https://example.com/a?b=1,2')

    rows = rows_of(c.get('/api/export.csv?games=hsr'))
    check("?games=hsr 只导出该游戏", [x[1] for x in rows[1:]], ['自动资讯', '活动, "限定"'])
    rows = rows_of(c.get('/api/export.csv?games=wuwa'))
    check("无日期条目同样能按游戏筛出", [x[1] for x in rows[1:]], ['无日期活动'])
    rows = rows_of(c.get('/api/export.csv?cats=签到'))
    check("?cats=签到 只导出签到", [x[1] for x in rows[1:]], ['签到活动'])
    rows = rows_of(c.get('/api/export.csv?games=hsr&cats=活动'))
    check("游戏+分类组合筛选", [x[1] for x in rows[1:]], ['活动, "限定"'])

    # 收藏导出:只看 userstate 里的收藏键(hsr|活动 / wuwa|无日期),忽略筛选
    app._load_userstate = lambda: {'fav': {'hsr|活动, "限定"': 1690000000000,
                                           'wuwa|无日期活动': 1690000000001,
                                           'zzz|已取消的收藏': -1690000000002}}
    rows = rows_of(c.get('/api/export.csv?fav=1'))
    check("?fav=1 只导出收藏", [x[1] for x in rows[1:]], ['无日期活动', '活动, "限定"'])
    rows = rows_of(c.get('/api/export.csv?fav=1&games=wuwa'))
    check("收藏 + 游戏筛选可组合", [x[1] for x in rows[1:]], ['无日期活动'])
    rows = rows_of(c.get('/api/export.csv?fav=0'))
    check("fav=0 不过滤", len(rows) - 1, 5)

    # 数据质量筛选(?dq=):与列表上的「缺图 / 缺结束 / 更早开始未知」同一口径
    rows = rows_of(c.get('/api/export.csv?dq=noimg'))
    check("?dq=noimg 只导出缺图活动(不含资讯)", [x[1] for x in rows[1:]],
          ['老活动·结束未知', '无日期活动', '签到活动'])
    rows = rows_of(c.get('/api/export.csv?dq=noend'))
    check("?dq=noend 只导出缺结束活动(资讯本就没有结束,不算)", [x[1] for x in rows[1:]],
          ['老活动·结束未知', '无日期活动', '签到活动'])
    rows = rows_of(c.get('/api/export.csv?dq=stale'))
    check("?dq=stale 只导出更早开始·结束未知", [x[1] for x in rows[1:]],
          ['老活动·结束未知'])
    rows = rows_of(c.get('/api/export.csv?games=arknights&dq=stale'))
    check("质量筛选可与游戏筛选组合", [x[1] for x in rows[1:]], ['老活动·结束未知'])
    rows = rows_of(c.get('/api/export.csv?dq=bogus'))
    check("非法 dq 忽略(按全量导出)", len(rows) - 1, 5)

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
