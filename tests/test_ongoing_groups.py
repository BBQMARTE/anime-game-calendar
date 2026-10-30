# -*- coding: utf-8 -*-
"""「进行中」分组测试:有结束时间 vs 结束时间未知。

来源只给开始时间、没给结束时间的条目,不该和「已知截止」的活动混在同一组里——
前者无法算倒计时,后者可以。renderList 通过 ongoingGroups() 拆成两组。

运行:python3 tests/test_ongoing_groups.py(node 缺失则 SKIP)
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
const EVENTS = __EVENTS__;
const FAV = new Set(__FAV__);
const fn = new Function('evStart', 'evEnd', 'isFav', grab('ongoingGroups') + '\nreturn ongoingGroups;');
const g = fn(e => new Date(e.start), e => (e.end ? new Date(e.end) : null), e => FAV.has(e.id))(EVENTS, new Date('2026-10-31T12:00:00+08:00'));
console.log(JSON.stringify({ live: g.live.map(e => e.id), unknown: g.unknown.map(e => e.id) }));
"""

EV = [
    {'id': 'a', 'start': '2026-10-30T12:00', 'end': '2026-11-05T12:00'},  # 进行中,5 天后结束
    {'id': 'b', 'start': '2026-10-10T12:00', 'end': '2026-10-28T12:00'},  # 已结束
    {'id': 'c', 'start': '2026-11-01T12:00', 'end': '2026-11-10T12:00'},  # 尚未开始
    {'id': 'd', 'start': '2026-10-01T12:00'},                             # 开始 30 天,结束未知
    {'id': 'e', 'start': '2026-10-28T12:00'},                             # 开始 3 天,结束未知
    {'id': 'f', 'start': '2026-10-25T12:00', 'end': '2026-11-01T12:00'},  # 进行中且收藏
]
FAV = ['f']

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
        print('SKIP: 未找到 node,跳过进行中分组测试')
        return 0
    html = open(HTML, encoding='utf-8').read()
    loader = (LOADER.replace('__EVENTS__', json.dumps(EV, ensure_ascii=False))
              .replace('__FAV__', json.dumps(FAV, ensure_ascii=False)))
    r = subprocess.run([node, '-e', loader], input=html, capture_output=True,
                       text=True, encoding='utf-8', timeout=60)
    if r.returncode != 0:
        print('FAIL: node 执行失败\n' + r.stderr[:600])
        return 1
    got = json.loads(r.stdout.strip().splitlines()[-1])
    check('进行中只含真实未结束的活动(收藏置顶,按结束时间升序)',
          got['live'], ['f', 'a'])
    check('结束未知组按开始时间倒序(最近的在前)', got['unknown'], ['e', 'd'])
    check('已结束/未开始都不出现在任何组',
          ('b' in got['live']) or ('b' in got['unknown']) or ('c' in got['live']) or ('c' in got['unknown']),
          False)

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
