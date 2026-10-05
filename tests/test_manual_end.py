# -*- coding: utf-8 -*-
"""手动条目「无结束时间」口径统一测试（覆盖 Issue #13）。

data/manual.json 的条目不走 scrapers._ev()，此前 end 为空时三个消费方各解释一次：
README 说补 2 天、前端按当天 23:59、ICS 输出零时长（DTEND==DTSTART，违反 RFC5545）。
统一口径为「起点当天 23:59:59」，但只在**消费点**兜底（api_ics() 与前端 evEnd()）——
在读取入口补合成 end 会进 validate_events 的时长校验，深夜条目被判「时长过短」降级。

运行：python3 tests/test_manual_end.py
      （需要 flask；缺依赖则 SKIP 并退出码 0；前端断言需要 node，缺 node 则 SKIP 该组）
"""
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import app
except ImportError as e:  # pragma: no cover - 缺依赖时不算失败
    print('SKIP: 无法导入 app（%s）' % e)
    sys.exit(0)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANUAL = os.path.join(ROOT, 'data', 'manual.json')

bad = 0


def check(label, got, expect):
    global bad
    ok = got == expect
    bad += 0 if ok else 1
    print("[%s] %s: got=%r expect=%r" % ('OK ' if ok else 'FAIL', label, got, expect))
    return ok


def no_end_count():
    arr = json.load(open(MANUAL, encoding='utf-8'))
    return sum(1 for e in arr if isinstance(e, dict) and e.get('title')
               and e.get('start') and not e.get('end'))


# ---- 1. _default_end 口径：起点当天 23:59:59 ----
check('带时分起点补到当天 23:59:59',
      app._default_end('2026-09-25T12:00'), '2026-09-25T23:59:59')
check('纯日期起点补到当天 23:59:59',
      app._default_end('2026-09-25'), '2026-09-25T23:59:59')
check('非法起点返回 None', app._default_end(''), None)
check('None 起点返回 None', app._default_end(None), None)

# ---- 2. _manual_events 不补 end，ICS 端兜底后无零时长 ----
events = app._manual_events()
ne = [e for e in events if e['start'] and not e['end']]
check('manual.json 无 end 条目数 > 0（样本有效）', no_end_count() > 0, True)
# 读取入口必须保持 end=None：补合成值会让深夜条目被时长校验降级
check('_manual_events 不补 end（与 manual.json 一致）', len(ne), no_end_count())

app._state['events'] = events
raw = app.app.test_client().get('/api/calendar.ics').get_data(as_text=True)
pairs = re.findall(r'DTSTART:(\S+)\r\nDTEND:(\S+)', raw)
check('ICS DTEND==DTSTART 事件数为 0', len([p for p in pairs if p[0] == p[1]]), 0)
check('ICS VEVENT 数 > 0', raw.count('BEGIN:VEVENT') > 0, True)
# 有显式 end 的条目必须与 data/manual.json 原始值一致（不是拿自己比自己）
raw_end = {}
for e in json.load(open(MANUAL, encoding='utf-8')):
    if isinstance(e, dict) and e.get('title') and e.get('end'):
        raw_end[e['title']] = e['end']
exp = next(e for e in events if e['end'] and e['title'] in raw_end)
check('有 end 的条目未被改写', exp['end'], raw_end[exp['title']])

# ---- 2.5 起点晚于 22:00 的条目不得被降级（入口补合成 end 会触发时长下限） ----
import scrapers  # noqa: E402
import tempfile  # noqa: E402

_late = [{'title': '深夜首播', 'game_id': 'hsr', 'start': '2026-09-25T22:30', 'end': ''}]
with tempfile.TemporaryDirectory() as d:
    with open(os.path.join(d, 'manual.json'), 'w', encoding='utf-8') as f:
        json.dump(_late, f, ensure_ascii=False)
    real, app.DATA_DIR = app.DATA_DIR, d
    try:
        got = app._manual_events()
    finally:
        app.DATA_DIR = real
scrapers.validate_events(got)
check('22:30 起点条目仍为 kind=event', (got[0]['kind'], got[0].get('_reject', '')), ('event', ''))

# ---- 3. 前端 evEnd() 与 ICS 同口径 ----
NODE = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');
const m = /function evStart\(e\)\{[^\n]*\}[\r\n]+function evEnd\(e\)\{[^\n]*\}/.exec(src);
if (!m) { console.error('evStart/evEnd not found'); process.exit(2); }
eval(m[0] + '\nglobalThis.evStart=evStart;globalThis.evEnd=evEnd;');
const e = JSON.parse(process.argv[3]);
const s = evStart(e), t = evEnd(e);
const fmt = d => `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}T${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}:${String(d.getSeconds()).padStart(2,'0')}`;
console.log(JSON.stringify({ start: s && fmt(s), end: t && fmt(t) }));
"""

if not shutil.which('node'):
    print('SKIP: 未找到 node，跳过前端 evEnd() 对照')
else:
    e = {'start': '2026-09-25T12:00', 'end': None, 'date': '2026-09-25T12:00'}
    p = subprocess.run(['node', '-e', NODE, 'node',
                        os.path.join(ROOT, 'static', 'index.html'), json.dumps(e)],
                       capture_output=True, text=True)
    if p.returncode != 0:
        print('FAIL: node 退出码 %d: %s' % (p.returncode, p.stderr.strip()))
        bad += 1
    else:
        js = json.loads(p.stdout.strip().splitlines()[-1])
        check('前端 evEnd 无 end → 当天 23:59:59',
              js['end'], app._default_end('2026-09-25T12:00'))

print('ALL PASS' if bad == 0 else 'SOME FAILED')
sys.exit(1 if bad else 0)
