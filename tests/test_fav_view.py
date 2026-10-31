# -*- coding: utf-8 -*-
"""「收藏」页签排序、分组与过滤测试。

收藏此前只能在各个列表里置顶,没有独立入口;新增「收藏」页签后,
排序口径为:进行中(先结束的在前) → 即将开始(最近的在前) → 已结束/时间未知;
现在页内再按这三类分组显示小标题,收藏多了也能一眼分开。

运行:python3 tests/test_fav_view.py(node 缺失则 SKIP)
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
const src = (fs.readFileSync(0, 'utf8').match(/<script>[\s\S]*?<\/script>/g) || [])
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
const EVENTS = __EVENTS__;
const FAV = new Set(__FAV__);
const fn = new Function('evStart', 'evEnd', 'isFav',
  grab('favRank') + '\n' + grab('favEvents') + '\nreturn {favEvents,favRank};');
const api = fn(e => new Date(e.start), e => (e.end ? new Date(e.end) : null), e => FAV.has(e.id));
const now = new Date('2026-10-31T12:00:00+08:00');
const arr = api.favEvents(EVENTS, now);
const ranks = EVENTS.map(e => [e.id, api.favRank(e, now)]);
const grpFn = new Function('evStart', 'evEnd', 'favRank', grab('favGroups') + '\nreturn favGroups;')(
  e => new Date(e.start), e => (e.end ? new Date(e.end) : null), api.favRank);
const grp = grpFn(arr, now);
// favList:收藏页不受顶部筛选影响,只受「设置里隐藏的游戏 / 隐藏已完成」影响
const DATA2 = {events: __EVENTS2__};
const FAV2 = new Set(__FAV2__);
const fl = new Function('DATA', 'settings', 'calVisible', 'isDone', 'isFav',
  grab('favList') + '\nreturn favList;')(
  DATA2, {hideDone: true}, e => e.game_id !== 'wuwa', e => e.id === 'c', e => FAV2.has(e.id));
console.log(JSON.stringify({ ids: arr.map(e => e.id), ranks,
  groups: {live: grp.live.map(e => e.id), upcoming: grp.upcoming.map(e => e.id), past: grp.past.map(e => e.id)},
  favList: fl().map(e => e.id) }));
"""

EV = [
    {'id': 'a', 'start': '2026-10-30T12:00', 'end': '2026-11-03T12:00'},
    {'id': 'b', 'start': '2026-10-28T12:00', 'end': '2026-11-01T12:00'},
    {'id': 'c', 'start': '2026-11-02T12:00', 'end': '2026-11-09T12:00'},
    {'id': 'd', 'start': '2026-10-01T12:00', 'end': '2026-10-20T12:00'},
    {'id': 'e', 'start': '2026-10-05T12:00'},
    {'id': 'f', 'start': '2026-10-31T12:00', 'end': '2026-11-05T12:00'},
]
FAV = ['a', 'b', 'c', 'd', 'e']

# 收藏页数据源用例:c 已完成、d 在设置里被隐藏游戏、e 未收藏
EV2 = [
    {'id': 'a', 'game_id': 'hsr', 'title': 'A', 'start': '2026-10-30T12:00', 'end': '2026-11-03T12:00'},
    {'id': 'b', 'game_id': 'zzz', 'title': 'B', 'start': '2026-10-28T12:00', 'end': '2026-11-01T12:00'},
    {'id': 'c', 'game_id': 'hsr', 'title': 'C', 'start': '2026-10-01T12:00', 'end': '2026-10-20T12:00'},
    {'id': 'd', 'game_id': 'wuwa', 'title': 'D', 'start': '2026-10-31T12:00', 'end': '2026-11-05T12:00'},
    {'id': 'e', 'game_id': 'hsr', 'title': 'E', 'start': '2026-10-31T12:00', 'end': '2026-11-05T12:00'},
]
FAV2 = ['a', 'b', 'c', 'd']

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
        print('SKIP: 未找到 node,跳过收藏视图测试')
        return 0
    html = open(HTML, encoding='utf-8').read()
    loader = (LOADER.replace('__EVENTS__', json.dumps(EV, ensure_ascii=False))
              .replace('__FAV__', json.dumps(FAV, ensure_ascii=False))
              .replace('__EVENTS2__', json.dumps(EV2, ensure_ascii=False))
              .replace('__FAV2__', json.dumps(FAV2, ensure_ascii=False)))
    r = subprocess.run([node, '-e', loader], input=html, capture_output=True,
                       text=True, encoding='utf-8', timeout=60)
    if r.returncode != 0:
        print('FAIL: node 执行失败\n' + r.stderr[:600])
        return 1
    got = json.loads(r.stdout.strip().splitlines()[-1])
    check('只列出收藏条目', 'f' in got['ids'], False)
    check('排序:进行中(先结束)→ 即将开始 → 已结束 → 时间未知',
          got['ids'], ['b', 'a', 'e', 'c', 'd'])
    check('收藏页按三类分组', got['groups'],
          {'live': ['b', 'a', 'e'], 'upcoming': ['c'], 'past': ['d']})
    check('分组口径(0 进行中 / 1 即将开始 / 2 已结束 / 3 无开始时间)',
          got['ranks'], [['a', 0], ['b', 0], ['c', 1], ['d', 2], ['e', 0], ['f', 0]])
    check('页面有「即将开始」分组标题', '即将开始 · ' in html, True)
    check('页面有「已结束 / 时间未知」分组标题', '已结束 / 时间未知 · ' in html, True)
    check('页签按钮存在', 'data-tab="fav"' in html, True)
    check('收藏页不受顶部筛选影响,但过滤隐藏游戏与已完成', got['favList'], ['a', 'b'])

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
