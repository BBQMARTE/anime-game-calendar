# -*- coding: utf-8 -*-
"""手动条目校验双端一致性：data/manual.json 在 Python 与 scraper.js 下 kind 判定必须相同。

覆盖 Issue #4：Python 端曾在 fetch_all 内置校验、手动条目在 app 层才并入，导致
同一份手动数据「服务器模式保留、App 爬虫模式降级」。

运行：python3 tests/test_manual_parity.py
      （需要 flask + node；任一缺失则 SKIP 并退出码 0）
"""
import json, os, shutil, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scrapers

try:
    import app
except ImportError as e:  # pragma: no cover - 缺依赖时不算失败
    print('SKIP: 无法导入 app（%s）' % e)
    sys.exit(0)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANUAL = os.path.join(ROOT, 'data', 'manual.json')

# JS 侧按 scraper.js::manualEvents 同样的映射构造（手动条目统一读入后再校验）
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
    """直接调 app.py::_manual_events()（不手抄字段映射，避免与实现漂移），再走统一校验。"""
    if arr is None:
        out = app._manual_events()
    else:
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, 'manual.json'), 'w', encoding='utf-8') as f:
                json.dump(arr, f, ensure_ascii=False)
            real, app.DATA_DIR = app.DATA_DIR, d
            try:
                out = app._manual_events()
            finally:
                app.DATA_DIR = real
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
    # 条目 ID 自 #17 起由内容派生，按 title 取 ID，避免与下标绑定
    kinds = app_side_kinds()
    ids_by_title = {e['title']: e['id'] for e in app._manual_events()}
    for title in ('「维尔乌姆假日相册」网页活动',
                  '衣着上新「当宇宙潮涌」（远旅·不夜乌托邦系列）',
                  '衣着上新「释命运以弦音」（贝丽尔·不夜乌托邦系列）',
                  '衣着上新「虹色冠冕」（狩勋女巫红弩箭·二十一又一系列）'):
        got = kinds.get(ids_by_title.get(title, ''))
        if got != ('info', '商城/网页活动不排期'):
            bad += 1
            print('MISMATCH do_refresh %s: got=%s want=%s'
                  % (title, got, ('info', '商城/网页活动不排期')))
    print('do_refresh 手动条目 %d 条，降级 %d 条'
          % (len(kinds), sum(1 for v in kinds.values() if v[0] != 'event')))
    print('ALL PASS' if bad == 0 else 'SOME FAILED')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
