# -*- coding: utf-8 -*-
"""筛选器「复制清单」测试。

在顶部筛选条末尾新增「复制清单」:把当前筛选(游戏/分类/搜索词/快捷词/质量筛选)
得到的活动整理成「游戏｜标题｜时间」的一行一条纯文本,直接粘到群里。
无开始时间的条目排在最后并标「时间待定」,不会因为缺时间被悄悄丢掉。

运行:python tests/test_copy_filtered.py(node 缺失则 SKIP)
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
const evStart = e => (e.start ? new Date(e.start) : null);
const evEnd = e => (e.end ? new Date(e.end) : null);
const gameName = id => ({hsr:'崩坏：星穹铁道', zzz:'绝区零'})[id] || id;
const fmtRange = e => {
  const f = d => (d.getMonth()+1) + '月' + d.getDate() + '日';
  const s = evStart(e), t = evEnd(e);
  if (s && t) return f(s) + ' ~ ' + f(t);
  if (s) return f(s) + ' 起';
  return '时间待定';
};
const fn = new Function('evStart', 'evEnd', 'gameName', 'fmtRange',
  grab('filterCopyText') + '\nreturn filterCopyText;')(evStart, evEnd, gameName, fmtRange);
const EVENTS = [
  {game_id:'zzz', title:'活动B', start:'2026-11-02T10:00', end:'2026-11-10T03:59'},
  {game_id:'hsr', title:'活动A', start:'2026-10-30T10:00', end:'2026-11-05T03:59'},
  {game_id:'hsr', title:'时间待定C'},
];
const text = fn(EVENTS, '当前筛选');
console.log(JSON.stringify({
  text,
  empty: fn([], '当前筛选'),
  hasFn: src.includes('function copyFiltered('),
  usesFiltered: src.includes('const evs=filteredEvents()'),
  chip: src.includes('aria-label="复制当前筛选清单" onclick="copyFiltered()"'),
  emptyHint: src.includes('当前筛选没有活动可复制'),
  okHint: src.includes("'已复制 '+evs.length+' 个活动,可粘贴到群聊'"),
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

    check('首行是标题与条数', lines[0], '当前筛选 · 3 个活动')
    check('按开始时间排序,待定排最后', [ln.split('｜')[1] for ln in lines[1:]],
          ['活动A', '活动B', '时间待定C'])
    check('行格式为 游戏｜标题｜时间', lines[1], '- 崩坏：星穹铁道｜活动A｜10月30日 ~ 11月5日')
    check('无开始时间标为时间待定', lines[3], '- 崩坏：星穹铁道｜时间待定C｜时间待定')
    check('空列表返回空串(调用方给提示)', d['empty'], '')
    check('复制函数已实现', d['hasFn'], True)
    check('用当前筛选结果', d['usesFiltered'], True)
    check('筛选条里有入口 chip', d['chip'], True)
    check('空结果有轻提示', d['emptyHint'], True)
    check('成功有轻提示并带条数', d['okHint'], True)

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
