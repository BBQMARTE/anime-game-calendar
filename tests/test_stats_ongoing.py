# -*- coding: utf-8 -*-
"""前端统计口径测试:「进行中」不再把更早开始·结束未知的条目算进去。

列表里无结束且开始超过 30 天的条目放在「更早开始·结束未知」(默认折叠),
统计页此前却把这类老条目也算作「进行中」。现在两端共用 isStaleUnknown /
isOngoingEvent,口径与列表、ICS 一致。

运行:python tests/test_stats_ongoing.py(node 缺失则 SKIP)
"""
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, 'static', 'index.html')
bad = 0


def check(label, got, expect):
    global bad
    ok = got == expect
    if not ok:
        bad += 1
    print("[%s] %s: got=%r expect=%r" % ('OK ' if ok else 'FAIL', label, got, expect))


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
const evStart = e => (e.start ? new Date(e.start) : null);
const evEnd = e => (e.end ? new Date(e.end) : null);
const fn = new Function('evStart', 'evEnd',
  grab('isStaleUnknown') + '\n' + grab('isOngoingEvent')
  + '\nreturn {isStaleUnknown, isOngoingEvent};');
const f = fn(evStart, evEnd);
const now = new Date('2026-10-31T12:00:00');
const cases = [
  {id:'recent_noend', start:'2026-10-28T10:00', end:null},
  {id:'old_noend',    start:'2026-08-28T10:00', end:null},
  {id:'running',      start:'2026-10-30T10:00', end:'2026-11-02T23:59'},
  {id:'ended',        start:'2026-10-30T10:00', end:'2026-10-30T23:59'},
  {id:'future',       start:'2026-11-02T10:00', end:null},
  {id:'cut_edge',     start:'2026-09-30T10:00', end:null},
];
console.log(JSON.stringify(cases.map(e => ({
  id: e.id,
  ongoing: f.isOngoingEvent(e, now),
  stale: f.isStaleUnknown(e, now),
}))));
"""


def main():
    global bad
    node = shutil.which('node')
    if not node:
        print('SKIP: 未找到 node')
        return 0
    r = subprocess.run([node, '-e', LOADER], input=open(HTML, encoding='utf-8').read(),
                       capture_output=True, text=True, encoding='utf-8', timeout=60)
    if r.returncode != 0:
        print('FAIL: JS 执行失败\n' + r.stderr[:600])
        return 1
    d = {x['id']: x for x in json.loads(r.stdout.strip().splitlines()[-1])}
    check('近期无结束条目算进行中', d['recent_noend']['ongoing'], True)
    check('近期无结束条目不算更早未知', d['recent_noend']['stale'], False)
    check('老的无结束条目不冒充进行中', d['old_noend']['ongoing'], False)
    check('老的无结束条目归入更早未知', d['old_noend']['stale'], True)
    check('有结束且在区间内 → 进行中', d['running']['ongoing'], True)
    check('已结束 → 不算进行中', d['ended']['ongoing'], False)
    check('未来 → 不算进行中', d['future']['ongoing'], False)
    check('恰好 31 天前 → 更早未知', d['cut_edge']['stale'], True)
    check('恰好 31 天前 → 不算进行中', d['cut_edge']['ongoing'], False)

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
