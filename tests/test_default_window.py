# -*- coding: utf-8 -*-
"""缺结束时间的默认窗口口径统一守门（覆盖 Issue #34）。

Issue #13 把手动条目的零时长修掉后，默认窗口仍有两处口径：
抓取条目 `scrapers._ev()` → `timeparse.with_two_day_default` 补 **2 天**，
手动条目 ICS 端 `app._default_end()` 与前端 `evEnd()` 补 **当天 23:59:59**。
同一份数据在「抓取」与「手动兜底」两条道上结束时间不同（2 天 vs 当天末），
PC 与 App 对同类活动的持续时长展示随之分叉。

本测试固化单一口径「起点 + 2 天」，覆盖四条道：
  1) 抓取：`scrapers._ev()` 无 end → 起点 + 2 天
  2) 手动 ICS：`app._default_end()` → 起点 + 2 天（且与 1 同值）
  3) 前端：`evEnd()`（PC / App 同源码）→ 与 2 同值
  4) 越界：起点在 9999 年时四条道都放弃结束时间、不抛异常
反向验证：把任一条改回「当天 23:59:59」或「2 天」以外的口径，本测试即 FAIL。

运行：python3 tests/test_default_window.py
      （需要 flask；缺依赖则 SKIP 并退出码 0；前端断言需要 node，缺 node 则 SKIP 该组）
"""
import hashlib
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scrapers
import timeparse

try:
    import app
except ImportError as e:  # pragma: no cover - 缺依赖时不算失败
    print('SKIP: 无法导入 app（%s）' % e)
    sys.exit(0)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIRRORS = [os.path.join(ROOT, 'static', 'index.html'),
           os.path.join(ROOT, 'android', 'app', 'src', 'main', 'assets', 'www', 'index.html')]
SCRAPERS = [os.path.join(ROOT, 'static', 'scraper.js'),
            os.path.join(ROOT, 'android', 'app', 'src', 'main', 'assets', 'www', 'scraper.js')]
SW = [os.path.join(ROOT, 'static', 'sw.js'),
      os.path.join(ROOT, 'android', 'app', 'src', 'main', 'assets', 'www', 'sw.js')]
PUB = datetime(2026, 9, 19, 17, 0)

bad = 0


def check(label, got, expect):
    global bad
    ok = got == expect
    bad += 0 if ok else 1
    print("[%s] %s: got=%r expect=%r" % ('OK ' if ok else 'FAIL', label, got, expect))
    return ok


# ---- 1. 抓取道：_ev() 无 end → 起点 + 2 天 ----
start = datetime(2027, 9, 10, 12, 0)
e = scrapers._ev('g1', '测试', '「盛夏嘉年华」开启', '活动', PUB, start, None, '')
check('抓取条目 _ev() 无 end → 起点 + 2 天',
      (e['start'], e['end']), ('2027-09-10T12:00:00', '2027-09-12T12:00:00'))
check('抓取道与 timeparse.with_two_day_default 同值',
      e['end'],
      timeparse.with_two_day_default(start, None)[1].isoformat(timespec='seconds'))

# ---- 2. 手动 ICS 道：_default_end() → 与抓取道同值 ----
check('手动条目 ICS 端 _default_end() → 起点 + 2 天（与抓取道同值）',
      app._default_end('2027-09-10T12:00'), e['end'])
check('纯日期起点 _default_end() → + 2 天',
      app._default_end('2027-09-10'), '2027-09-12T00:00:00')
check('非法 / 空起点返回 None',
      (app._default_end(''), app._default_end(None)), (None, None))

# ---- 3. ICS 端到端：手动条目无 end 时 DTEND == 起点 + 2 天（非零时长、非当天末） ----
_ev = [{'id': 'manual-test0001', 'game_id': 'hsr', 'game': '崩坏：星穹铁道',
        'title': '缺结束时间的活动', 'category': '活动', 'kind': 'event',
        'start': '2027-09-10T12:00', 'end': None, 'date': '2026-09-01T12:00', 'link': ''}]
_real = app._state['events']
try:
    app._state['events'] = _ev
    ics = app.app.test_client().get('/api/calendar.ics').get_data(as_text=True)
finally:
    app._state['events'] = _real
