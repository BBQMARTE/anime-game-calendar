# -*- coding: utf-8 -*-
"""「导出整月 .ics」测试。

设置「数据」里新增整月导出:当前浏览的月份(没开过日历则用本月),
复用周导出的区间口径(开始日落在本月;跨月活动有明确结束时间且仍覆盖本月也保留)。

运行:python tests/test_month_ics.py(node 缺失则 SKIP)
"""
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, 'static', 'index.html')

LOADER = r"""
const fs = require('fs');
const src = fs.readFileSync(0, 'utf8');
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
const code = ['evStart','evEnd','monthRange','weekEvents'].map(grab).join('\n');
const api = new Function(code + '\nreturn {monthRange,weekEvents};')();
const r = api.monthRange(2026, 10);   // 2026-11
const fmt = d => d.getFullYear() + '-' + (d.getMonth() + 1) + '-' + d.getDate();
const evs = [
  {id:'first', start:'2026-11-01T10:00'},
  {id:'last', start:'2026-11-30T10:00'},
  {id:'next_month', start:'2026-12-01T00:00'},
  {id:'cross', start:'2026-10-28T10:00', end:'2026-11-02T03:59'},
  {id:'prev_noend', start:'2026-10-28T10:00'},
  {id:'ends_at_boundary', start:'2026-11-30T20:00', end:'2026-12-01T00:00'},
];
const ids = api.weekEvents(evs, r).map(e => e.id);
const empty = api.weekEvents(evs, api.monthRange(2027, 0));
console.log(JSON.stringify({
  start: fmt(r.start),
  end: fmt(r.end),
  ids,
  emptyCount: empty.length,
  hasEntry: src.includes('onclick="exportMonthIcs()"'),
  hasLabel: src.includes('导出整月 .ics'),
  hasFn: src.includes('function exportMonthIcs(') && src.includes('function monthRange('),
}));
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
        print('SKIP: 未找到 node')
        return 0
    r = subprocess.run([node, '-e', LOADER], input=open(HTML, encoding='utf-8').read(),
                       capture_output=True, text=True, encoding='utf-8', timeout=60)
    if r.returncode != 0:
        print('FAIL: node 执行失败\n' + r.stderr[:800])
        return 1
    d = json.loads(r.stdout.strip().splitlines()[-1])

    check('月范围 1 日到下月 1 日', (d['start'], d['end']), ('2026-11-1', '2026-12-1'))
    check('整月活动:本月开始 + 跨月有结束时间',
          d['ids'], ['first', 'last', 'cross', 'ends_at_boundary'])
    check('下月 1 日的活动不算本月', 'next_month' in d['ids'], False)
    check('上月开始的无结束条目不混入', 'prev_noend' in d['ids'], False)
    check('其它月没有活动时返回空', d['emptyCount'], 0)
    check('设置里「数据」有整月导出入口', d['hasEntry'], True)
    check('入口文案为「导出整月 .ics」', d['hasLabel'], True)
    check('exportMonthIcs / monthRange 已实现', d['hasFn'], True)

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
