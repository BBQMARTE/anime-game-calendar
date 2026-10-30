# -*- coding: utf-8 -*-
"""「复制活动信息」纯文本测试。

详情页一键复制整理好的文本(游戏/标题/时间/分类/链接),可直接粘到群聊。
运行:python3 tests/test_copy_event.py(node 缺失则 SKIP)
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
const code = "const pad=n=>String(n).padStart(2,'0');\n"
  + ['evStart','evEnd','fmtRange','eventText'].map(grab).join('\n');
const api = new Function(code + '\nreturn {eventText};')();
const full = {game:'崩坏：星穹铁道', title:'活动A', category:'活动', link:'https://x/y',
  start:'2026-11-01T10:00', end:'2026-11-10T03:59'};
const noLink = {game_id:'zzz', title:'活动B', category:'签到', start:'2026-11-05T10:00', end:'2026-11-06T23:59'};
const nodate = {game:'绝区零', title:'活动C', _nodate:true, date:'2026-10-20T10:00'};
console.log(JSON.stringify({
  full: api.eventText(full),
  noLink: api.eventText(noLink),
  nodate: api.eventText(nodate),
  hasBtn: html.includes('复制活动信息'),
  hasFn: html.includes('function copyEventText'),
  hasClip: html.includes("navigator.clipboard.writeText(text)"),
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
        print('SKIP: 未找到 node，跳过复制活动信息测试')
        return 0
    r = subprocess.run([node, '-e', LOADER], input=open(HTML, encoding='utf-8').read(),
                       capture_output=True, text=True, encoding='utf-8', timeout=60)
    if r.returncode != 0:
        print('FAIL: node 执行失败\n' + r.stderr[:800])
        return 1
    d = json.loads(r.stdout.strip().splitlines()[-1])
    check("完整信息四行", d['full'],
          '【崩坏：星穹铁道】活动A\n时间:11月1日 10:00 ~ 11月10日 03:59\n分类:活动\n链接:https://x/y')
    check("无链接时省略链接行,游戏回退 game_id", d['noLink'],
          '【zzz】活动B\n时间:11月5日 10:00 ~ 11月6日 23:59\n分类:签到')
    check("无日期的条目时间写作待定", d['nodate'], '【绝区零】活动C\n时间:待定')
    check("详情页有「复制活动信息」按钮", d['hasBtn'], True)
    check("copyEventText 已实现", d['hasFn'], True)
    check("使用剪贴板 API", d['hasClip'], True)

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
