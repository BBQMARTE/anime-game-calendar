# -*- coding: utf-8 -*-
"""无日期条目不得伪造活动窗口（覆盖 Issue #25）。

`scrapers.py::_ev()` 曾在「没解析到开始时间」时用公告发布时间 `pub` 兜底填 start，
并据此补出 2 天窗口。后果有二：
  1. `_validate_event()` 规则 5（无起止时间需更强活动特征）永远进不去，长期空转；
  2. 真实数据里「未成年人游戏限时通知」这类非活动条目带上伪造的 2 天窗口进月历/ICS。

口径（两端一致）：无 start 时保持 None 并打 `_nodate`；前端显示「时间待定」、
`/api/calendar.ics` 不产出对应 VEVENT。

运行：python3 tests/test_ev_nodate.py
      （需要 flask；缺依赖则 SKIP 并退出码 0；前端断言需要 node，缺 node 则 SKIP 该组）
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scrapers

try:
    import app
except ImportError as e:  # pragma: no cover - 缺依赖时不算失败
    print('SKIP: 无法导入 app（%s）' % e)
    sys.exit(0)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRAPERS = [os.path.join(ROOT, 'static', 'scraper.js'),
            os.path.join(ROOT, 'android', 'app', 'src', 'main', 'assets', 'www', 'scraper.js')]
PUB = datetime(2026, 9, 19, 17, 0)

bad = 0


def check(label, got, expect):
    global bad
    ok = got == expect
    bad += 0 if ok else 1
    print("[%s] %s: got=%r expect=%r" % ('OK ' if ok else 'FAIL', label, got, expect))
    return ok


# ---- 1. _ev():无 start 时不得拿 pub 兜底 ----
e = scrapers._ev('arknights', '明日方舟', '《明日方舟》关于国庆节假期未成年人游戏限时通知',
                 '活动', PUB, None, None, 'https://ak.hypergryph.com/news/8578', '', 'event')
check('无 start 的条目 start 保持 None', e['start'], None)
check('无 start 的条目不得补出 end', e['end'], None)
check('pub 仍如实记录在 date', e['date'], PUB.isoformat())
check('标记 _nodate', e.get('_nodate'), True)

# ---- 2. 规则 5 恢复可达（校验对象是 _ev 产出的条目，title 已过 _short） ----
no_feature = scrapers._ev('arknights', '明日方舟', '账号数据迁移安排',
                          '活动', PUB, None, None, 'https://x', '', 'event')
check('无日期且无活动特征词 → 规则 5 降级',
      tuple(scrapers._validate_event(no_feature)), (False, '非官方来源且缺乏活动特征词'))
with_feature = scrapers._ev('arknights', '明日方舟', '限时双倍掉落开启',
                            '活动', PUB, None, None, 'https://x', '', 'event')
check('无日期但有活动特征词 → 规则 5 放行', tuple(scrapers._validate_event(with_feature)), (True, ''))

# ---- 3. 有 start 的条目行为不变（补 2 天窗口、跨年、9999 年界） ----
start = datetime(2026, 9, 10)
e2 = scrapers._ev('g1', '测试', '「盛夏嘉年华」开启', '活动', PUB, start, None, '')
check('有 start 仍补 2 天窗口', (e2['start'], e2['end']),
      ('2026-09-10T00:00:00', '2026-09-12T00:00:00'))
check('有 start 不打 _nodate', e2.get('_nodate'), None)
e3 = scrapers._ev('g1', '测试', '限时活动', '活动', datetime(9999, 1, 10), datetime(9999, 12, 30), None, '')
check('9999 年起点补窗不越界、不抛异常', (e3['start'], e3['end']), ('9999-12-30T00:00:00', None))

# ---- 4. ICS：无日期的 event 不产出 VEVENT ----
nodate_ev = {'id': 'arknights-deadbeef', 'game_id': 'arknights', 'game': '明日方舟',
             'title': '关于国庆节假期未成年人游戏限时通知', 'category': '活动',
             'kind': 'event', 'start': None, 'end': None, 'date': PUB.isoformat(),
             '_nodate': True, 'link': 'https://x'}
ok_ev = {'id': 'arknights-cafe0001', 'game_id': 'arknights', 'game': '明日方舟',
         'title': '「盛夏嘉年华」开启', 'category': '活动', 'kind': 'event',
         'start': '2026-09-10T12:00', 'end': '2026-09-12T12:00',
         'date': '2026-09-01T12:00', 'link': 'https://x'}
_real = app._state['events']
try:
    app._state['events'] = [nodate_ev, ok_ev]
    ics = app.app.test_client().get('/api/calendar.ics').get_data(as_text=True)
finally:
    app._state['events'] = _real
check('ICS 只为有 start 的条目产出 VEVENT', ics.count('BEGIN:VEVENT'), 1)
check('无日期条目不进 ICS', '未成年人游戏限时通知' in ics, False)
check('有日期条目仍在 ICS', '盛夏嘉年华' in ics, True)

# ---- 5. 前端：evStart() 对 _nodate 返回 null，fmtRange() 显示「时间待定」 ----
html = open(os.path.join(ROOT, 'static', 'index.html'), encoding='utf-8').read()
idx_apk = os.path.join(ROOT, 'android', 'app', 'src', 'main', 'assets', 'www', 'index.html')
check('index.html 与安卓镜像 md5 一致',
      hashlib.md5(html.encode('utf-8')).hexdigest()[:8],
      hashlib.md5(open(idx_apk, encoding='utf-8').read().encode('utf-8')).hexdigest()[:8])

NODE = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');
const grab = (name) => {
  const i = src.indexOf('function ' + name + '(');
  let depth = 0, started = false;
  for (let k = src.indexOf('{', i); k < src.length; k++) {
    if (src[k] === '{') { depth++; started = true; }
    else if (src[k] === '}') { depth--; if (started && !depth) return src.slice(i, k + 1); }
  }
  throw new Error('unbalanced: ' + name);
};
eval(grab('evStart') + '\n' + grab('evEnd') + '\n' + grab('fmtRange')
     + '\nglobalThis.evStart=evStart;globalThis.evEnd=evEnd;globalThis.fmtRange=fmtRange;');
const pad = (n) => String(n).padStart(2, '0');
const nodate = JSON.parse(process.argv[3]);
const ok = JSON.parse(process.argv[4]);
console.log(JSON.stringify({
  nodateStart: evStart(nodate), nodateEnd: evEnd(nodate), nodateFmt: fmtRange(nodate),
  okStart: evStart(ok) ? ok.start : null, okFmt: fmtRange(ok),
}));
"""
if not shutil.which('node'):
    print('SKIP: 未找到 node，跳过前端断言')
