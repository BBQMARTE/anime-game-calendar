# -*- coding: utf-8 -*-
"""「更早开始·结束未知 / 真正进行中」双端口径一致性测试。

前端(static/index.html 的 isStaleUnknown / isOngoingEvent)与服务端(app.py 的
_is_stale_unknown / _is_ongoing)分别驱动列表折叠、订阅过滤与 /api/health 统计。
任何一端改了阈值或比较粒度,都会出现「页面折叠了但订阅还在推」「监控说进行中
页面说历史」这类分叉,所以用同一组夹具逐条比对布尔结果。

重点覆盖日期级 vs 时刻级的历史 bug:30 天前 20:00 开始的条目,按日期比较
(旧的 Python 实现)不算 stale,按时刻比较(前端)已经算 stale。

运行:python tests/test_stale_parity.py(node 缺失则 SKIP 并退出码 0)
"""
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, 'static', 'index.html')

NOW = datetime(2026, 10, 31, 12, 0, 0)
D = lambda days, hh=10, mm=0: (NOW + timedelta(days=days)).replace(
    hour=hh, minute=mm, second=0, microsecond=0).strftime('%Y-%m-%dT%H:%M')
F = lambda days, hh=10, mm=0: (NOW + timedelta(days=days)).replace(
    hour=hh, minute=mm, second=0, microsecond=0).strftime('%Y-%m-%d')

CASES = [
    # 30 天边界:同刻不算,早 2 小时算(时刻级口径的关键差异)
    {'id': 'edge30_same', 'start': D(-30, 12, 0), 'end': None},
    {'id': 'edge30_early', 'start': D(-30, 10, 0), 'end': None},
    {'id': 'edge30_late', 'start': D(-30, 20, 0), 'end': None},
    # 老条目 / 近期无结束 / 今天开始无结束
    {'id': 'old_noend', 'start': F(-40), 'end': None},
    {'id': 'recent_noend', 'start': D(-5), 'end': None},
    {'id': 'today_noend', 'start': D(0), 'end': None},
    # 有结束时间:已结束 / 进行中 / 未来 / 结束时间正好是此刻
    {'id': 'done', 'start': D(-9), 'end': D(-1, 23, 59)},
    {'id': 'live', 'start': D(-2), 'end': D(1, 23, 59)},
    {'id': 'future', 'start': D(3), 'end': D(9)},
    {'id': 'end_now', 'start': D(-1), 'end': NOW.strftime('%Y-%m-%dT%H:%M')},
    # 开始时间正好是此刻
    {'id': 'start_now', 'start': NOW.strftime('%Y-%m-%dT%H:%M'), 'end': None},
    # 无开始时间
    {'id': 'no_start', 'start': None, 'end': None},
]

LOADER = r"""
const fs = require('fs');
const src = (fs.readFileSync(0, 'utf8').match(/<script>[\s\S]*?<\/script>/g) || [])
  .map(b => b.replace(/<\/?script>/g, '')).join('\n');
function grab(name) {
  const i = src.indexOf('function ' + name + '(');
  if (i < 0) throw new Error('not found: ' + name);
  let d = 0, go = false;
  for (let k = src.indexOf('{', i); k < src.length; k++) {
    if (src[k] === '{') { d++; go = true; }
    else if (src[k] === '}') { d--; if (go && !d) return src.slice(i, k + 1); }
  }
  throw new Error('unbalanced: ' + name);
}
const CASES = __CASES__;
const NOW = new Date(2026, 9, 31, 12, 0, 0);
const fn = new Function('evStart', 'evEnd', 'now',
  grab('isPointItem') + '\n' + grab('isStaleUnknown') + '\n' + grab('isOngoingEvent') +
  '\nreturn {stale: isStaleUnknown, ongoing: isOngoingEvent};');
const fns = fn(e => (e.start ? new Date(e.start) : null),
  e => (e.end ? new Date(e.end) : (e.start ? new Date(new Date(e.start).getFullYear(),
    new Date(e.start).getMonth(), new Date(e.start).getDate() + 2,
    new Date(e.start).getHours(), new Date(e.start).getMinutes(), 0) : null)), NOW);
const out = CASES.map(c => ({id: c.id,
  stale: !!fns.stale(c, NOW), ongoing: !!fns.ongoing(c, NOW)}));
console.log(JSON.stringify(out));
"""

bad = 0


def check(label, got, expect):
    global bad
    ok = got == expect
    if not ok:
        bad += 1
    print("[%s] %s: got=%r expect=%r" % ('OK ' if ok else 'FAIL', label, got, expect))


def main():
    node = shutil.which('node')
    if not node:
        print('SKIP: 未找到 node,跳过双端口径测试')
        return 0
    loader = LOADER.replace('__CASES__', json.dumps(CASES, ensure_ascii=False))
    r = subprocess.run([node, '-e', loader], input=open(HTML, encoding='utf-8').read(),
                       capture_output=True, text=True, encoding='utf-8', timeout=60)
    if r.returncode != 0:
        print('FAIL: node 执行失败\n' + r.stderr[:600])
        return 1
    js = {x['id']: (x['stale'], x['ongoing']) for x in json.loads(r.stdout.strip().splitlines()[-1])}

    for c in CASES:
        py = (app._is_stale_unknown(c, NOW), app._is_ongoing(c, NOW))
        check(c['id'], js.get(c['id']), py)

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
