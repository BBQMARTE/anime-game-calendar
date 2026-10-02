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
console.log(JSON.stringify(evs.map((e) => {
  const r = S.validateEvent(e);
  return [e.game_id, e.title, r.valid ? 'event' : 'info', r.reason || ''];
})));
"""


def py_manual_events():
    """按 app.py::_manual_events 的映射构造，并走统一的 validate_events。"""
    arr = json.load(open(MANUAL, encoding='utf-8'))
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
    scrapers.validate_events(out)
    return [[e['game_id'], e['title'], e['kind'], e.get('_reject', '')] for e in out]


def js_manual_events():
    arr = open(MANUAL, encoding='utf-8').read()
    p = subprocess.run(['node', '-e', NODE_LOADER, 'node',
                        os.path.join(ROOT, 'static', 'scraper.js'), arr],
                       capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip() or 'node 退出码 %d' % p.returncode)
    return json.loads(p.stdout.strip().splitlines()[-1])


def main():
    if not shutil.which('node'):
        print('SKIP: 未找到 node，跳过手动条目双端一致性测试')
        return 0
    py, js = py_manual_events(), js_manual_events()
    bad = 0
    if len(py) != len(js):
        print('MISMATCH 条数: py=%d js=%d' % (len(py), len(js)))
        bad += 1
    for a, b in zip(py, js):
        if a != b:
            bad += 1
            print('MISMATCH %s\n  py = %s\n  js = %s' % (a[1], a, b))
    dropped = [r for r in py if r[2] != 'event']
    print('手动条目 %d 条，双端 mismatch %d，校验降级 %d 条' % (len(py), bad, len(dropped)))
    print('ALL PASS' if bad == 0 else 'SOME FAILED')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
