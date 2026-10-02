# -*- coding: utf-8 -*-
"""手动条目校验双端一致性：data/manual.json 在 Python 与 scraper.js 下 kind 判定必须相同。

覆盖 Issue #4：Python 端曾在 fetch_all 内置校验、手动条目在 app 层才并入，导致
同一份手动数据「服务器模式保留、App 爬虫模式降级」。

运行：python3 tests/test_manual_parity.py
      （需要 node；node 缺失则 SKIP 并退出码 0）
"""
import json, os, shutil, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime

import scrapers

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANUAL = os.path.join(ROOT, 'data', 'manual.json')

# 与 app.py::_manual_events 相同的字段映射（手动条目统一读入后再校验）
NODE_LOADER = r"""
const fs = require('fs');
let src = fs.readFileSync(process.argv[2], 'utf8');
const S = new Function(src + '\nreturn Scraper;')();
global.localStorage = { getItem: (k) => (k === 'ycal_manual' ? process.argv[3] : null) };
const arr = JSON.parse(process.argv[3]);
const evs = S.manualEvents();
let dropped = 0;
// 与 fetchAll 的赋值语义一致：只有 kind==='event' 且校验不通过才降级
const rows = evs.map((e) => {
  const r = S.validateEvent(e);
  if (e.kind === 'event' && !r.valid) { e.kind = 'info'; e._reject = r.reason; dropped++; }
  return [e.game_id, e.title, e.kind, e._reject || ''];
});
console.log(JSON.stringify({ rows, dropped }));
"""


def _manual_source():
    return json.load(open(MANUAL, encoding='utf-8'))


def py_manual_events(arr=None):
    """按 app.py::_manual_events 的映射构造，并走统一的 validate_events。"""
    arr = _manual_source() if arr is None else arr
    names = {g['id']: g['name'] for g in scrapers.GAMES_META}
    out = []
    for i, e in enumerate(arr):
        if not isinstance(e, dict) or 'title' not in e:
            continue
        gid = e.get('game_id', '')
        start = e.get('start') or None
        out.append({
            'id': f'manual-{i}', 'game_id': gid, 'game': names.get(gid, e.get('game') or gid or '自定义'),
            'title': e.get('title', '未命名事件'), 'category': e.get('category', '活动'),
            'start': start, 'end': e.get('end') or None,
            'date': start or datetime.now().isoformat(timespec='seconds'),
            'link': e.get('link', ''), 'image': e.get('image', ''),
            'src': 'manual', 'kind': e.get('kind', 'event'),
        })
    dropped = scrapers.validate_events(out)
    rows = [[e['game_id'], e['title'], e['kind'], e.get('_reject', '')] for e in out]
    return rows, dropped


def js_manual_events(arr=None):
    text = open(MANUAL, encoding='utf-8').read() if arr is None else json.dumps(arr, ensure_ascii=False)
    p = subprocess.run(['node', '-e', NODE_LOADER, 'node',
                        os.path.join(ROOT, 'static', 'scraper.js'), text],
                       capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip() or 'node 退出码 %d' % p.returncode)
    data = json.loads(p.stdout.strip().splitlines()[-1])
    return data['rows'], data['dropped']


def app_side_kinds():
    """真正覆盖 app.py::do_refresh 的调用时机（离线：抓取与 B 站均返回空）。"""
    import app
    app.scrapers.fetch_all = lambda: ([], {})
    app.bilibili.fetch_all = lambda per_game=6: ([], {'name': 'B站动态', 'ok': True, 'count': 0})
    app._save_cache = lambda: None
    assert app.do_refresh() is True
    return {e['id']: (e['kind'], e.get('_reject', ''))
            for e in app._state['events'] if e.get('src') == 'manual'}


def main():
    if not shutil.which('node'):
        print('SKIP: 未找到 node，跳过手动条目双端一致性测试')
        return 0
    bad = 0
    py, py_dropped = py_manual_events()
    js, js_dropped = js_manual_events()
    if len(py) != len(js):
        print('MISMATCH 条数: py=%d js=%d' % (len(py), len(js)))
        bad += 1
    for a, b in zip(py, js):
        if a != b:
            bad += 1
            print('MISMATCH %s\n  py = %s\n  js = %s' % (a[1], a, b))
    if py_dropped != js_dropped:
        bad += 1
        print('MISMATCH 降级条数: py=%d js=%d' % (py_dropped, js_dropped))
    print('手动条目 %d 条，双端 mismatch %d，校验降级 %d 条'
          % (len(py), bad, py_dropped))

    # 数据里本就写死 kind:'info' 的条目，JS 侧不得被反推成 event
    with_kind, _ = py_manual_events(_manual_source() + [
        {'title': '人工确认的资讯条目', 'kind': 'info',
         'start': '2026-10-01T12:00', 'end': '2026-10-10T12:00'}])
    if with_kind[-1][2] != 'info':
        bad += 1
        print('MISMATCH 显式 kind=info 的条目被改写: %s' % (with_kind[-1],))

    # app.py::do_refresh 的调用时机回归保护（删掉那条调用即失败）
    kinds = app_side_kinds()
    for mid, want in (('manual-83', 'info'), ('manual-139', 'info'),
                      ('manual-140', 'info'), ('manual-141', 'info')):
        got = kinds.get(mid)
        if got != (want, '商城/网页活动不排期'):
            bad += 1
            print('MISMATCH do_refresh %s: got=%s want=%s' % (mid, got, (want, '商城/网页活动不排期')))
    print('do_refresh 手动条目 %d 条，降级 %d 条'
          % (len(kinds), sum(1 for v in kinds.values() if v[0] != 'event')))
    print('ALL PASS' if bad == 0 else 'SOME FAILED')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
