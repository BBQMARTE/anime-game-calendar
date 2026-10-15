# -*- coding: utf-8 -*-
"""序列化精度双端一致性守门（覆盖 Issue #26）。

背景：`static/scraper.js::iso()` 曾把秒位硬编码成 `:00`，而 Python 端
`datetime.isoformat()` 如实带秒（区间末端无时分时为 `23:59:59`）—— 同一结束时刻
两端序列化成不同字符串（恒差 59 秒），倒计时/进度条/落格判定与两端缓存随之分叉。

修法已随 Issue #9 返工（`5f309cb`）落地，但当时 `tests/` 的序列化用例
（`test_parity.py` 的 dates / windows 两组）输入全是整点日期，秒位恒为 `00`：
**把 `iso()` 改回硬编码 `:00` 仍能全绿**（本文件即为此补的守门，见 Issue #26 验收 2/5）。

运行：python3 tests/test_iso_seconds.py
      （需要 node；node 缺失则 SKIP 并退出码 0，与 test_dual_side 同模式）
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime

import timeparse as tp

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRAPERS = [os.path.join(ROOT, 'static', 'scraper.js'),
            os.path.join(ROOT, 'android', 'app', 'src', 'main', 'assets', 'www', 'scraper.js')]
REF = datetime(2026, 8, 3, 12, 0, 0)

# 双端同批输入 → (名称, start, end) 必须逐字段相同（Issue #26 验收 2）。
# 前两条对应「无时分末端补 23:59:59」与「显式时分照原样」；第三条为「输入带秒」的口径对照
# （两端都截到整分，属既有口径，见 Issue #26 评论）。
CASES = [
    ('【盛夏嘉年华】活动时间：2026年7月10日 ~ 2026年8月10日',
     '盛夏嘉年华', '2026-07-10T00:00:00', '2026-08-10T23:59:59'),
    ('【盛夏嘉年华】活动时间：2026年7月10日 12:00 ~ 2026年8月10日 12:00',
     '盛夏嘉年华', '2026-07-10T12:00:00', '2026-08-10T12:00:00'),
    ('【盛夏嘉年华】活动时间：2026年7月10日 12:00:30 ~ 2026年8月10日 12:00:45',
     '盛夏嘉年华', '2026-07-10T12:00:00', '2026-08-10T12:00:00'),
    ('「星轨航程」活动期间：2026年7月10日 ~ 2026年7月20日',
     '星轨航程', '2026-07-10T00:00:00', '2026-07-20T23:59:59'),
    ('「星轨航程」活动期间：2026年12月31日 23:00 ~ 2027年1月5日 00:00',
     '星轨航程', '2026-12-31T23:00:00', '2027-01-05T00:00:00'),
]

# 序列化精度：这些时刻的秒位不能再被截成 00（年份补 4 位属 Issue #9）
STAMPS = ['2026-08-10T23:59:59', '2026-08-10T12:00:30', '0026-09-10T23:59:59',
          '9999-12-31T23:59:59', '2026-01-01T00:00:01']

NODE_LOADER = r"""
const fs = require('fs');
let src = fs.readFileSync(process.argv[2], 'utf8');
const anchor = 'return { GAMES, fetchAll,';
if (!src.includes(anchor)) throw new Error('scraper.js 导出锚点未找到: ' + anchor);
src = src.replace(anchor, 'return { extractEvents, iso, GAMES, fetchAll,');
const S = new Function(src + '\nreturn Scraper;')();
const inp = JSON.parse(process.argv[3]);
const ref = new Date(2026, 7, 3, 12, 0, 0);
process.stdout.write(JSON.stringify({
  events: inp.cases.map((t) => S.extractEvents(t, ref).map(([n, s, e]) => [n, S.iso(s), S.iso(e)])),
  stamps: inp.stamps.map((s) => S.iso(new Date(s))),
}));
"""

bad = 0


def check(label, got, expect):
    global bad
    ok = got == expect
    bad += 0 if ok else 1
    print("[%s] %s: got=%r expect=%r" % ('OK ' if ok else 'FAIL', label, got, expect))


def py_events():
    out = []
    for text, _, _, _ in CASES:
        out.append([[n, s.isoformat() if s else None, e.isoformat() if e else None]
                    for n, s, e in tp.extract_events(text, REF)])
    return out


def main():
    global bad

    # ---- 1. 源码守门：iso() 不得硬编码秒位（android 镜像逐字节同步） ----
    h = [hashlib.md5(open(f, 'rb').read()).hexdigest() for f in SCRAPERS]
    if len(set(h)) != 1:
        bad += 1
        print('MISMATCH 两份 scraper.js md5 不一致: %s' % dict(zip(SCRAPERS, h)))
    else:
        print('scraper.js ×2 md5 一致: %s' % h[0])
    for f in SCRAPERS:
        src = open(f, encoding='utf-8').read()
        m = re.search(r'const iso = d =>[^\n]*', src)
        line = m.group(0) if m else ''
        check('%s::iso 出参用 getSeconds()' % os.path.basename(os.path.dirname(f)),
              'getSeconds()' in line, True)
        check('%s::iso 无硬编码秒位 :00`' % os.path.basename(os.path.dirname(f)),
              bool(re.search(r":00\s*`", line)), False)

    if not shutil.which('node'):
        print('SKIP: 未找到 node，跳过双端一致性比对')
        print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
        return 1 if bad else 0

    # ---- 2. 双端 extract_events 逐字段相同，且秒位符合预期 ----
    mine = py_events()
    for i, (text, name, exp_s, exp_e) in enumerate(CASES):
        check('py 序列化 %s' % text[:20], mine[i], [[name, exp_s, exp_e]])
    inp = {'cases': [c[0] for c in CASES], 'stamps': STAMPS}
    for script in SCRAPERS:
        p = subprocess.run(['node', '-e', NODE_LOADER, 'node', script,
                            json.dumps(inp, ensure_ascii=False)], capture_output=True, text=True)
        if p.returncode != 0:
            bad += 1
            print('MISMATCH js 侧无法加载 %s: %s' % (os.path.basename(script),
                                                     (p.stderr.strip().splitlines() or [''])[-1]))
            continue
        js = json.loads(p.stdout.strip(), strict=False)
        if js['events'] != mine:
            bad += 1
            print('MISMATCH extract_events 双端不一致\n  py = %s\n  js = %s' % (mine, js['events']))
        else:
            print('extract_events 双端 %d 条逐字段一致' % len(CASES))
        for s, got in zip(STAMPS, js['stamps']):
            check('js::iso(%s)' % s, got, datetime.fromisoformat(s).isoformat(timespec='seconds'))

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
