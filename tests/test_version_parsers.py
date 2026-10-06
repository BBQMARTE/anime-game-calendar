# -*- coding: utf-8 -*-
"""版本说明解析器双端一致性测试（Issue #10）。

scrapers.py 的 _ef_extract_version / _ananta_extract_version 与 static/scraper.js
的 efExtractVersion / anantaExtractVersion 是声明上的同构副本，但 JS 端曾多一层
findDateTokens 兜底并按时间升序重排，而 Python 端只认严格正则、保持文档顺序——
于是「月日写法 + 取样窗口截断」时会双端分叉（JS 产出不存在的开始日、Python 漏条目）。

本测试用固定文本 fixture 离线比对两端：(名称, 分类, start, end) 必须逐字段相同。
运行：python3 tests/test_version_parsers.py（需要 node；node 缺失则 SKIP 退出码 0）
"""
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime

import scrapers

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRAPERS = [os.path.join(ROOT, 'static', 'scraper.js'),
            os.path.join(ROOT, 'android', 'app', 'src', 'main', 'assets', 'www', 'scraper.js')]

# 复现文本：窗口截断 + 升序重排曾在 JS 侧产出 2026-10-01T16:00Z（= 北京时间 10月2日）
EF_TEXT = '''■ 全新活动
「雪淞幽梦」
· 活动时间：10月6日 12:00 ~ 10月20日 03:59
'''

AN_TEXT = '''一、版本更新公告
     「环期赠礼」
     活动时间：10月6日 12:00 ~ 10月20日 03:59
     「限定S级祈愿」
     活动时间：10月10日 12:00 ~ 10月24日 03:59
'''

# 严格写法（yyyy/mm/dd hh:mm）应双端照常解析，作为「不是靠删兜底换一致」的对照
EF_STRICT_TEXT = '''■ 全新活动
「雪淞幽梦」
· 活动时间：2026/10/06 12:00 - 2026/10/20 03:59
'''

# 边界：不存在的日期（2月30日）应双端一起丢弃；跨年区间应双端同样滚年
AN_EDGE = '''一、版本更新公告
● 「活动甲」
活动时间：2月30日 12:00 ~ 3月5日 12:00
● 「活动乙」
活动时间：12月30日 12:00 ~ 1月5日 12:00
'''

NODE_LOADER = r"""
const fs = require('fs');
let src = fs.readFileSync(process.argv[2], 'utf8');
const anchor = 'return { GAMES, fetchAll,';
if (!src.includes(anchor)) throw new Error('scraper.js 导出锚点未找到: ' + anchor);
src = src.replace(anchor, 'return { efExtractVersion, anantaExtractVersion, GAMES, fetchAll,');
const S = new Function(src + '\nreturn Scraper;')();
const p = n => String(n).padStart(2, '0');
const fmt = d => d ? `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
  + `T${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}` : null;
const inp = JSON.parse(process.argv[3]);
const ref = new Date(inp.ref[0], inp.ref[1] - 1, inp.ref[2], inp.ref[3], inp.ref[4]);
const conv = (r) => r.map(([n, c, s, e]) => [n, c, fmt(s), fmt(e)]);
process.stdout.write(JSON.stringify({
  ef: conv(S.efExtractVersion(inp.ef, ref)),
  efStrict: conv(S.efExtractVersion(inp.efStrict, ref)),
  ananta: conv(S.anantaExtractVersion(inp.ananta, ref)),
  anEdge: conv(S.anantaExtractVersion(inp.anEdge, ref)),
}));
"""


def _fmt(d):
    return d.strftime('%Y-%m-%dT%H:%M:%S') if d else None


def py_side():
    pub = datetime(2026, 9, 20, 12, 0)
    conv = lambda rs: [[n, c, _fmt(s), _fmt(e)] for n, c, s, e in rs]
    return {
        'ef': conv(scrapers._ef_extract_version(EF_TEXT, pub)),
        'efStrict': conv(scrapers._ef_extract_version(EF_STRICT_TEXT, pub)),
        'ananta': conv(scrapers._ananta_extract_version(AN_TEXT, pub)),
        'anEdge': conv(scrapers._ananta_extract_version(AN_EDGE, pub)),
    }


def js_side(script):
    inp = {'ref': [2026, 9, 20, 12, 0], 'ef': EF_TEXT, 'efStrict': EF_STRICT_TEXT,
           'ananta': AN_TEXT, 'anEdge': AN_EDGE}
    p = subprocess.run(['node', '-e', NODE_LOADER, 'node', script, json.dumps(inp, ensure_ascii=False)],
                       capture_output=True, text=True)
    if p.returncode != 0:
        err = (p.stderr.strip().splitlines() or [''])[-1]
        print('MISMATCH js 侧无法加载 %s: %s' % (os.path.basename(script), err))
        return None
    return json.loads(p.stdout.strip(), strict=False)


def main():
    if not shutil.which('node'):
        print('SKIP: 未找到 node，跳过双端一致性测试')
        return 0
    bad = 0
    mine = py_side()
    # 对照：严格写法下双端都必须解析出同一条完整区间（防止「两端一起挂」被当成一致）
    expect_ef_strict = [['雪淞幽梦', '活动', '2026-10-06T12:00:00', '2026-10-20T03:59:00']]
    if mine['efStrict'] != expect_ef_strict:
        bad += 1
        print('FAIL 严格写法解析异常 py = %s' % mine['efStrict'])
    expect_an = [['环期赠礼', '角色与专武', '2026-10-06T12:00:00', '2026-10-20T03:59:00']]
    if mine['ananta'] != expect_an:
        bad += 1
        print('FAIL 异环「月日写法」解析异常 py = %s' % mine['ananta'])
    expect_edge = [['活动乙', '活动', '2026-12-30T12:00:00', '2027-01-05T12:00:00']]
    if mine['anEdge'] != expect_edge:
        bad += 1
        print('FAIL 边界用例（2月30日 丢弃 + 跨年滚年）异常 py = %s' % mine['anEdge'])
    for script in SCRAPERS:
        theirs = js_side(script)
        if theirs is None:
            bad += 1
            continue
        for key in ('ef', 'efStrict', 'ananta', 'anEdge'):
            if theirs[key] != mine[key]:
                bad += 1
                print('MISMATCH %s %s\n  py = %s\n  js = %s'
                      % (key, os.path.basename(script), mine[key], theirs[key]))
    print('用例 ef %d / efStrict %d / ananta %d / anEdge %d，mismatch %d'
          % (len(mine['ef']), len(mine['efStrict']), len(mine['ananta']),
             len(mine['anEdge']), bad))
    print('ALL PASS' if bad == 0 else 'SOME FAILED')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
