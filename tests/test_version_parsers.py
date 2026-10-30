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

# 过期守卫：公告于 2024-09-25 发布、活动在 2024-10 结束；运行时钟钉在 2026-09 时应被丢弃
EF_EXPIRED_TEXT = '''■ 全新活动
「往期活动」
· 活动时间：2024/09/26 12:00 - 2024/10/10 03:59
'''


def pub_of():
    return datetime(2024, 9, 25, 12, 0)


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
const mk = a => new Date(a[0], a[1] - 1, a[2], a[3], a[4]);
const ref = mk(inp.ref), late = mk(inp.now);
const conv = (r) => r.map(([n, c, s, e]) => [n, c, fmt(s), fmt(e)]);
// 过期过滤参考时刻也要能注入:不传 now 即运行时钟(与 Python 侧 now=None 同语义)
process.stdout.write(JSON.stringify({
  ef: conv(S.efExtractVersion(inp.ef, ref, late)),
  efStrict: conv(S.efExtractVersion(inp.efStrict, ref, late)),
  efExpired: conv(S.efExtractVersion(inp.efExpired, ref, late)),
  ananta: conv(S.anantaExtractVersion(inp.ananta, ref, late)),
  anEdge: conv(S.anantaExtractVersion(inp.anEdge, ref, late)),
}));
"""


def _fmt(d):
    return d.strftime('%Y-%m-%dT%H:%M:%S') if d else None


# fixture 用到的公告发布时刻与「过期过滤参考时刻」:显式注入,让用例不随系统日期变红
PUB = datetime(2026, 9, 20, 12, 0)
NOW = datetime(2026, 10, 6, 12, 0)       # 落在 fixture 区间内(10-06 ~ 10-24),条目全部有效
NOW_MID = datetime(2026, 10, 15, 0, 0)   # 边界内:环期赠礼(至 10-20)仍有效,限定S级祈愿(至 10-24)仍在
NOW_LATE = datetime(2028, 1, 1, 0, 0)    # 推到所有 fixture 区间之后,用于验证过期过滤

# 各参考时刻的绝对期望(只比对一端不够:两端一起错时对拍恒绿)
EXPECT_NOW = {'ef': [], 'efStrict': [], 'ananta': [], 'anEdge': []}
EXPECT_LATE = {'ef': [], 'efStrict': [], 'ananta': [], 'anEdge': [], 'efExpired': []}


def py_side(now=None):
    conv = lambda rs: [[n, c, _fmt(s), _fmt(e)] for n, c, s, e in rs]
    return {
        'ef': conv(scrapers._ef_extract_version(EF_TEXT, PUB, now)),
        'efStrict': conv(scrapers._ef_extract_version(EF_STRICT_TEXT, PUB, now)),
        'ananta': conv(scrapers._ananta_extract_version(AN_TEXT, PUB, now)),
        'anEdge': conv(scrapers._ananta_extract_version(AN_EDGE, PUB, now)),
        # main 的反向守卫：往期活动在任一参考时刻都必须被过滤掉（含运行时钟）
        'efExpired': conv(scrapers._ef_extract_version(EF_EXPIRED_TEXT, PUB, now)),
    }


def py_late(now=NOW_LATE):
    return py_side(now)


def js_side(script, now=NOW):
    inp = {'ref': [2026, 9, 20, 12, 0],
           'now': [now.year, now.month, now.day, now.hour, now.minute],
           'ef': EF_TEXT, 'efStrict': EF_STRICT_TEXT, 'efExpired': EF_EXPIRED_TEXT,
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
    mine = py_side(NOW)
    # 对照：严格写法下双端都必须解析出同一条完整区间（防止「两端一起挂」被当成一致）
    expect_ef_strict = [['雪淞幽梦', '活动', '2026-10-06T12:00:00', '2026-10-20T03:59:00']]
    if mine['efStrict'] != expect_ef_strict:
        bad += 1
        print('FAIL 严格写法解析异常 py = %s' % mine['efStrict'])
    expect_an = [['环期赠礼', '角色与专武', '2026-10-06T12:00:00', '2026-10-20T03:59:00']]
    if mine['ananta'] != expect_an:
        bad += 1
        print('FAIL 异环「月日写法」解析异常 py = %s' % mine['ananta'])
    if mine['efExpired'] != []:
        bad += 1
        print('FAIL 已结束活动未被运行时钟过滤 py = %s' % mine['efExpired'])
    expect_edge = [['活动乙', '活动', '2026-12-30T12:00:00', '2027-01-05T12:00:00']]
    if mine['anEdge'] != expect_edge:
        bad += 1
        print('FAIL 边界用例（2月30日 丢弃 + 跨年滚年）异常 py = %s' % mine['anEdge'])
    for script in SCRAPERS:
        theirs = js_side(script)
        if theirs is None:
            bad += 1
            continue
        for key in ('ef', 'efStrict', 'ananta', 'anEdge', 'efExpired'):
            if theirs[key] != mine[key]:
                bad += 1
                print('MISMATCH %s %s\n  py = %s\n  js = %s'
                      % (key, os.path.basename(script), mine[key], theirs[key]))
    # 过期过滤双端同口径：now 推到 fixture 区间之后，两端都必须清空（不是只有一端丢弃）
    late_py = py_side(NOW_LATE)
    for key in EXPECT_LATE:
        if late_py[key] != EXPECT_LATE[key]:
            bad += 1
            print('FAIL 过期后应为空 py %s = %s' % (key, late_py[key]))
    # 注入是否真被采用：边界内的参考时刻必须解析出条目（把 now 写死成运行时钟时这条会转红）
    mid_py = py_side(NOW_MID)
    if len(mid_py['ananta']) != 1:
        bad += 1
        print('FAIL 注入参考时刻未生效 py ananta = %s' % mid_py['ananta'])
    # 月日写法的年份只随公告走，不随参考时刻漂移
    if [r[2:] for r in mine['ef']] != [r[2:] for r in mid_py['ef']]:
        bad += 1
        print('FAIL 月日写法随参考时刻漂移 ef %s / %s' % (mine['ef'], mid_py['ef']))
    for script in SCRAPERS:
        late_js = js_side(script, NOW_LATE)
        if late_js is None:
            bad += 1
            continue
        for key in EXPECT_LATE:
            if late_js[key] != EXPECT_LATE[key] or late_js[key] != late_py[key]:
                bad += 1
                print('MISMATCH 过期过滤 %s %s\n  expect = %s\n  py = %s\n  js = %s'
                      % (key, os.path.basename(script), EXPECT_LATE[key], late_py[key], late_js[key]))
        mid_js = js_side(script, NOW_MID)
        if mid_js is None or len(mid_js['ananta']) != 1:
            bad += 1
            print('FAIL 注入参考时刻未生效 js %s mid ananta = %s'
                  % (os.path.basename(script), mid_js and mid_js['ananta']))
    print('用例 ef %d / efStrict %d / ananta %d / anEdge %d / efExpired %d，'
          '过期后 py %d/%d/%d/%d/%d，mismatch %d'
          % (len(mine['ef']), len(mine['efStrict']), len(mine['ananta']),
             len(mine['anEdge']), len(mine['efExpired']),
             len(late_py['ef']), len(late_py['efStrict']),
             len(late_py['ananta']), len(late_py['anEdge']), len(late_py['efExpired']), bad))
    print('ALL PASS' if bad == 0 else 'SOME FAILED')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
