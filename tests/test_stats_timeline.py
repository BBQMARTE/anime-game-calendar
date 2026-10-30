# -*- coding: utf-8 -*-
"""数据统计弹窗「未来 14 天时间线」的渲染测试。

用 node 提取 index.html 里的纯函数,配一个最小 DOM 桩直接调用 openStats(),
断言产出 HTML 含时间线区块、刻度、以及正确数量的甘特条。无需真实浏览器。

运行:python3 tests/test_stats_timeline.py(node 缺失则 SKIP)
"""
import json, os, shutil, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, 'static', 'index.html')

LOADER = r"""
const fs = require('fs');
const html = fs.readFileSync(0, 'utf8');
const blocks = html.match(/<script>[\s\S]*?<\/script>/g) || [];
const src = blocks.map(b => b.replace(/<\/?script>/g, '')).join('\n');
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
const code = ['esc','evStart','evEnd','isEv','gameColor','gameName'].map(grab).join('\n');
const CAT = src.match(/const CAT_COLOR=[^\n]+/)[0];
const stats = grab('openStats');
const now = new Date(2026, 9, 31, 12, 0, 0);
const DATA = {
  updated: '2026-10-31T12:00:00',
  games: [{id:'hsr', name:'崩坏：星穹铁道', color:'#b688ff'},
          {id:'zzz', name:'绝区零', color:'#ff7a45'}],
  events: [
    // 进行中:9-20 至 11-10
    {id:'a', game_id:'hsr', game:'崩坏：星穹铁道', title:'进行中活动', category:'活动',
     kind:'event', start:'2026-09-20T10:00', end:'2026-11-10T03:59'},
    // 5 天后开始,1 天后结束 → 落在时间线里
    {id:'b', game_id:'zzz', game:'绝区零', title:'五天后活动', category:'活动',
     kind:'event', start:'2026-11-05T10:00', end:'2026-11-06T23:59'},
    // 40 天后开始 → 超出 14 天窗口,不应出现
    {id:'c', game_id:'hsr', game:'崩坏：星穹铁道', title:'远期活动', category:'活动',
     kind:'event', start:'2026-12-10T10:00', end:'2026-12-20T03:59'},
  ],
};
const captured = [];
global.document = {
  createElement: () => ({ className: '', innerHTML: '', addEventListener(){}, querySelector(){ return null; } }),
  body: { appendChild(o) { captured.push(o); } },
};
const api = new Function('DATA', 'document', 'attachSwipeClose', 'Date',
  code + '\n' + CAT + '\n' + stats + '\nreturn {openStats, tlCount: 0};'
)(DATA, global.document, () => {}, Date);
api.openStats();
const out = captured.length ? captured[0].innerHTML : '';
console.log(JSON.stringify({
  hasSection: out.includes('未来 14 天时间线'),
  hasAxis: out.includes('+7 天') && out.includes('+14 天') && out.includes('今天'),
  bars: (out.match(/tl-track/g) || []).length,
  names: [...out.matchAll(/class="tl-name"[^>]*>([^<]*)</g)].map(m => m[1]),
  badRange: [...out.matchAll(/left:([-\d.]+)%;width:([-\d.]+)%/g)]
      .some(m => +m[1] < 0 || +m[1] > 100 || +m[2] < 0 || +m[2] > 100),
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
        print('SKIP: 未找到 node，跳过时间线渲染测试')
        return 0
    r = subprocess.run([node, '-e', LOADER], input=open(HTML, encoding='utf-8').read(),
                       capture_output=True, text=True, encoding='utf-8', timeout=60)
    if r.returncode != 0:
        print('FAIL: node 执行失败\n' + r.stderr[:800])
        return 1
    d = json.loads(r.stdout.strip().splitlines()[-1])
    check("统计弹窗渲染成功", True, True)
    check("含时间线区块标题", d['hasSection'], True)
    check("含时间线刻度", d['hasAxis'], True)
    check("甘特条数量(窗口内 2 条)", d['bars'], 2)
    check("窗口外的远期活动被排除", d['names'], ['进行中活动', '五天后活动'])
    check("条带百分比在 0~100 内", d['badRange'], False)

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
