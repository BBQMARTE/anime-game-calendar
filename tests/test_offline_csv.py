# -*- coding: utf-8 -*-
"""离线 CSV 导出(csvCell / buildCsvText)测试。

APK 离线模式没有服务端,之前「导出 CSV」只能弹窗提示去连电脑。
现在用本地当前列表在前端生成同样字段的表格(带 BOM、逗号/引号正确转义、
收藏/已做完列与线上一致),离线也能把活动带走。

运行:python tests/test_offline_csv.py(node 缺失则 SKIP)
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
const FAV = {'hsr|活动, "限定"': 1, 'wuwa|无日期活动': -1};
const DONE = {'zzz|签到活动': 1};
const isFav = e => (FAV[(e.game_id || '') + '|' + (e.title || '')] || 0) > 0;
const isDone = e => (DONE[(e.game_id || '') + '|' + (e.title || '')] || 0) > 0;
const f = new Function('isFav', 'isDone', grab('csvCell') + '\n' + grab('buildCsvText')
  + '\nreturn {csvCell, buildCsvText};')(isFav, isDone);
const EVENTS = [
  {game_id:'hsr', game:'崩坏：星穹铁道', title:'活动, "限定"', category:'活动', kind:'event',
   start:'2026-11-01T10:00', end:'2026-11-10T03:59', src:'manual', link:'https://example.com/a?b=1,2'},
  {game_id:'zzz', game:'绝区零', title:'签到活动', category:'签到', kind:'event',
   start:'2026-10-30T10:00', src:'bilibili'},
  {game_id:'hsr', game:'崩坏：星穹铁道', title:'自动资讯', category:'资讯', kind:'info',
   date:'2026-10-20T10:00'},
  {game_id:'wuwa', game:'鸣潮', title:'无日期活动', category:'活动', kind:'event',
   _nodate:true, date:'2026-10-21T10:00'},
  {title:'手动无游戏', category:'活动', kind:'event', start:'2026-11-02T10:00', src:'manual'},
];
const text = f.buildCsvText(EVENTS);
console.log(JSON.stringify({
  bom: text.charCodeAt(0),
  text,
  empty: f.buildCsvText([]),
  cellPlain: f.csvCell('abc'),
  cellComma: f.csvCell('a,b'),
  cellQuote: f.csvCell('a"b'),
  cellNewline: f.csvCell('a\nb'),
  hasFn: src.includes('function buildCsvText('),
  hasDownload: src.includes('function downloadCsvFile(') && src.includes('new Blob('),
  offlineExport: src.includes("已导出 '+evs.length+' 条到 CSV(离线)"),
  offlineFav: src.includes("已导出 '+evs.length+' 条收藏到 CSV(离线)"),
  noOldAlert: !src.includes('离线模式无法导出 CSV'),
  settingsHint: src.includes('离线 APK 也能导出'),
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
    lines = text.split('\r\n')
    check('以 BOM 开头', d['bom'], 0xFEFF)
    check('表头与线上导出一致', lines[0].lstrip('\ufeff'), '游戏,标题,分类,开始,结束,类型,来源,链接,收藏,已做完')
    check('行尾 CRLF 且以换行结束', text.endswith('\r\n'), True)
    check('按开始时间升序(无 start 用 date)',
          [text.index(k) for k in ('自动资讯', '无日期活动', '签到活动', '"活动, ""限定"""', '手动无游戏')],
          sorted([text.index(k) for k in ('自动资讯', '无日期活动', '签到活动', '"活动, ""限定"""', '手动无游戏')]))
    check('逗号标题被引号包裹并可还原', '"活动, ""限定"""' in text, True)
    check('带逗号链接被包裹', '"https://example.com/a?b=1,2"' in text, True)
    check('人工来源标为已核实', '已核实' in text, True)
    check('B站来源标为 B站', 'B站' in text, True)
    check('资讯条目标为资讯', '资讯' in text, True)
    hsr = [ln for ln in lines if ln.startswith('崩坏') and '限定' in ln][0]
    check('收藏为是、未打钩为否', hsr.endswith('是,否'), True)
    zzz = [ln for ln in lines if ln.startswith('绝区零')][0]
    check('打钩条目在已做完列标是', zzz.endswith('否,是'), True)
    wuwa = [ln for ln in lines if ln.startswith('鸣潮')][0]
    check('取消收藏(墓碑值)不标是', wuwa, '鸣潮,无日期活动,活动,,,活动,自动,,否,否')
    check('空列表只有表头', d['empty'].strip('\ufeff\r\n'), '游戏,标题,分类,开始,结束,类型,来源,链接,收藏,已做完')
    check('简单值不额外加引号', d['cellPlain'], 'abc')
    check('逗号触发引号', d['cellComma'], '"a,b"')
    check('引号成对转义', d['cellQuote'], '"a""b"')
    check('换行同样被包裹', d['cellNewline'], '"a\nb"')
    check('离线构建函数已实现', d['hasFn'], True)
    check('下载用 Blob', d['hasDownload'], True)
    check('在线/离线导出均有轻提示', (d['offlineExport'], d['offlineFav']), (True, True))
    check('不再提示「离线模式无法导出 CSV」', d['noOldAlert'], True)
    check('设置里说明离线可导出', d['settingsHint'], True)

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
