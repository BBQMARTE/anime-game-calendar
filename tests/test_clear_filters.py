# -*- coding: utf-8 -*-
"""空结果「清除搜索与筛选」出口测试。

筛选把列表筛空时,原来的「暂无数据」会让人以为数据坏了;现在区分三种空状态,
筛选导致的空结果给出可点的「清除搜索与筛选」。

运行:python3 tests/test_clear_filters.py(node 缺失则 SKIP)
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
const code = [grab('filtersActive'), grab('clearFilters')].join('\n');
const DATA = {games: [{id:'hsr'}, {id:'zzz'}, {id:'wuwa'}], events: [{}]};
const CAT_COLOR = {'活动':1, '签到':2, '公告':3};
function make(qv, games, cats) {
  let q = qv;
  const activeGames = games, activeCats = cats;
  return new Function('q','activeGames','activeCats','DATA','CAT_COLOR','saveFilters','render','$',
    code + '\nreturn {filtersActive,clearFilters,getQ:()=>q,getGames:()=>activeGames,getCats:()=>activeCats};')
    (q, activeGames, activeCats, DATA, CAT_COLOR, () => {}, () => {}, () => ({value:''}));
}
const none = make('', new Set(['hsr','zzz','wuwa']), new Set(['活动','签到','公告']));
const qOnly = make('今天', new Set(['hsr','zzz','wuwa']), new Set(['活动','签到','公告']));
const gameOff = make('', new Set(['hsr','zzz']), new Set(['活动','签到','公告']));
const catOff = make('', new Set(['hsr','zzz','wuwa']), new Set(['活动','签到']));
none.clearFilters();
console.log(JSON.stringify({
  none: none.filtersActive(),
  qOnly: qOnly.filtersActive(),
  gameOff: gameOff.filtersActive(),
  catOff: catOff.filtersActive(),
  clearedQ: none.getQ(),
  clearedGames: [...none.getGames()],
  clearedCats: [...none.getCats()],
  hasLink: html.includes('没有符合条件的活动') && html.includes('clearFilters();return false'),
  hasFn: html.includes('function clearFilters'),
  hasHideDone: html.includes('隐藏已完成的活动') && html.includes('function toggleHideDone'),
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
        print('SKIP: 未找到 node，跳过清除筛选测试')
        return 0
    r = subprocess.run([node, '-e', LOADER], input=open(HTML, encoding='utf-8').read(),
                       capture_output=True, text=True, encoding='utf-8', timeout=60)
    if r.returncode != 0:
        print('FAIL: node 执行失败\n' + r.stderr[:800])
        return 1
    d = json.loads(r.stdout.strip().splitlines()[-1])
    check("无筛选时不提示清理", d['none'], False)
    check("有搜索词时提示清理", d['qOnly'], True)
    check("勾掉部分游戏时提示清理", d['gameOff'], True)
    check("勾掉部分分类时提示清理", d['catOff'], True)
    check("清除后搜索词为空", d['clearedQ'], '')
    check("清除后游戏全选", d['clearedGames'], ['hsr', 'zzz', 'wuwa'])
    check("清除后分类全选", d['clearedCats'], ['活动', '签到', '公告'])
    check("空结果带「清除搜索与筛选」链接", d['hasLink'], True)
    check("clearFilters 已实现", d['hasFn'], True)
    check("设置含「隐藏已完成的活动」开关", d['hasHideDone'], True)

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
