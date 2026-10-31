# -*- coding: utf-8 -*-
"""「隐藏未核实的自动条目」筛选口径测试。

从 index.html 提取 filtered() 并注入依赖桩,验证:
关闭开关时三类来源都出现;打开后只剩 manual / bilibili,爬虫自动条目被隐藏。

运行:python3 tests/test_hide_auto.py(node 缺失则 SKIP)
"""
import json, os, shutil, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, 'static', 'index.html')

LOADER = r"""
const fs = require('fs');
const html = fs.readFileSync(0, 'utf8');
const src = (html.match(/<script>[\s\S]*?<\/script>/g) || [])
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
// filtered() 依赖同名自由变量(DATA/q/activeGames/activeCats/calVisible/settings);
// 本用例只测「隐藏自动条目」,q 为空,所以快捷词/游戏前缀函数用桩即可(不会被实际调用)
const runFiltered = new Function('DATA','q','activeGames','activeCats','calVisible','settings',
  "const QUICK_WORDS=[];\nfunction isQuickWord(){return false}\nfunction quickMatch(){return false}\nfunction gamePrefix(){return null}\nfunction isDone(){return false}\nlet dq='';\nfunction dqMatch(){return true}\n"
  + grab('filtered') + '\nreturn filtered();');
const DATA = { events: [
  {id:'m', game_id:'zzz', title:'人工核实', category:'活动', src:'manual'},
  {id:'b', game_id:'hsr', title:'B站动态', category:'活动', src:'bilibili'},
  {id:'c', game_id:'zzz', title:'自动抓取', category:'活动'},
]};
const run = (hideAuto) => runFiltered(DATA, '', new Set(['zzz','hsr']),
  new Set(['活动','签到','角色与专武','公告','资讯']), () => true, {hideAuto})
  .map(e => e.id);
console.log(JSON.stringify({ off: run(false), on: run(true) }));
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
        print('SKIP: 未找到 node，跳过筛选测试')
        return 0
    r = subprocess.run([node, '-e', LOADER], input=open(HTML, encoding='utf-8').read(),
                       capture_output=True, text=True, encoding='utf-8', timeout=60)
    if r.returncode != 0:
        print('FAIL: node 执行失败\n' + r.stderr[:600])
        return 1
    d = json.loads(r.stdout.strip().splitlines()[-1])
    check("默认显示三类来源", d['off'], ['m', 'b', 'c'])
    check("开启后只剩人工与 B站", d['on'], ['m', 'b'])

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
