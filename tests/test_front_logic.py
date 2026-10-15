# -*- coding: utf-8 -*-
"""前端纯函数单测：从 static/index.html 提取 isoWeek / esc / gameShort / tagText / doneKey，
用 node 执行断言（无需浏览器环境）。

运行：python3 tests/test_front_logic.py
      （需要 node；node 缺失则 SKIP 并退出码 0，与 test_dual_side 同模式）
"""
import json, os, shutil, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, 'static', 'index.html')

# node loader:提取函数源码(大括号平衡扫描),stub GAME_SHORT/DATA 后注入执行。
# index.html 经 stdin 传入(不依赖 -e 后的 argv 位置,node 各版本对 '--' 处理不一致);
# 函数无法经 JSON 序列化(stringify 会把 function 值整个丢掉),故在 node 内求值后再输出。
LOADER = r"""
const fs = require('fs');
const html = fs.readFileSync(0, 'utf8');
const blocks = html.match(/<script>[\s\S]*?<\/script>/g) || [];
const src = blocks.map(b => b.replace(/<\/?script>/g, '')).join('\n');
function grab(name) {
  const i = src.indexOf('function ' + name + '(');
  if (i < 0) throw new Error('function not found in index.html: ' + name);
  let depth = 0, started = false;
  for (let k = src.indexOf('{', i); k < src.length; k++) {
    if (src[k] === '{') { depth++; started = true; }
    else if (src[k] === '}') { depth--; if (started && !depth) return src.slice(i, k + 1); }
  }
  throw new Error('unbalanced braces: ' + name);
}
const GAME_SHORT = {hsr:'崩铁', zzz:'绝区零', endfield:'终末地', arknights:'方舟', wuwa:'鸣潮', ananta:'异环', r1999:'1999'};
const code = ['esc','tagText','gameName','gameShort','isoWeek','doneKey'].map(grab).join('\n');
const DATA = {games: [{id: 'zzz', name: '绝区零'}]};   // gameShort 兜底分支的 stub
const api = new Function('GAME_SHORT', 'DATA', code + '\nreturn {esc, tagText, gameName, gameShort, isoWeek, doneKey};')(GAME_SHORT, DATA);
const d = (y, m, dd) => new Date(y, m - 1, dd);
const out = {
  isoWeek: [api.isoWeek(d(2026, 10, 11)), api.isoWeek(d(2026, 10, 12)),
            api.isoWeek(d(2026, 1, 1)), api.isoWeek(d(2024, 12, 30))],
  esc: [api.esc('&<>"\''), api.esc(null), api.esc('崩坏:星穹铁道 3.8')],
  gameShort: [api.gameShort('hsr'), api.gameShort('r1999'), api.gameShort('zzz'),
              api.gameShort('xxx'), api.gameShort(null)],
  tagText: [api.tagText('活动'), api.tagText('签到'), api.tagText('公告'),
            api.tagText('B站'), api.tagText('自定义')],
  doneKey: [api.doneKey({game_id: 'zzz', title: '活动A'}), api.doneKey({title: '公告'})],
};
console.log(JSON.stringify(out));
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
        print('SKIP: 未找到 node，跳过前端逻辑单测')
        return 0
    out = subprocess.run([node, '-e', LOADER],
                         input=open(HTML, encoding='utf-8').read(),
                         capture_output=True, text=True, encoding='utf-8', timeout=60)
    if out.returncode != 0:
        print('FAIL: node 执行失败\n' + out.stderr[:800])
        return 1
    a = json.loads(out.stdout.strip().splitlines()[-1])

    # isoWeek:ISO-8601 周次(周一为始,跨年归属)
    check("2026-10-11(周日) 属 W41", a['isoWeek'][0], '2026-W41')
    check("2026-10-12(周一) 翻到 W42", a['isoWeek'][1], '2026-W42')
    check("2026-01-01(周四) 属 W01", a['isoWeek'][2], '2026-W01')
    check("2024-12-30(周一) 跨年归 2025-W01", a['isoWeek'][3], '2025-W01')

    # esc:XSS 转义
    check("esc 五元字符", a['esc'][0], '&amp;&lt;&gt;&quot;&#39;')
    check("esc None 兜底空串", a['esc'][1], '')
    check("esc 普通文本原样", a['esc'][2], '崩坏:星穹铁道 3.8')

    # gameShort:映射/兜底/无归属
    check("gameShort hsr→崩铁", a['gameShort'][0], '崩铁')
    check("gameShort r1999→1999", a['gameShort'][1], '1999')
    check("gameShort 映射表优先(zzz)", a['gameShort'][2], '绝区零')
    check("gameShort 完全未知取id前两字", a['gameShort'][3], 'xx')
    check("gameShort null→活动", a['gameShort'][4], '活动')

    # tagText:亮底深字/深底白字
    check("tagText 活动→深字", a['tagText'][0], '#0b3d20')
    check("tagText 签到(紫底)→白字", a['tagText'][1], '#fff')
    check("tagText 公告→深字", a['tagText'][2], '#4d2e00')
    check("tagText B站→深字", a['tagText'][3], '#4a0e2e')
    check("tagText 未知色→白字", a['tagText'][4], '#fff')

    # doneKey:收藏/打钩共用键口径
    check("doneKey 拼接口径", a['doneKey'][0], 'zzz|活动A')
    check("doneKey 无归属", a['doneKey'][1], '|公告')

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
