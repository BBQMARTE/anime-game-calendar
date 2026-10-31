# -*- coding: utf-8 -*-
"""详情弹窗「只看该游戏」按钮测试。

按钮文案是「只看该游戏全部活动」,所以点击后必须真的看到该游戏的全部活动:
清掉搜索词、数据质量筛选与分类筛选,并清掉分享链接里点名的游戏
(_urlGames 会绕过 activeGames,不清就会漏出别的游戏)。
其余筛选(隐藏自动/已完成等偏好)保持不变。

运行:python tests/test_only_game.py(node 缺失则 SKIP)
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
const CAT_COLOR = {'活动': 1, '签到': 1, '资讯': 1};
const qi = {value: '签到'};
const flashes = [];
let cleared = 0, saved = 0, rendered = 0;
const env = new Function('document','$','saveFilters','clearUrlGames','render','flash','CAT_COLOR','gameName','window',
  "let activeGames=new Set(['hsr','zzz']), activeCats=new Set(['活动']), q='签到', dq='noimg';\n"
  + grab('onlyThisGame') + "\n"
  + "return {run:onlyThisGame, get:()=>({games:[...activeGames],cats:[...activeCats],q:q,dq:dq}), input:()=>qi.value};"
)({
  querySelectorAll: () => [],
}, s => (s === '#q' ? qi : null), () => { saved++; }, () => { cleared++; }, () => { rendered++; },
  m => flashes.push(m), CAT_COLOR, id => ({hsr:'崩坏：星穹铁道', zzz:'绝区零'})[id] || id,
  {scrollTo(){}});
env.run('zzz');
const after = env.get();
console.log(JSON.stringify({
  after, input: env.input(), flashes, cleared, saved, rendered,
  hasClear: src.includes('clearUrlGames();   // 分享链接里点名的游戏会绕过 activeGames'),
  hasReset: src.includes("dq='';             // 「全部活动」:搜索词与质量筛选一并清掉"),
  flashMsg: src.includes("flash('只看 '+gameName(id))"),
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

    check('只保留点名的游戏', d['after']['games'], ['zzz'])
    check('分类筛选清空(全部活动)', d['after']['cats'], ['活动', '签到', '资讯'])
    check('搜索词清空', d['after']['q'], '')
    check('搜索输入框同步清空', d['input'], '')
    check('数据质量筛选清空', d['after']['dq'], '')
    check('分享链接点名的游戏被清掉', d['cleared'], 1)
    check('筛选偏好落盘并重绘各一次', (d['saved'], d['rendered']), (1, 1))
    check('轻提示只看该游戏', d['flashes'], ['只看 绝区零'])
    check('源码保留清 _urlGames 的说明', d['hasClear'], True)
    check('源码保留清搜索/质量筛选的说明', d['hasReset'], True)
    check('源码有轻提示', d['flashMsg'], True)

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
