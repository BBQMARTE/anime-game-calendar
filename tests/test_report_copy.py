# -*- coding: utf-8 -*-
"""「我的反馈」复制待核查清单测试。

每日核查需要把待核查反馈发给核查人(或自己对照官方公告逐条查),
新增「复制待核查」:一行一条「游戏｜标题｜类型｜提交时间」,已处理的不会混进来。

运行:python tests/test_report_copy.py(node 缺失则 SKIP)
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
const REPORT_LABEL = {'missing-image':'缺图','no-end':'缺结束时间','wrong-time':'时间不对','other':'其他'};
const gameName = id => ({hsr:'崩坏：星穹铁道', zzz:'绝区零'})[id] || id;
const fn = new Function('gameName', 'REPORT_LABEL',
  grab('reportCopyText') + '\nreturn reportCopyText;')(gameName, REPORT_LABEL);
const ITEMS = [
  {game_id:'hsr', title:'画外遗光', kind:'no-end', at:'2026-10-31T09:20:00', done:false},
  {game_id:'zzz', title:'限定角色活动', kind:'missing-image', at:'2026-10-30T18:00:00', done:true},
  {game_id:'hsr', title:'奇怪的时间', kind:'wrong-time', at:'2026-10-29T11:05:00', done:false},
];
const text = fn(ITEMS);
console.log(JSON.stringify({
  text,
  empty: fn([]),
  onlyDone: fn([{game_id:'zzz', title:'已处理', kind:'other', at:'2026-10-30T10:00', done:true}]),
  hasFn: src.includes('function copyPendingReports('),
  cache: src.includes('_REPORTS_CACHE=all'),
  button: src.includes('onclick="copyPendingReports()"'),
  onlyPending: src.includes('${pendAll?`<span class="stat-link" onclick="copyPendingReports()">'),
  emptyHint: src.includes('没有待核查反馈可复制'),
  okHint: src.includes("'已复制 '+n+' 条待核查反馈,可发给核查人'"),
  usesCache: src.includes('const text=reportCopyText(_REPORTS_CACHE)'),
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
    lines = d['text'].split('\n')

    check('首行是标题与待核查条数', lines[0], '待核查反馈 · 2 条')
    check('已处理的反馈不出现', '限定角色活动' in d['text'], False)
    check('行格式为 游戏｜标题｜类型｜时间', lines[1], '- 崩坏：星穹铁道｜画外遗光｜缺结束时间｜10-31 09:20')
    check('三类反馈都能列出', lines[2], '- 崩坏：星穹铁道｜奇怪的时间｜时间不对｜10-29 11:05')
    check('空清单返回空串', d['empty'], '')
    check('全是已处理时返回空串', d['onlyDone'], '')
    check('复制函数已实现', d['hasFn'], True)
    check('从最近一次清单取数', (d['cache'], d['usesCache']), (True, True))
    check('反馈页有「复制待核查」入口', d['button'], True)
    check('待核查为 0 时不显示入口', d['onlyPending'], True)
    check('空清单有轻提示', d['emptyHint'], True)
    check('成功提示带条数', d['okHint'], True)

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
