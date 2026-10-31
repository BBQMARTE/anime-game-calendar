# -*- coding: utf-8 -*-
"""数据统计面板的「可点条目」测试。

统计页原先只读:看到 14 天时间线里某条活动、或近期变更里某条改期,
没法直接跳过去。现在:
  - 时间线条目 -> showDetailById(id) 打开详情
  - 近期变更的新增/改期 -> jumpToChange(title, game_id) 在当前列表里定位
  - 已移除的变更 -> 只提示「已被官方移除」,不给跳转(列表里确实没有)
  - 各游戏/分类条形图 -> statGame / statCat 只看该游戏/分类

运行:python tests/test_stats_actions.py(node 缺失则 SKIP)
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
const code = ['esc','evStart','evEnd','isEv','gameColor','gameName','isPointItem','isStaleUnknown','isOngoingEvent'].map(grab).join('\n');
const CAT = src.match(/const CAT_COLOR=[^\n]+/)[0];
const stats = grab('openStats');
const now = new Date(2026, 9, 31, 12, 0, 0);
const DATA = {
  updated: '2026-10-31T12:00:00',
  games: [{id:'hsr', name:'崩坏：星穹铁道', color:'#b688ff'},
          {id:'zzz', name:'绝区零', color:'#ff7a45'}],
  events: [
    {id:'a', game_id:'hsr', game:'崩坏：星穹铁道', title:'进行中活动', category:'活动',
     kind:'event', start:'2026-09-20T10:00', end:'2026-11-10T03:59', image:'cover.jpg'},
    {id:'b', game_id:'zzz', game:'绝区零', title:'五天后活动', category:'签到',
     kind:'event', start:'2026-11-05T10:00', end:'2026-11-06T23:59'},
  ],
  changes: [
    {type:'moved', title:'进行中活动', game_id:'hsr', at:'2026-10-30T10:00:00',
     from:{start:'2026-09-25T10:00', end:'2026-11-10T03:59'}, to:{start:'2026-09-20T10:00', end:'2026-11-10T03:59'}},
    {type:'removed', title:'已撤下活动', game_id:'zzz', at:'2026-10-29T10:00:00',
     from:{start:'2026-10-01T10:00', end:'2026-10-20T03:59'}, to:null},
  ],
};
const captured = [];
global.document = {
  createElement: () => ({ className: '', innerHTML: '', addEventListener(){}, querySelector(){ return null; } }),
  body: { appendChild(o) { captured.push(o); } },
};
function chgTypeLabel(t){return t==='moved'?'改期':t==='removed'?'移除':'新增'}
function chgDesc(r){return r.type==='moved'?'原时间 → 现时间':'已移除'}
const api = new Function('DATA', 'document', 'attachSwipeClose', 'Date', 'chgTypeLabel', 'chgDesc',
  code + '\n' + CAT + '\n' + stats + '\nreturn {openStats};'
)(DATA, global.document, () => {}, Date, chgTypeLabel, chgDesc);
api.openStats();
const out = captured.length ? captured[0].innerHTML : '';
console.log(JSON.stringify({
  timelineClick: out.includes("onclick=\"showDetailById('a')\""),
  movedJump: out.includes('onclick="jumpToChange('),
  removedNoJump: (out.match(/removedFlash/g) || []).length === 1
                 && !/chg-row removed"[^>]*jumpToChange/.test(out),
  gameBar: out.includes("statGame('hsr',this)"),
  catBar: out.includes("statCat('活动',this)"),
  weekStart: out.includes("statRange('本周开始',this)"),
  monthStart: out.includes("statRange('本月开始',this)"),
  fns: ['jumpToChange','removedFlash','showDetailById','statGame','statCat','statRange'].map(n => src.includes('function ' + n + '(')),
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

    check("时间线条目可点开详情", d['timelineClick'], True)
    check("改期/新增条目可定位", d['movedJump'], True)
    check("已移除条目不跳转,只提示", d['removedNoJump'], True)
    check("游戏条形图可只看该游戏", d['gameBar'], True)
    check("分类条形图可只看该分类", d['catBar'], True)
    check("本周开始可筛列表", d['weekStart'], True)
    check("本月开始可筛列表", d['monthStart'], True)
    check("跳转/详情函数均已定义", d['fns'], [True] * 6)

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
