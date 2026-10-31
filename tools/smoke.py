# -*- coding: utf-8 -*-
"""发版后的端到端冒烟检查(需要本地服务在线)。

覆盖最近几版最容易回归的链路:
  1) /api/health 关键字段与数据源 last_ok
  2) 数据质量筛选导出条数 == health 的 missing_end / missing_images / stale_unknown
  3) /api/calendar.ics 的 ETag 304、收藏订阅
  4) 首页是否包含当前版本的前端入口(状态同步码 / 我的反馈+撤回 / 质量筛选条 / 统计快捷筛选)
  5) static 与 android assets 的 index.html / sw.js 是否逐字节一致,SW 版本号是否一致

用法:
    py tools/smoke.py                  # 默认 http://127.0.0.1:5000
    py tools/smoke.py http://<host>:5000
"""
import csv
import hashlib
import io
import json
import os
import re
import sys

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = (sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:5000').rstrip('/')
bad = 0


def check(label, got, expect):
    global bad
    ok = got == expect
    if not ok:
        bad += 1
    print('[%s] %s: got=%r expect=%r' % ('OK ' if ok else 'FAIL', label, got, expect))


def md5(path):
    with open(path, 'rb') as f:
        return hashlib.md5(f.read()).hexdigest()


def csv_rows(resp):
    text = resp.content.decode('utf-8-sig')
    return len(list(csv.reader(io.StringIO(text)))) - 1


def main():
    try:
        h = requests.get(BASE + '/api/health', timeout=10).json()
    except Exception as e:  # noqa: BLE001
        print('FAIL: 服务不可达 %s (%s)' % (BASE, e))
        return 1

    for k in ('updated', 'events', 'events_real', 'missing_end', 'missing_images',
              'stale_unknown', 'sources', 'last_error'):
        check('health 含字段 %s' % k, k in h, True)
    check('health 数据源带 last_ok',
          all('last_ok' in v for v in (h.get('sources') or {}).values()), True)

    for dq, key in (('noend', 'missing_end'), ('noimg', 'missing_images'),
                    ('stale', 'stale_unknown')):
        r = requests.get(BASE + '/api/export.csv?dq=' + dq, timeout=15)
        check('?dq=%s 导出 200' % dq, r.status_code, 200)
        check('?dq=%s 行数 == health.%s' % (dq, key), csv_rows(r), h.get(key))

    rc = requests.get(BASE + '/api/export.csv', timeout=15)
    header = rc.content.decode('utf-8-sig').splitlines()[0]
    check('CSV 表头含收藏/已做完列', ('收藏' in header and '已做完' in header), True)

    # ?q=:导出要跟列表搜索同口径,命中数必须真的少于全量,且每条都含关键词
    rq = requests.get(BASE + '/api/export.csv?q=%E6%B4%BB%E5%8A%A8', timeout=15)   # q=活动
    check('?q=活动 导出 200', rq.status_code, 200)
    check('?q=活动 条数少于全量', csv_rows(rq) < csv_rows(rc), True)
    qrows = list(csv.reader(io.StringIO(rq.content.decode('utf-8-sig'))))
    check('?q=活动 每条都命中检索串',
          all('活动' in (x[0] + x[1] + x[2]) for x in qrows[1:]) if len(qrows) > 1 else False, True)

    r1 = requests.get(BASE + '/api/calendar.ics', timeout=15)
    check('ICS 200', r1.status_code, 200)
    check('ICS 含日历头', b'BEGIN:VCALENDAR' in r1.content, True)
    body = r1.content.decode('utf-8', 'replace')
    check('ICS 每条事件带 CATEGORIES',
          body.count('CATEGORIES:'), body.count('BEGIN:VEVENT'))
    etag = r1.headers.get('ETag') or ''
    check('ICS 带 ETag', bool(etag), True)
    r2 = requests.get(BASE + '/api/calendar.ics', headers={'If-None-Match': etag}, timeout=15)
    check('ICS 条件请求 304', r2.status_code, 304)
    rf = requests.get(BASE + '/api/calendar.ics?fav=1', timeout=15)
    check('收藏订阅 200', rf.status_code, 200)
    check('收藏订阅 ETag 带 fav 标记', '-fav-' in (rf.headers.get('ETag') or ''), True)

    page = requests.get(BASE + '/', timeout=15).text
    for marker in ('状态同步码', 'openReports()', 'withdrawReport(', 'dq-bar', "statRange('本周开始'",
                   "todayJump('今天开始')", 'hlText(e.title)', 'markReported(overlay,e)',
                   'dayParam(selDay)', 'srcInfo(this)', 'exportSearch().quick'):
        check('首页含 %s' % marker, marker in page, True)

    pairs = [('static/index.html', 'android/app/src/main/assets/www/index.html'),
             ('static/sw.js', 'android/app/src/main/assets/www/sw.js'),
             ('static/manifest.webmanifest',
              'android/app/src/main/assets/www/manifest.webmanifest')]
    for a, b in pairs:
        check('%s 双端一致' % os.path.basename(a),
              md5(os.path.join(ROOT, a)), md5(os.path.join(ROOT, b)))
    sv = re.search(r"const CACHE = '([^']+)'", open(os.path.join(ROOT, 'static/sw.js'),
                                                   encoding='utf-8').read())
    av = re.search(r"const CACHE = '([^']+)'",
                   open(os.path.join(ROOT, 'android/app/src/main/assets/www/sw.js'),
                        encoding='utf-8').read())
    check('SW 版本一致', sv and av and sv.group(1), av and av.group(1))

    man = json.load(open(os.path.join(ROOT, 'static/manifest.webmanifest'), encoding='utf-8'))
    check('manifest 快捷方式数量', len(man.get('shortcuts') or []), 2)

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
