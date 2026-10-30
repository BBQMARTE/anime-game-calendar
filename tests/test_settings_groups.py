# -*- coding: utf-8 -*-
"""设置面板分组折叠测试。

设置项一多就整屏堆在一起,找不到想改的那一项;改成三个可折叠分组
(日历 / 提醒推送 / 数据)后,用 node + DOM 桩渲染 openSettings() 断言:
分组数量、三个标题、默认全部展开、以及折叠箭头 CSS 是否在样式里。

运行:python3 tests/test_settings_groups.py(node 缺失则 SKIP)
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
  if (i < 0) throw new Error('function not found: ' + name);
  let depth = 0, started = false;
  for (let k = src.indexOf('{', i); k < src.length; k++) {
    if (src[k] === '{') { depth++; started = true; }
    else if (src[k] === '}') { depth--; if (started && !depth) return src.slice(i, k + 1); }
  }
  throw new Error('unbalanced braces: ' + name);
}
const code = ['esc', 'openSettings'].map(grab).join('\n');
const DATA = {
  games: [{id:'hsr', name:'崩坏：星穹铁道', color:'#b688ff'},
          {id:'zzz', name:'绝区零', color:'#ff7a45'}],
  events: [
    {kind:'event', src:'manual', image:'x.png'},
    {kind:'event', src:'bilibili', image:'x.png'},
    {kind:'event', src:'', image:'x.png'},        // 未核实、有图
    {kind:'event', src:''},                       // 未核实、无图
    {kind:'info', src:''},                        // 公告不计入自动条目
  ],
};
const captured = [];
const document = {
  createElement: () => ({ className:'', innerHTML:'', addEventListener(){} }),
  body: { appendChild(o) { captured.push(o); } },
};
const settings = {calOn:true, hideAuto:false};
const api = new Function('DATA','document','calGamesSet','settings','attachSwipeClose','loadNotifyCfgUI',
  code + '\nreturn {openSettings};')
  (DATA, document, () => new Set(['hsr','zzz']), settings, () => {}, () => {});
api.openSettings();
const out = captured.length ? captured[0].innerHTML : '';
console.log(JSON.stringify({
  groups: (out.match(/<details class="set-group" open>/g) || []).length,
  summaries: (out.match(/<summary class="set-sec">([^<]*)<\/summary>/g) || []).map(s => s.replace(/<[^>]+>/g, '')),
  anyCollapsed: /<details class="set-group">/.test(out),
  hasAutoHint: out.includes('当前 2 条自动条目会被隐藏') && out.includes('其中 1 条无图'),
  hasCss: html.includes('.set-group>summary::-webkit-details-marker{display:none}')
      && html.includes('.set-group[open]>summary::after{transform:rotate(-90deg)}'),
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
        print('SKIP: 未找到 node，跳过设置分组测试')
        return 0
    r = subprocess.run([node, '-e', LOADER], input=open(HTML, encoding='utf-8').read(),
                       capture_output=True, text=True, encoding='utf-8', timeout=60)
    if r.returncode != 0:
        print('FAIL: node 执行失败\n' + r.stderr[:800])
        return 1
    d = json.loads(r.stdout.strip().splitlines()[-1])
    check("设置面板渲染成功", True, True)
    check("三个折叠分组", d['groups'], 3)
    check("分组标题依次为 日历/提醒推送/数据", d['summaries'], ['日历', '提醒推送', '数据'])
    check("默认全部展开", d['anyCollapsed'], False)
    check("隐藏自动条目仍显示条数提示", d['hasAutoHint'], True)
    check("折叠箭头样式已写入", d['hasCss'], True)

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
