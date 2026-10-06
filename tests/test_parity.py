# -*- coding: utf-8 -*-
"""双端一致性测试：Python 解析内核 vs static/scraper.js（App 端 WebView 同构副本）。

覆盖 Issue #5：static/scraper.js 自称是 timeparse.py 的「同构副本」，但 tests/ 里
没有任何测试加载 JS 端比对结果，过往 3 类分叉（无空格连字符区间、泛称名词表、
手动条目校验时机）只能靠临时脚本发现。

逐条比对 extract_range / extract_events / is_noise_name / validate_event 的输出，
任一条不一致即失败。用例全部为当前双端「应当一致」的形态；已知尚未收敛的分叉
（如非法日期 2月30日 的进位，见 Issue #9）不入本用例集，避免测试基线自相矛盾。

运行：python3 tests/test_parity.py
      （需要 node；node 缺失则 SKIP 并退出码 0）
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime

import scrapers
import timeparse as tp
from timeparse import with_two_day_default

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRAPERS = [os.path.join(ROOT, 'static', 'scraper.js'),
            os.path.join(ROOT, 'android', 'app', 'src', 'main', 'assets', 'www', 'scraper.js')]
REF = datetime(2026, 8, 3, 12, 0, 0)

# 区间/事件解析（Issue #2 类：无空格连字符、点日期、斜杠区间、分隔符两侧空白等）
RANGE_CASES = [
    '活动时间：9月10日-9月20日',
    '活动时间：2026年9月10日-2026年9月20日',
    '活动时间：09.10-09.20',
    '活动时间：7/10-7/20',
    '活动时间：9月10日 - 9月20日',
    '活动时间：9月10日 ~ 9月20日',
    '活动时间：9月10日～9月20日',
    '活动时间:8月10日 ~ 8月20日',
    '本次活动将于7月10日开启，至7月20日结束',
    '「盛夏嘉年华」活动期间：2026年7月10日 ~ 2026年7月20日',
    '「星轨航程」9月10日-9月20日 开启',
    '限时活动 8/1-8/31 上线',
    '掉落提升1.5-2.2倍，9月10日～9月20日',
    '活动时间：9月10日',
    '活动时间:8月15日~',
    '活动时间:~8月15日',
    '版本更新后~8月15日',
    # Issue #9：跨年越界与不存在日期（双端须同口径，任一端抛异常/自动进位即漂移）
    '活动时间：12月31日 ~ 2月29日',
    '限时活动 9999年12月30日 ~ 9999年2月28日',
    '活动时间：9998年12月30日 ~ 9998年2月28日',
    '活动时间：2026年2月29日 ~ 2026年3月5日',
    '活动时间：2026年4月31日 ~ 2026年5月10日',
    '活动时间：2月30日 10点至2026年3月21日 12时30分',
    '活动时间：0026-09-10 ~ 0026-09-20',
    '活动时间：0000-09-10 ~ 0000-09-20',
    '活动时间：2028年2月29日 ~ 2028年3月5日',
    '活动时间：2026年12月31日 ~ 2026年1月5日',
    # Issue #9 返工：TIME_RE 字符类与 Python _TIME 对齐（12:60 / 95:00 不再两端漂移）
    '活动时间：9月10日 12:60 ~ 9月20日 12:00',
    '活动时间：9月10日 95:00 ~ 9月20日 12:00',
    '活动时间：2026年7月10日 12:00 ~ 2026年8月10日 12:00',
]

# 序列化层（Issue #9 返工：iso() 年份补 4 位须与 Python isoformat 同口径）
ISO_DATES = ['0026-09-10', '9999-12-30', '2026-09-10', '1970-01-01']

# 补 2 天窗口（Issue #9 返工：9999 年起点 + 无结束时间时不得补出 10000 年）
WINDOW_DATES = ['9998-12-30', '9999-12-28', '9999-12-29', '9999-12-30', '9999-12-31', '2026-01-01']

# 泛称名过滤（Issue #3 类：双端 BAD_SHORT / NOISE_NAME 必须同表）
NAME_CASES = [
    '活动', '签到', '福利', '奖励', '登录', '菲林', '母带',
    '版本前瞻', '前瞻', '特别节目', '活动预告', '说明', '「星轨航程」',
    '盛夏嘉年华', '每日签到福利', '幸运签',
]

# 手动条目后置校验（Issue #4 类：同一条目双端 kind 判定必须相同）
VALIDATE_CASES = [
    {'kind': 'event', 'title': '「盛夏嘉年华」开启',
     'start': '2026-09-10T00:00', 'end': '2026-09-20T23:59'},
    {'kind': 'event', 'title': '版本前瞻',
     'start': '2026-09-10T00:00', 'end': '2026-09-20T23:59'},
    {'kind': 'event', 'title': '活动玩法说明',
     'start': '2026-09-10T00:00', 'end': '2026-09-20T23:59'},
    {'kind': 'event', 'title': '活动时间：9月10日', 'start': '2026-09-10T00:00', 'end': None},
    {'kind': 'event', 'title': '商城礼包上架',
     'start': '2026-09-10T00:00', 'end': '2026-09-20T23:59'},
    {'kind': 'event', 'title': '「盛夏嘉年华」开启',
     'start': '2026-09-10T00:00', 'end': '2026-09-10T01:00'},
    {'kind': 'info', 'title': '人工确认的资讯条目', 'start': None, 'end': None},
]

# 在 scraper.js 自执行闭包内追加 extractRange 导出（其余导出保持原样）
NODE_LOADER = r"""
const fs = require('fs');
let src = fs.readFileSync(process.argv[2], 'utf8');
const anchor = 'return { GAMES, fetchAll,';
if (!src.includes(anchor)) throw new Error('scraper.js 导出锚点未找到: ' + anchor);
src = src.replace(anchor, 'return { extractRange, withTwoDayDefault, iso, GAMES, fetchAll,');
const S = new Function(src + '\nreturn Scraper;')();
const inp = JSON.parse(process.argv[3]);
const ref = new Date(2026, 7, 3, 12, 0, 0);   // 本地时区，与 Python naive datetime 对齐
const p = (n) => String(n).padStart(2, '0');
const _day = (s) => { const [y, mo, d] = s.split('-').map(Number); const dt = new Date(0); dt.setFullYear(y, mo - 1, d); dt.setHours(0, 0, 0, 0); return dt; };
const fmt = (d) => d ? `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
  + `T${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}` : null;
const out = {
  ranges: inp.ranges.map((t) => { const [s, e] = S.extractRange(t, ref); return [fmt(s), fmt(e)]; }),
  events: inp.ranges.map((t) => S.extractEvents(t, ref).map(([n, s, e]) => [n, fmt(s), fmt(e)])),
  names: inp.names.map((n) => S.isNoiseName(n)),
  valids: inp.valids.map((e) => { const r = S.validateEvent(e); return [r.valid, r.reason]; }),
  dates: inp.dates.map((s) => S.iso(_day(s))),
  windows: inp.windows.map((s) => S.withTwoDayDefault(_day(s), null).map(S.iso)),
};
process.stdout.write(JSON.stringify(out));
"""


def _fmt(d):
    return d.strftime('%Y-%m-%dT%H:%M:%S') if d else None


def _iso(d):
    """与 scraper.js iso() 同口径：年份补 4 位（datetime.isoformat 天然如此）"""
    return d.isoformat(timespec='seconds') if d else None


def py_side(inp):
    out = {'ranges': [], 'events': [], 'names': [], 'valids': [], 'dates': [], 'windows': []}
    for t in inp['ranges']:
        s, e = tp.extract_range(t, REF)
        out['ranges'].append([_fmt(s), _fmt(e)])
        out['events'].append([[n, _fmt(s), _fmt(e)] for n, s, e in tp.extract_events(t, REF)])
    out['names'] = [tp.is_noise_name(n) for n in inp['names']]
    for e in inp['valids']:
        try:
            out['valids'].append(list(scrapers._validate_event(e)))
        except (TypeError, KeyError, AttributeError) as ex:   # 与 validateEvents 的容错口径一致
            out['valids'].append(['EXC', type(ex).__name__])

    def _day(s):
        y, mo, d = (int(x) for x in s.split('-'))
        return datetime(y, mo, d)
    out['dates'] = [_iso(_day(s)) for s in inp['dates']]
    def _win(s):
        try:
            return [_iso(x) for x in with_two_day_default(_day(s), None)]
        except OverflowError as ex:   # 返工前 9999 年起点会抛；报 MISMATCH 而不是中断整个测试
            return ['EXC', type(ex).__name__]
    out['windows'] = [_win(s) for s in inp['windows']]
    return out


def js_side(script, inp):
    """返回 JS 端结果；脚本本身加载不了（旧内核缺新导出）时返回 None 并打印原因。"""
    p = subprocess.run(['node', '-e', NODE_LOADER, 'node', script,
                        json.dumps(inp, ensure_ascii=False)],
                       capture_output=True, text=True)
    if p.returncode != 0:
        err = (p.stderr.strip().splitlines() or [''])[-1]
        print('MISMATCH js 侧无法加载 %s: %s' % (os.path.basename(script), err))
        return None
    return json.loads(p.stdout.strip(), strict=False)


def md5(path):
    return hashlib.md5(open(path, 'rb').read()).hexdigest()


def main():
    if not shutil.which('node'):
        print('SKIP: 未找到 node，跳过双端一致性测试')
        return 0
    bad = 0

    # 两份 scraper.js 必须逐字节一致（安卓镜像 = static 副本）
    h = [md5(f) for f in SCRAPERS]
    if len(set(h)) != 1:
        bad += 1
        print('MISMATCH scraper.js md5: %s' % dict(zip(SCRAPERS, h)))
    else:
        print('scraper.js ×2 md5 一致: %s' % h[0])

    inp = {'ranges': RANGE_CASES, 'names': NAME_CASES, 'valids': VALIDATE_CASES,
           'dates': ISO_DATES, 'windows': WINDOW_DATES}
    mine = py_side(inp)
    for script in SCRAPERS:
        theirs = js_side(script, inp)
        if theirs is None:          # 旧内核缺新导出(如 withTwoDayDefault/iso)，本组整体不可比
            bad += 1
            continue
        for key in ('ranges', 'events', 'names', 'valids', 'dates', 'windows'):
            for i, (a, b) in enumerate(zip(mine[key], theirs[key])):
                if a != b:
                    bad += 1
                    label = RANGE_CASES[i] if key in ('ranges', 'events') else i
                    print('MISMATCH %s[%s] %s\n  py = %s\n  js = %s'
                          % (key, label, os.path.basename(script), a, b))
    print('用例 range %d / name %d / validate %d / dates %d / windows %d，mismatch %d'
          % (len(RANGE_CASES), len(NAME_CASES), len(VALIDATE_CASES), len(ISO_DATES),
             len(WINDOW_DATES), bad))
    print('ALL PASS' if bad == 0 else 'SOME FAILED')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
