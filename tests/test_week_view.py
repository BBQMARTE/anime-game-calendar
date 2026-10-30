# -*- coding: utf-8 -*-
"""周视图格内活动名测试。

月视图格内只有圆点;周视图格高 74px,可再放最多 2 条活动名,方便扫一眼本周安排。
weekMiniNames() 负责去重并截断,渲染处只在 calWeek 时使用。

运行:python3 tests/test_week_view.py(node 缺失则 SKIP)
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
const fn = new Function(grab('weekMiniNames') + '\nreturn weekMiniNames;')();
const cases = __CASES__;
console.log(JSON.stringify(cases.map(c => fn(c))));
"""

CASES = [
    {'starts': [{'id': 'a', 'title': '活动A'}, {'id': 'b', 'title': '活动B'}, {'id': 'c', 'title': '活动C'}],
     'runs': [], 'ends': []},
    # 同一活动同时出现在 starts 与 ends(当日开始并结束):只出现一次
    {'starts': [{'id': 'x', 'title': '单日活动X'}], 'runs': [{'id': 'x', 'title': '单日活动X'}],
     'ends': [{'id': 'x', 'title': '单日活动X'}, {'id': 'y', 'title': '活动Y'}]},
    # 进行中的活动排在 starts 之后,超过 2 条时截断
    {'starts': [{'id': 's1', 'title': '开始1'}], 'runs': [{'id': 'r1', 'title': '进行1'},
                                                          {'id': 'r2', 'title': '进行2'}], 'ends': []},
    # 空
    {'starts': [], 'runs': [], 'ends': []},
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
        print('SKIP: 未找到 node,跳过周视图测试')
        return 0
    html = open(HTML, encoding='utf-8').read()
    loader = LOADER.replace('__CASES__', json.dumps(CASES, ensure_ascii=False))
    r = subprocess.run([node, '-e', loader], input=html, capture_output=True,
                       text=True, encoding='utf-8', timeout=60)
    if r.returncode != 0:
        print('FAIL: node 执行失败\n' + r.stderr[:600])
        return 1
    got = json.loads(r.stdout.strip().splitlines()[-1])
    check('超过 2 条时截断', got[0], ['活动A', '活动B'])
    check('同一活动只出现一次', got[1], ['单日活动X', '活动Y'])
    check('开始活动优先于进行中', got[2], ['开始1', '进行1'])
    check('空单元格返回空数组', got[3], [])
    check('仅周视图使用小标题', 'calWeek?weekMiniNames(ev):[]' in html, True)

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
