# -*- coding: utf-8 -*-
"""「隐藏已完成的活动」开关测试。

打钩「做完」的条目默认仍显示(划线样式);打开设置里的隐藏开关后,
列表/月历都不再出现它们,关掉即可看回历史。

运行:python3 tests/test_hide_done.py(node 缺失则 SKIP)
"""
import json, os, shutil, subprocess, sys

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
const DONE = {'zzz|已完成活动': true};
const isDone = e => !!DONE[(e.game_id || '') + '|' + (e.title || '')];
const DATA = {events: [
  {id:'a', game_id:'zzz', title:'已完成活动', category:'活动', src:'manual'},
  {id:'b', game_id:'hsr', title:'未完成活动', category:'活动', src:'manual'},
]};
const runFiltered = new Function('DATA','q','activeGames','activeCats','calVisible','settings','isDone',
  "const QUICK_WORDS=[];\nfunction isQuickWord(){return false}\nfunction quickMatch(){return false}\nfunction gamePrefix(){return null}\nlet dq='';\nfunction dqMatch(){return true}\n"
  + grab('filtered') + '\nreturn filtered();');
console.log(JSON.stringify({
  off: runFiltered(DATA, '', new Set(['zzz','hsr']), new Set(['活动']), () => true,
                   {hideAuto:false, hideDone:false}, isDone).map(e => e.id),
  on: runFiltered(DATA, '', new Set(['zzz','hsr']), new Set(['活动']), () => true,
                  {hideAuto:false, hideDone:true}, isDone).map(e => e.id),
  hasRow: src.includes('隐藏已完成的活动'),
  hasToggle: src.includes('function toggleHideDone'),
  defaultOff: src.includes('hideDone:false'),
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
        print('SKIP: 未找到 node，跳过隐藏完成测试')
        return 0
    r = subprocess.run([node, '-e', LOADER], input=open(HTML, encoding='utf-8').read(),
                       capture_output=True, text=True, encoding='utf-8', timeout=60)
    if r.returncode != 0:
        print('FAIL: node 执行失败\n' + r.stderr[:800])
        return 1
    d = json.loads(r.stdout.strip().splitlines()[-1])
    check("开关关闭时已完成条目仍显示", d['off'], ['a', 'b'])
    check("开关打开时隐藏已完成条目", d['on'], ['b'])
    check("设置面板有该开关", d['hasRow'], True)
    check("toggleHideDone 已实现", d['hasToggle'], True)
    check("默认关闭(不改变老用户观感)", d['defaultOff'], True)

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
