# -*- coding: utf-8 -*-
"""周视图「复制本周 / 导出本周 .ics」测试。

周视图新增两个入口:复制整周排期成纯文本发群,或把本周活动打包成一个 .ics。
口径:开始日落在本周;跨周活动有明确结束时间且仍在本周内也保留;
无结束时间的条目只在开始当天出现,前一周开始的不提前混进来。

运行:python tests/test_week_ics.py(node 缺失则 SKIP)
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
const code = ['evStart','evEnd','weekRange','weekEvents'].map(grab).join('\n');
const api = new Function(code + '\nreturn {weekRange,weekEvents};')();
const base = new Date(2026, 10, 3, 12, 0, 0);   // 2026-11-03 周二
const r = api.weekRange(base);
const fmt = d => d.getFullYear() + '-' + (d.getMonth() + 1) + '-' + d.getDate();
const evs = [
  {id:'sun', start:'2026-11-01T10:00'},
  {id:'tue', start:'2026-11-03T10:00'},
  {id:'sat', start:'2026-11-07T23:00'},
  {id:'prev_noend', start:'2026-10-31T10:00'},
  {id:'cross', start:'2026-10-28T10:00', end:'2026-11-03T03:59'},
  {id:'cross_noend', start:'2026-10-28T10:00'},
  {id:'next_sun', start:'2026-11-08T00:00'},
  {id:'ends_at_boundary', start:'2026-11-07T20:00', end:'2026-11-08T00:00'},
];
const ids = api.weekEvents(evs, r).map(e => e.id);
const empty = api.weekEvents(evs, api.weekRange(new Date(2026, 11, 1)));
const gameName = id => ({hsr:'崩坏：星穹铁道', zzz:'绝区零'})[id] || id;
const fmtRange = e => e.range || '';
const copyFn = new Function('evStart','gameName','fmtRange',
  grab('weekCopyText') + '\nreturn weekCopyText;')(e => (e.start ? new Date(e.start) : null), gameName, fmtRange);
const copyText = copyFn([
  {game_id:'zzz', title:'周二活动', start:'2026-11-03T10:00', range:'11月3日 10:00 ~ 11月10日 03:59'},
  {game_id:'hsr', title:'周日活动', start:'2026-11-01T10:00', range:'11月1日 10:00 起'},
  {game_id:'hsr', title:'时间待定', start:null},
], '本周活动 11月1日–11月7日');
const copyEmpty = copyFn([], '本周活动 11月1日–11月7日');
console.log(JSON.stringify({
  start: fmt(r.start),
  end: fmt(r.end),
  ids,
  emptyCount: empty.length,
  copyText,
  copyEmpty,
  hasEntry: src.includes('onclick="exportWeekIcs()"') && src.includes('onclick="copyWeek()"'),
  hasFn: src.includes('function exportWeekIcs(') && src.includes('function weekEvents(')
    && src.includes('function weekCopyText(') && src.includes('function copyWeek('),
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

    check('周范围从周日起到周六', (d['start'], d['end']), ('2026-11-1', '2026-11-8'))
    check('本周活动:开始日在本周 + 跨周且有结束时间',
          d['ids'], ['sun', 'tue', 'sat', 'cross', 'ends_at_boundary'])
    check('前一周开始的无结束条目不算本周', 'prev_noend' in d['ids'], False)
    check('下个周日的活动不算本周', 'next_sun' in d['ids'], False)
    check('其它周没有活动时返回空', d['emptyCount'], 0)
    lines = d['copyText'].split('\n')
    check('复制本周首行是标题与总数', lines[0], '本周活动 11月1日–11月7日 · 3 个活动')
    check('复制本周按开始时间排序(无开始时间排最后)',
          (lines[1].startswith('- 崩坏：星穹铁道｜周日活动｜')
           and lines[2].startswith('- 绝区零｜周二活动｜')), True)
    check('有开始时间时带时间范围', lines[1].endswith('11月1日 10:00 起'), True)
    check('无开始时间显示「时间待定」', lines[3].startswith('- 崩坏：星穹铁道｜时间待定｜') and lines[3].endswith('时间待定'), True)
    check('本周没有活动时复制文本为空', d['copyEmpty'], '')
    check('周视图有「复制本周 / 导出本周 .ics」入口', d['hasEntry'], True)
    check('copyWeek / weekCopyText 等函数已实现', d['hasFn'], True)

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
