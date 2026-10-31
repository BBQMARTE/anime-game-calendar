# -*- coding: utf-8 -*-
"""分享链接/统计跳转的「隐藏游戏强制显示」回收测试。

_urlGames 原本只用于「别人发来的分享链接里点名的游戏」:即使本机设置里勾掉了,
也要显示出来。后来统计面板的跳转也复用了它,但如果用户之后手动改筛选,
这个强制显示必须收回,否则被设置隐藏的游戏会一直留在列表里直到刷新页面。

运行:python tests/test_share_reset.py(node 缺失则 SKIP)
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
const mk = new Function(
  'let _urlGames={hidden:1};\nconst activeGames=new Set(["a"]);\nconst activeCats=new Set([]);\nfunction saveFilters(){}\nfunction render(){}\n'
  + grab('clearUrlGames') + '\n' + grab('toggleGame') + '\n' + grab('toggleCat')
  + '\nreturn {tg:toggleGame, tc:toggleCat, u:()=>_urlGames, a:()=>[...activeGames]};');
const f = mk();
f.tg('a');
const r1 = {cleared: f.u() === null, active: f.a()};
f.tc('活动');
const r2 = {cleared: f.u() === null};
console.log(JSON.stringify({
  afterToggleGame: r1,
  afterToggleCat: r2,
  hasFn: src.includes('function clearUrlGames()'),
  toggleAll: /function toggleAll\(\)\{\s*clearUrlGames\(\);/.test(src),
  clearFilters: /function clearFilters\(\)\{\s*clearUrlGames\(\);/.test(src),
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

    check("手动切换游戏后收回强制显示", d['afterToggleGame']['cleared'], True)
    check("切换游戏本身仍生效(取消选中)", d['afterToggleGame']['active'], [])
    check("手动切换分类后收回强制显示", d['afterToggleCat']['cleared'], True)
    check("clearUrlGames 已实现", d['hasFn'], True)
    check("全部按钮也会收回", d['toggleAll'], True)
    check("清除筛选也会收回", d['clearFilters'], True)

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
