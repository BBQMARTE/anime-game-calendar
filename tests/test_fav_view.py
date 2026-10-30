# -*- coding: utf-8 -*-
"""「收藏」页签排序与过滤测试。

收藏此前只能在各个列表里置顶,没有独立入口;新增「收藏」页签后,
排序口径为:进行中(先结束的在前) → 即将开始(最近的在前) → 已结束/时间未知。

运行:python3 tests/test_fav_view.py(node 缺失则 SKIP)
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
const fn = new Function('evStart', 'evEnd', 'isFav', grab('favEvents') + '\nreturn favEvents;');
const arr = fn(e => new Date(e.start), e => (e.end ? new Date(e.end) : null), e => FAV.has(e.id))(EVENTS, new Date('2026-10-31T12:00:00+08:00'));
console.log(JSON.stringify({ ids: arr.map(e => e.id) }));
"""

EV = [
    {'id': 'a', 'start': '2026-10-30T12:00', 'end': '2026-11-03T12:00'},
    {'id': 'b', 'start': '2026-10-28T12:00', 'end': '2026-11-01T12:00'},
    {'id': 'c', 'start': '2026-11-02T12:00', 'end': '2026-11-09T12:00'},
    {'id': 'd', 'start': '2026-10-01T12:00', 'end': '2026-10-20T12:00'},
    {'id': 'e', 'start': '2026-10-05T12:00'},
    {'id': 'f', 'start': '2026-10-31T12:00', 'end': '2026-11-05T12:00'},
]
FAV = ['a', 'b', 'c', 'd', 'e']

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
        print('SKIP: 未找到 node,跳过收藏视图测试')
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
    check('只列出收藏条目', 'f' in got['ids'], False)
    check('排序:进行中(先结束)→ 即将开始 → 已结束 → 时间未知',
          got['ids'], ['b', 'a', 'e', 'c', 'd'])
    check('页签按钮存在', 'data-tab="fav"' in html, True)

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
