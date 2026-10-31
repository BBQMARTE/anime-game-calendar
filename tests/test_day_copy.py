# -*- coding: utf-8 -*-
"""月历「复制当天」测试。

点日期只看当天活动,但想把这一天发到群里还得逐条点开复制。
现在选中日的标题右侧有「复制当天」:按「当天开始 / 进行中 / 当天结束」分组,
每行「游戏｜标题｜时间范围」,整段可直接粘贴。

运行:python tests/test_day_copy.py(node 缺失则 SKIP)
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
const gameName = id => ({hsr:'崩坏：星穹铁道', zzz:'绝区零', wuwa:'鸣潮'})[id] || id;
const evStart = e => (e.start ? new Date(e.start) : null);
const fmtRange = e => (e.range || '');
const textFn = new Function('gameName','evStart','fmtRange',
  grab('dayCopyText') + '\nreturn dayCopyText;')(gameName, evStart, fmtRange);
const mkEv = () => ({
  starts: [
    {game_id:'hsr', title:'画外遗光', start:'2026-11-03T10:00', end:'2026-11-17T03:59', range:'11月3日 10:00 ~ 11月17日 03:59'},
    {game_id:'zzz', title:'限时活动', start:'2026-11-03T12:00', end:null, range:'11月3日 12:00 起'},
  ],
  runs: [
    {game_id:'wuwa', title:'进行中的活动', start:'2026-11-01T10:00', end:'2026-11-03T23:59', range:'11月1日 10:00 ~ 11月3日 23:59'},
  ],
  ends: [
    {game_id:'hsr', title:'收尾活动', start:null, end:'2026-11-03T03:59', range:''},
  ],
});
const text = textFn(mkEv(), '11月3日 周一');
const empty = textFn({starts:[], runs:[], ends:[]}, '11月3日 周一');
const flashes = [];
const emptyCall = new Function('eventsOnDay','dayLabel','selDay','dayCopyText','flash',
  grab('copyDay') + '\nreturn copyDay;')(
    () => ({starts:[], runs:[], ends:[]}), () => '11月3日 周一',
    new Date(2026, 10, 3), textFn, m => flashes.push(m));
emptyCall();
console.log(JSON.stringify({
  text,
  empty,
  flashes,
  hasEntry: src.includes('onclick="copyDay()"'),
  hasFn: src.includes('function copyDay(') && src.includes('function dayCopyText('),
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
    text = d['text']
    lines = text.split('\n')

    check('日历选中日有「复制当天」入口', d['hasEntry'], True)
    check('copyDay / dayCopyText 已实现', d['hasFn'], True)
    check('首行是日期与活动总数', lines[0], '11月3日 周一 · 4 个活动')
    check('按三类分组', ('[当天开始 · 2]' in text and '[进行中 · 1]' in text and '[当天结束 · 1]' in text), True)
    check('分组顺序:开始 → 进行中 → 结束',
          text.index('[当天开始') < text.index('[进行中') < text.index('[当天结束'), True)
    check('每行是 游戏｜标题｜时间',
          '崩坏：星穹铁道｜画外遗光｜11月3日 10:00 ~ 11月17日 03:59' in text, True)
    check('无结束时间的活动显示「起」', '绝区零｜限时活动｜11月3日 12:00 起' in text, True)
    check('没有开始时间时显示「时间待定」', '崩坏：星穹铁道｜收尾活动｜时间待定' in text, True)
    check('当天没有活动时返回空文本', d['empty'], '')
    check('当天没有活动时有提示', '当天没有活动可复制' in (d['flashes'] or [''])[0], True)

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
