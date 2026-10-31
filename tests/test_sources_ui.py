# -*- coding: utf-8 -*-
"""数据源状态可点查看测试。

首页顶部只显示小圆点 + 名称,失败原因和「上次成功」只放在 title 里,
手机上没有 hover 看不到。现在点一下数据源就把名称 + 状态弹出来。

运行:python tests/test_sources_ui.py(node 缺失则 SKIP)
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
const alerts = [];
const info = new Function('alert', grab('srcInfo') + '\nreturn srcInfo;')(m => alerts.push(m));
info({getAttribute: k => ({'data-name':'B站','data-tip':'抓取失败: timeout · 上次成功 10-31 09:00'})[k]});
info({getAttribute: k => ({'data-name':'人工','data-tip':'12 条'})[k]});
info({getAttribute: k => ({'data-name':'', 'data-tip':''})[k]});
console.log(JSON.stringify({
  alerts,
  hasEntry: src.includes('onclick="srcInfo(this)"'),
  hasData: src.includes('data-tip="${esc(tip)}"') && src.includes('data-name="${esc(s.name||k)}"'),
  hasFn: src.includes('function srcInfo('),
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

    check('数据源可点查看', d['hasEntry'], True)
    check('状态写进 data 属性(移动端也能读)', d['hasData'], True)
    check('srcInfo 已实现', d['hasFn'], True)
    check('失败源弹出名称 + 原因 + 上次成功',
          d['alerts'][0], 'B站\n抓取失败: timeout · 上次成功 10-31 09:00')
    check('正常源弹出条数', d['alerts'][1], '人工\n12 条')
    check('无内容时给出提示', d['alerts'][2], '暂无状态')

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
