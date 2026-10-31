# -*- coding: utf-8 -*-
"""分享链接筛选参数测试(?games=&cats=&tab=)。

把当前筛选写进地址栏,发给别人打开就是同一个视图;离线 APK 走 file://,
syncUrl 会跳过 replaceState,不报 SecurityError。

运行:python tests/test_share_url.py(node 缺失则 SKIP)
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
const TAB_IDS = ['cal', 'ongoing', 'soon', 'all', 'fav'];
const fn = new Function('TAB_IDS', grab('parseFilterParams') + '\n' + grab('buildFilterQuery') +
  '\nreturn {p: parseFilterParams, b: buildFilterQuery};');
const f = fn(TAB_IDS);
const ALL_G = ['hsr', 'zzz', 'wuwa', 'arknights'];
const ALL_C = ['活动', '签到', '角色与专武', '公告', '资讯'];
const round = q => f.b(new Set(f.p(q).games || ALL_G), new Set(f.p(q).cats || ALL_C),
  f.p(q).tab || 'cal', ALL_G, ALL_C);
console.log(JSON.stringify({
  full: f.p('?games=hsr,zzz&cats=活动,签到&tab=ongoing'),
  spaces: f.p('?games=%20zzz%20,%20hsr'),
  badtab: f.p('?tab=bogus'),
  empty: f.p(''),
  emptyGames: f.p('?games='),
  search: f.p('?q=%E5%B4%A9%E9%93%81'),
  buildAll: f.b(new Set(ALL_G), new Set(ALL_C), 'cal', ALL_G, ALL_C),
  buildGames: f.b(new Set(['hsr']), new Set(ALL_C), 'cal', ALL_G, ALL_C),
  buildCats: f.b(new Set(ALL_G), new Set(['活动']), 'soon', ALL_G, ALL_C),
  buildBoth: f.b(new Set(['hsr', 'zzz']), new Set(['活动', '签到']), 'fav', ALL_G, ALL_C),
  buildSearch: f.b(new Set(ALL_G), new Set(ALL_C), 'cal', ALL_G, ALL_C, ' 崩铁 '),
  round1: round('?games=hsr&tab=all'),
  round2: round('?cats=活动,公告&tab=ongoing'),
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
        print('FAIL: node 执行失败\n' + r.stderr[:600])
        return 1
    d = json.loads(r.stdout.strip().splitlines()[-1])

    check('完整参数', d['full'], {'games': ['hsr', 'zzz'], 'cats': ['活动', '签到'],
                                  'tab': 'ongoing', 'q': None})
    check('空格与编码', d['spaces']['games'], ['zzz', 'hsr'])
    check('非法 tab 忽略', d['badtab']['tab'], None)
    check('无参数', d['empty'], {'games': None, 'cats': None, 'tab': None, 'q': None})
    check('games= 视为空列表', d['emptyGames']['games'], [])
    check('搜索词解码', d['search']['q'], '崩铁')

    check('全选 + 默认页签 → 干净地址', d['buildAll'], '')
    check('只选一个游戏', d['buildGames'], '?games=hsr')
    check('选部分分类 + 非默认页签', d['buildCats'], '?cats=%E6%B4%BB%E5%8A%A8&tab=soon')
    check('组合参数', d['buildBoth'],
          '?games=hsr%2Czzz&cats=%E6%B4%BB%E5%8A%A8%2C%E7%AD%BE%E5%88%B0&tab=fav')
    check('搜索词写进链接(去首尾空格)', d['buildSearch'], '?q=%E5%B4%A9%E9%93%81')

    check('解析→生成往返(单游戏)', d['round1'], '?games=hsr&tab=all')
    check('解析→生成往返(分类)', d['round2'],
          '?cats=%E6%B4%BB%E5%8A%A8%2C%E5%85%AC%E5%91%8A&tab=ongoing')

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
