# -*- coding: utf-8 -*-
"""资讯时效测试:超过 60 天的旧公告不再进「全部资讯」。

抓取源(尤其鸣潮官网文章列表)会把几百天前的旧公告一起带回来,
「全部资讯」越滚越长。现在服务端 app._drop_expired 与 APK 端 scraper.js::isFreshInfo
同口径:非人工录入的 info 超过 60 天即丢弃;人工录入条目不受限。

运行:python3 tests/test_info_freshness.py(node 缺失则跳过 JS 比对)
"""
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
bad = 0
NOW = datetime(2026, 10, 31, 12, 0)


def check(label, got, expect):
    global bad
    ok = got == expect
    if not ok:
        bad += 1
    print("[%s] %s: got=%r expect=%r" % ('OK ' if ok else 'FAIL', label, got, expect))


def iso(days_ago, kind='info', src=None, **kw):
    e = {'id': f'{kind}-{days_ago}-{src}', 'kind': kind,
         'date': (NOW - timedelta(days=days_ago)).isoformat(), 'title': 'T'}
    if src:
        e['src'] = src
    e.update(kw)
    return e


def main():
    global bad
    rows = [
        iso(400, src='wuwa'),                         # 旧自动资讯 → 丢
        iso(61, src='zzz'),                           # 超过 60 天 → 丢
        iso(60, src='wuwa'),                          # 恰好 60 天 → 留
        iso(3, src='wuwa'),                           # 近期资讯 → 留
        iso(400, src='manual'),                       # 人工录入不受限 → 留
        iso(10, src=None, date=None),                 # 无发布日期 → 留
        {'id': 'ev-old', 'kind': 'event', 'start': '2026-09-01T12:00',
         'end': '2026-09-10T12:00', 'title': '旧活动'},   # 已结束 → 丢
        {'id': 'ev-live', 'kind': 'event', 'start': '2026-10-20T12:00',
         'end': '2026-11-10T12:00', 'title': '进行中'},   # 未结束 → 留
        {'id': 'ev-noend', 'kind': 'event', 'start': '2026-08-01T12:00',
         'title': '无结束时间'},                          # 真活动规则不变 → 留
    ]
    kept = app._drop_expired(rows, now=NOW)
    ids = {e['id'] for e in kept}
    check('旧自动资讯被丢弃', 'info-400-wuwa' in ids, False)
    check('61 天资讯被丢弃', 'info-61-zzz' in ids, False)
    check('恰好 60 天保留', 'info-60-wuwa' in ids, True)
    check('近期资讯保留', 'info-3-wuwa' in ids, True)
    check('人工录入旧资讯保留', 'info-400-manual' in ids, True)
    check('无日期的资讯保留', 'info-10-None' in ids, True)
    check('已结束活动仍被丢弃', 'ev-old' in ids, False)
    check('进行中活动保留', 'ev-live' in ids, True)
    check('无结束时间活动保留', 'ev-noend' in ids, True)

    node = shutil.which('node')
    if not node:
        print('SKIP: 未找到 node,跳过 JS 双端比对')
    else:
        js = os.path.join(ROOT, 'static', 'scraper.js')
        script = (
            "const fs=require('fs');"
            "const src=fs.readFileSync(%s,'utf8');"
            "const S=new Function(src+'\\nreturn Scraper;')();"
            "const now=new Date('2026-10-31T12:00:00');"
            "const mk=(kind,days,src)=>({kind,src,title:'T',date:new Date(now.getTime()-days*864e5).toISOString()});"
            "console.log(JSON.stringify(["
            "S.isFreshInfo(mk('info',400,'wuwa'),now),"
            "S.isFreshInfo(mk('info',61,'zzz'),now),"
            "S.isFreshInfo(mk('info',60,'wuwa'),now),"
            "S.isFreshInfo(mk('info',400,'manual'),now),"
            "S.isFreshInfo({kind:'info',title:'T'},now),"
            "S.isFreshInfo({kind:'event',title:'T'},now)]));"
            % __import__('json').dumps(js))
        r = subprocess.run([node, '-e', script], capture_output=True, text=True,
                           encoding='utf-8', timeout=60)
        if r.returncode != 0:
            print('FAIL: JS 执行失败\n' + r.stderr[:600])
            bad += 1
        else:
            check('JS isFreshInfo 与 Python 口径一致',
                  __import__('json').loads(r.stdout.strip().splitlines()[-1]),
                  [False, False, True, True, True, True])

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
