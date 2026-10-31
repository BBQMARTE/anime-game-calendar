# -*- coding: utf-8 -*-
"""「导出当前筛选 .ics」测试。

设置「数据」里新增入口:把眼前这批活动(游戏/分类筛选、搜索词、快捷词、
数据质量筛选)整体导成一个 .ics;没有开始时间的条目会被跳过并如实提示,
资讯条目不算活动、不写入日历。离线 APK 同样可用(全在本地生成)。

运行:python tests/test_filter_ics.py(node 缺失则 SKIP)
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
const f = new Function('evStart',
  grab('isEv') + '\n' + grab('icsReadyList') + '\n' + grab('filterIcsList')
  + '\nreturn {isEv, icsReadyList, filterIcsList};')(
  e => (e.start ? new Date(e.start) : null));
const EVENTS = [
  {id:'a', title:'活动A', start:'2026-11-01T10:00', end:'2026-11-05T03:59'},
  {id:'b', title:'待定B', start:'', category:'活动'},
  {id:'c', title:'资讯C', kind:'info', start:'2026-10-20T10:00'},
  {id:'d', title:'活动D', start:'2026-10-25T10:00'},
  {id:'e', title:'资讯E', kind:'info'},
];
const list = f.filterIcsList(EVENTS);
console.log(JSON.stringify({
  ids: list.map(e => e.id),
  noInfo: EVENTS.filter(e => f.isEv(e)).map(e => e.id),
  readyAll: f.icsReadyList(EVENTS).map(e => e.id),
  hasFn: src.includes('function exportFilteredIcs('),
  useFiltered: src.includes('const evs=filteredAll().filter(isEv)'),
  pendingHint: src.includes("' · '+(evs.length-list.length)+' 条时间待定未导出'"),
  emptyHint: src.includes('当前筛选没有可导出的活动'),
  noStartHint: src.includes('当前筛选里的活动都还没确定开始时间'),
  entry: src.includes("onclick=\"exportFilteredIcs()\""),
  label: src.includes('导出当前筛选 .ics'),
  usesBuild: src.includes("buildDayIcs(list,'当前筛选')"),
  icsName: src.includes('二游活动_当前筛选.ics'),
  favFn: src.includes('function exportFavIcs('),
  favUsesList: src.includes('const evs=favList().filter(isEv)'),
  favBuild: src.includes("buildDayIcs(list,'我的收藏')"),
  favName: src.includes('二游活动_收藏.ics'),
  favEntry: src.includes('onclick="exportFavIcs()"'),
  favEmpty: src.includes('还没有可导出的收藏活动'),
  favNoStart: src.includes('收藏的活动都还没确定开始时间'),
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

    check('只保留真活动且必须有开始时间', d['ids'], ['a', 'd'])
    check('资讯条目不算活动', d['noInfo'], ['a', 'b', 'd'])
    check('icsReadyList 只按开始时间过滤', d['readyAll'], ['a', 'c', 'd'])
    check('导出函数已实现', d['hasFn'], True)
    check('导出用当前筛选结果', d['useFiltered'], True)
    check('时间待定条数如实提示', d['pendingHint'], True)
    check('空筛选有明确提示', d['emptyHint'], True)
    check('全部无开始时间有明确提示', d['noStartHint'], True)
    check('设置里有入口', d['entry'], True)
    check('入口文案清晰', d['label'], True)
    check('用 buildDayIcs 生成', d['usesBuild'], True)
    check('文件名固定可预期', d['icsName'], True)
    check('收藏 .ics 导出已实现', d['favFn'], True)
    check('收藏导出用 favList(与收藏页同源)', d['favUsesList'], True)
    check('收藏导出日历名为「我的收藏」', d['favBuild'], True)
    check('收藏导出文件名固定', d['favName'], True)
    check('设置里有收藏 .ics 入口', d['favEntry'], True)
    check('没有收藏时有明确提示', d['favEmpty'], True)
    check('收藏全部无开始时间有提示', d['favNoStart'], True)

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