m = re.search(r'DTSTART:(\S+)\r\nDTEND:(\S+)', ics)
check('ICS 产出 VEVENT', bool(m), True)
if m:
    # 北京时间 09-12 12:00 → UTC 09-12 04:00
    check('ICS DTEND = 起点 + 2 天（UTC）', m.group(2), '20270912T040000Z')

# ---- 4. 越界：起点在 9999 年时都放弃结束时间、不抛异常 ----
def _safe(fn):
    try:
        return fn()
    except Exception as ex:                                  # noqa: BLE001
        return 'EXC %s' % type(ex).__name__


check('抓取道 9999 年补窗越界 → 放弃结束时间',
      _safe(lambda: timeparse.with_two_day_default(datetime(9999, 12, 30), None)[1]), None)
check('手动道 9999 年补窗越界 → 放弃结束时间、不抛异常',
      _safe(lambda: app._default_end('9999-12-30T00:00')), None)

# ---- 5. 前端：evEnd() 与 ICS 同口径（PC / App 同一份源码） ----
check('两份 index.html md5 一致',
      hashlib.md5(open(MIRRORS[0], 'rb').read()).hexdigest(),
      hashlib.md5(open(MIRRORS[1], 'rb').read()).hexdigest())

NODE = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');
const m = /function evStart\(e\)\{[^\n]*\}[\r\n]+function evEnd\(e\)\{[^\n]*\}/.exec(src);
if (!m) { console.error('evStart/evEnd not found'); process.exit(2); }
eval(m[0] + '\nglobalThis.evStart=evStart;globalThis.evEnd=evEnd;');
const pad = (n) => String(n).padStart(2, '0');
const fmt = (d) => d ? `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}` : null;
const cases = JSON.parse(process.argv[3]);
// 返回 [evEnd, evStart + 2 天]：断言 evEnd 恰为起点 + 2 天（不掺日期串解析差异）
console.log(JSON.stringify(cases.map((c) => {
  const s = evStart(c), t = evEnd(c);
  const plus2 = s ? new Date(s.getFullYear(), s.getMonth(), s.getDate() + 2, s.getHours(), s.getMinutes(), s.getSeconds()) : null;
  return [fmt(t), fmt(plus2)];
})));
"""
if not shutil.which('node'):
    print('SKIP: 未找到 node，跳过前端 evEnd() 对照')
else:
    cases = [{'start': '2027-09-10T12:00', 'end': None, 'date': '2027-09-10T12:00'},
             {'start': '2027-09-10', 'end': None, 'date': '2027-09-10'}]
    p = subprocess.run(['node', '-e', NODE, 'node', MIRRORS[0], __import__('json').dumps(cases)],
                       capture_output=True, text=True)
    if p.returncode != 0:
        bad += 1
        print('FAIL: node 退出码 %d: %s' % (p.returncode, p.stderr.strip()[:300]))
    else:
        import json
        got = json.loads(p.stdout.strip().splitlines()[-1])
        check('前端 evEnd() 无 end → 起点 + 2 天', got[0][0], '2027-09-12T12:00:00')
        check('前端 evEnd() = evStart() + 2 天（带时分）', got[0][0], got[0][1])
        check('前端 evEnd() = evStart() + 2 天（纯日期）', got[1][0], got[1][1])
        check('前端 evEnd() 与后端 _default_end() 同口径（带时分）',
              got[0][0], app._default_end('2027-09-10T12:00'))

# ---- 6. 源码层：不留「当天 23:59:59」旧口径；两份 scraper.js md5 一致；SW 已递增 ----
for f in MIRRORS:
    s = open(f, encoding='utf-8').read()
    check('%s::evEnd 不再硬编码当天末' % os.path.basename(os.path.dirname(f)),
          '23,59,59' in s, False)
h = {f: hashlib.md5(open(f, 'rb').read()).hexdigest() for f in SCRAPERS}
check('两份 scraper.js md5 一致', len(set(h.values())), 1)
v = set()
for f in SW:
    s = open(f, encoding='utf-8').read()
    m = re.search(r"const CACHE = 'ycal-v(\d+)'", s)
    v.add(m.group(1) if m else None)
check('两份 sw.js CACHE 版本一致且不为空', len(v) == 1 and None not in v, True)
check('sw.js CACHE 已递增到 v37+（本次前端改动需失效旧缓存）',
      int(list(v)[0] or 0) >= 37, True)

print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
sys.exit(1 if bad else 0)
