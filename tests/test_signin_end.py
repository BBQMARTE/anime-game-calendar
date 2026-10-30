# -*- coding: utf-8 -*-
"""签到（N日）结束时间推断测试。

标题里的「（7日）」「七日签到」本身就是活动时长。此前这类条目只解析到开始时间,
被补成 2 天默认窗口(与真实 7 天不符),前端还显示「剩 2 天」。
现在 scrapers._ev / app._manual_events / scraper.js ev()/manualEvents() 统一按 N 天补真实结束。

运行:python3 tests/test_signin_end.py(node 缺失则跳过 JS 比对)
"""
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scrapers  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
bad = 0


def check(label, got, expect):
    global bad
    ok = got == expect
    if not ok:
        bad += 1
    print("[%s] %s: got=%r expect=%r" % ('OK ' if ok else 'FAIL', label, got, expect))


def main():
    global bad
    # ---- Python 天数识别 ----
    check('（7日）→ 7', scrapers._signin_days('星河共我签到（7日）'), 7)
    check('七日签到 → 7', scrapers._signin_days('环期赠礼（1.4版本七日签到）'), 7)
    check('(3日) 半角括号 → 3', scrapers._signin_days('累计签到(3日)'), 3)
    check('无「签到」字样 → 0', scrapers._signin_days('版本活动（7日）'), 0)
    check('天数越界(45日) → 0', scrapers._signin_days('签到（45日）'), 0)
    check('单日不当作时长 → 0', scrapers._signin_days('签到（1日）'), 0)
    check('空标题 → 0', scrapers._signin_days(''), 0)

    # ---- _ev:签到条目按天数补结束,其它条目仍走 2 天默认窗口 ----
    start = datetime(2026, 11, 5, 12, 0)
    e = scrapers._ev('endfield', '明日方舟：终末地', '星河共我签到（7日）', '签到',
                     start, start, None, 'https://example.com/x')
    check('_ev 签到（7日）结束 = 开始 + 7 天',
          e['end'], (start + timedelta(days=7)).isoformat())
    check('_ev 签到分类保持不变', e['category'], '签到')
    e2 = scrapers._ev('endfield', '明日方舟：终末地', '普通活动', '活动',
                      start, start, None, 'https://example.com/y')
    check('_ev 普通活动仍补 2 天窗口',
          e2['end'], (start + timedelta(days=2)).isoformat())
    # 已有结束时间的签到条目不被覆盖
    e3 = scrapers._ev('endfield', '明日方舟：终末地', '星河共我签到（7日）', '签到',
                      start, start, start + timedelta(days=5), 'https://example.com/z')
    check('_ev 已有结束时不被推开', e3['end'], (start + timedelta(days=5)).isoformat())

    # ---- JS 端同口径 ----
    node = shutil.which('node')
    if not node:
        print('SKIP: 未找到 node,跳过 JS 双端比对')
    else:
        js_path = os.path.join(ROOT, 'static', 'scraper.js')
        cases = [['星河共我签到（7日）'], ['环期赠礼（1.4版本七日签到）'],
                 ['累计签到(3日)'], ['版本活动（7日）'], ['签到（45日）'], ['签到（1日）'], ['']]
        script = (
            "const fs=require('fs');"
            "const src=fs.readFileSync(%s,'utf8');"
            "globalThis.localStorage={getItem:k=>k==='ycal_manual'?%s:'[]'};"
            "const S=new Function(src+'\\nreturn Scraper;')();"
            "const cases=%s.map(a=>S.signinDays(a[0]));"
            "const m=S.manualEvents();"
            "console.log(JSON.stringify({cases, manual:m}));"
            % (json.dumps(js_path),
               json.dumps(json.dumps([{'title': '星河共我签到（7日）', 'game_id': 'endfield',
                                       'start': '2026-11-05T12:00', 'category': '签到'}]),
                          ensure_ascii=False),
               json.dumps(cases, ensure_ascii=False)))
        r = subprocess.run([node, '-e', script], capture_output=True, text=True,
                           encoding='utf-8', timeout=60)
        if r.returncode != 0:
            print('FAIL: JS 执行失败\n' + r.stderr[:600])
            bad += 1
        else:
            got = json.loads(r.stdout.strip().splitlines()[-1])
            check('JS signinDays 与 Python 一致',
                  got['cases'], [scrapers._signin_days(c[0]) for c in cases])
            check('JS manualEvents 补出 7 天结束',
                  got['manual'][0]['end'], '2026-11-12T12:00:00')

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
