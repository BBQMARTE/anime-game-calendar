# -*- coding: utf-8 -*-
"""桌面快捷键与「只看该游戏」入口测试。

- Esc 关闭最上层弹窗;「/」或 Ctrl/Cmd+K 聚焦搜索框(正在输入时不抢焦点)
- 详情页提供「只看某游戏的活动」按钮
运行:python3 tests/test_hotkeys.py(node 缺失则 SKIP)
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
const isTypingTag = new Function(grab('isTypingTag') + '\nreturn isTypingTag;')();
console.log(JSON.stringify({
  input: isTypingTag('INPUT'),
  textarea: isTypingTag('TEXTAREA'),
  select: isTypingTag('SELECT'),
  div: isTypingTag('DIV'),
  none: isTypingTag(null),
  listener: html.includes("document.addEventListener('keydown',hotkeyGo)"),
  esc: html.includes("if(e.key==='Escape')"),
  slash: html.includes("const slash=e.key==='/'"),
  cmdK: html.includes("toLowerCase()==='k'"),
  onlyGameFn: html.includes('function onlyThisGame'),
  onlyGameBtn: html.includes('只看「'),
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
        print('SKIP: 未找到 node，跳过快捷键测试')
        return 0
    r = subprocess.run([node, '-e', LOADER], input=open(HTML, encoding='utf-8').read(),
                       capture_output=True, text=True, encoding='utf-8', timeout=60)
    if r.returncode != 0:
        print('FAIL: node 执行失败\n' + r.stderr[:800])
        return 1
    d = json.loads(r.stdout.strip().splitlines()[-1])
    check("输入框视为正在输入", d['input'], True)
    check("多行文本域视为正在输入", d['textarea'], True)
    check("下拉框视为正在输入", d['select'], True)
    check("普通容器不算输入", d['div'], False)
    check("无焦点元素不算输入", d['none'], False)
    check("注册 keydown 监听", d['listener'], True)
    check("Esc 关闭弹窗", d['esc'], True)
    check("「/」聚焦搜索", d['slash'], True)
    check("Ctrl/Cmd+K 聚焦搜索", d['cmdK'], True)
    check("onlyThisGame 已实现", d['onlyGameFn'], True)
    check("详情页有「只看某游戏」按钮", d['onlyGameBtn'], True)

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
