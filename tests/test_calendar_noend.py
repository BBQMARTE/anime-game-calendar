# -*- coding: utf-8 -*-
"""月历「结束未知」条目口径测试。

无结束时间的活动此前在月历里按「开始 + 2 天」默认窗口显示三天(当天开始 / 中途进行中 / 当天结束),
和列表里「结束未知」的新口径不一致,也等于在月历上伪造了一个结束日。
现在:无结束时间只出现在开始当天(算「当天开始」),有结束时间的条目跨天逻辑不变。

运行:python3 tests/test_calendar_noend.py(node 缺失则 SKIP)
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
const fn = new Function('filteredEvents', 'calVisible', 'evStart', 'evEnd',
  grab('eventsOnDay') + '\nreturn eventsOnDay;');
const call = fn(() => EVENTS, () => true,
  e => new Date(e.start), e => (e.end ? new Date(e.end) : null));
const dump = r => ({ starts: r.starts.map(e => e.id), runs: r.runs.map(e => e.id), ends: r.ends.map(e => e.id) });
console.log(JSON.stringify({
  d1031: dump(call(2026, 9, 31)),
  d1101: dump(call(2026, 10, 1)),
  d1102: dump(call(2026, 10, 2)),
  d1103: dump(call(2026, 10, 3)),
}));
"""

EV = [
    # 10/31 开始,没有结束时间
    {'id': 'noend', 'start': '2026-10-31T09:00', 'end': None},
    # 10/31 开始,11/01 23:59 结束(跨天)
    {'id': 'range', 'start': '2026-10-31T12:00', 'end': '2026-11-01T23:59'},
]

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
        print('SKIP: 未找到 node,跳过月历口径测试')
        return 0
    loader = LOADER.replace('__EVENTS__', json.dumps(EV, ensure_ascii=False))
    r = subprocess.run([node, '-e', loader], input=open(HTML, encoding='utf-8').read(),
                       capture_output=True, text=True, encoding='utf-8', timeout=60)
    if r.returncode != 0:
        print('FAIL: node 执行失败\n' + r.stderr[:600])
        return 1
    d = json.loads(r.stdout.strip().splitlines()[-1])
    check('开始时:两条都算「当天开始」', d['d1031']['starts'], ['noend', 'range'])
    check('次日:无结束条目不再显示为「进行中」', d['d1101']['runs'], [])
    check('次日:有结束条目按「当天结束」', d['d1101']['ends'], ['range'])
    check('第 3 天:无结束条目不再伪造结束', d['d1102'], {'starts': [], 'runs': [], 'ends': []})
    check('第 4 天同样为空', d['d1103'], {'starts': [], 'runs': [], 'ends': []})

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
