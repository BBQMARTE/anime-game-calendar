# -*- coding: utf-8 -*-
"""CSV 导出查询串(filterQuery / exportSearch)测试。

导出要从「屏幕上看到的这个视图」出发:游戏/分类筛选、数据质量筛选、搜索词都带上。
搜索词只给 CSV(订阅链接不带关键词),快捷词(今天/本周…)是前端算的时间筛选,
服务端表达不了,导出时用轻提示说明,不能让用户以为导出漏了条目。

运行:python tests/test_export_query.py(node 缺失则 SKIP)
"""
import json
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
const body = [
  "const DATA={games:[{id:'hsr'},{id:'zzz'},{id:'wuwa'}]};",
  "const CAT_COLOR={'\u6d3b\u52a8':1,'\u7b7e\u5230':1,'\u8d44\u8baf':1};",
  "let activeCats=new Set(Object.keys(CAT_COLOR));",
  "const settings={calGames:null};",
  "let dq='', q='';",
  (src.match(/const QUICK_WORDS=\[[^\]]*\];/) || [''])[0],
  grab('calGamesSet'), grab('gamePrefix'), grab('isQuickWord'),
  grab('exportSearch'), grab('filterQuery'),
  "return {filterQuery,exportSearch,setQ:v=>{q=v},setDq:v=>{dq=v},setCats:v=>{activeCats=v}};"
].join('\n');
const f = new Function(body)();
const dec = (s) => s.split('&').map(p => decodeURIComponent(p)).join('&');
const out = (o) => ({ qs: dec(f.filterQuery(true)), ics: dec(f.filterQuery()) });
const r = {};
f.setQ(''); f.setDq('');
r.none = out({});
f.setQ('\u5d29\u94c1');                // 崩铁
r.keyword = out({});
f.setQ('\u7b7e\u5230 \u6d3b\u52a8');   // 签到 活动
r.terms = out({});
f.setQ('\u4eca\u5929');                // 今天(快捷词)
r.quick = { o: out({}), ex: f.exportSearch() };
f.setQ('zzz: \u4eca\u5929');            // zzz: 今天
r.prefixQuick = { o: out({}), ex: f.exportSearch() };
f.setQ('hsr: \u7b7e\u5230');            // hsr: 签到
r.prefix = out({});
f.setQ('\u7b7e\u5230'); f.setDq('noimg');
r.dq = out({});
f.setDq(''); f.setCats(new Set(['\u6d3b\u52a8']));
r.cats = out({});
console.log(JSON.stringify(r));
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

    check("无筛选时导出无查询串", d['none']['qs'], '')
    check("无搜索时订阅链接也不带关键词", d['none']['ics'], '')
    check("关键词写进 CSV 查询串", d['keyword']['qs'], '?q=崩铁')
    check("订阅链接不带搜索词", d['keyword']['ics'], '')
    check("多个关键词原样带上(服务端按 AND)", d['terms']['qs'], '?q=签到 活动')
    check("快捷词不写进查询串", d['quick']['o']['qs'], '')
    check("快捷词标记为无法导出", d['quick']['ex']['quick'], True)
    check("游戏前缀收窄 games 参数", d['prefixQuick']['o']['qs'], '?games=zzz')
    check("游戏前缀 + 快捷词只带游戏", d['prefixQuick']['ex']['quick'], True)
    check("游戏前缀 + 关键词两者都带", d['prefix']['qs'], '?games=hsr&q=签到')
    check("质量筛选与关键词并存", d['dq']['qs'], '?dq=noimg&q=签到')
    check("分类筛选与关键词并存", d['cats']['qs'], '?cats=活动&q=签到')

    src = open(HTML, encoding='utf-8').read()
    check("导出用 exportSearch 判断快捷词", '_exportSearch' not in src and 'exportSearch().quick' in src, True)
    check("CSV 导出注释已说明搜索词", '当前搜索词 / 质量筛选也带进导出' in src, True)

    # 游戏简称表:前后端必须逐项一致,否则列表搜得到、导出搜不到
    import app  # noqa: E402 - 延迟导入,避免 node 缺失时也加载数据
    m = re.search(r'const GAME_SHORT=\{([^}]*)\};', src)
    if not m:
        check("前端存在 GAME_SHORT 表", False, True)
    else:
        pairs = dict(re.findall(r"([a-z0-9_]+):'([^']*)'", m.group(1)))
        check("前后端游戏简称一致", pairs, app._GAME_SHORT)

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