else:
    p = subprocess.run(['node', '-e', NODE, 'node', os.path.join(ROOT, 'static', 'index.html'),
                        json.dumps(nodate_ev, ensure_ascii=False), json.dumps(ok_ev, ensure_ascii=False)],
                       capture_output=True, text=True)
    if p.returncode != 0:
        bad += 1
        print('FAIL: node 退出码 %d: %s' % (p.returncode, p.stderr.strip()[:300]))
    else:
        js = json.loads(p.stdout.strip().splitlines()[-1])
        check('前端 evStart(_nodate) 为空', js['nodateStart'], None)
        check('前端 evStart 为空的条目 evEnd 也返回 null', js['nodateEnd'], None)
        check('前端 fmtRange(_nodate) 显示「时间待定」', js['nodateFmt'], '时间待定')
        check('前端有日期条目不受影响', js['okStart'], ok_ev['start'])

# ---- 6. 双端同构：两份 scraper.js 逐字节一致，且都有 _nodate ----
h = {f: hashlib.md5(open(f, 'rb').read()).hexdigest() for f in SCRAPERS}
check('两份 scraper.js md5 一致', len(set(h.values())), 1)
for f in SCRAPERS:
    src = open(f, encoding='utf-8').read()
    m = re.search(r'function ev\(gid[\s\S]*?\n  \}', src)
    seg = m.group(0) if m else ''
    check('%s::ev 不再用 pub 兜底' % os.path.basename(os.path.dirname(f)),
          'start || pub' in seg or 'if (!start) start = s' in seg, False)
    check('%s::ev 打 _nodate' % os.path.basename(os.path.dirname(f)), "o._nodate = true" in seg, True)

print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
sys.exit(1 if bad else 0)
