# -*- coding: utf-8 -*-
"""天数阈值取整语义双端一致性测试（覆盖 Issue #16）。

两端此前各用一套「天」的算法：Python 是 `(a - b).days`（朝负无穷截断的整数），
JS 是 `(a - b) / 864e5`（浮点）。于是「恰好 N 天 + 数小时」的边界条目会自动分叉：
Python 保留、JS 丢弃（反向的 `<= N` 同理反向分叉），用户看到 PC 有、App 没有。

本测试把阈值判定收敛到单一函数（Python `scrapers._day_diff` / JS `Scraper.dayDiff`），
用三层断言守住：
  1. 纯函数层：两端 dayDiff 在同一组边界输入上逐条相同；
  2. 判定层：每个阈值 × 边界，两端的「留/弃」结论一致，且断言旧的截断语义确实会在
     这些用例上分叉（证明测试真的能抓到本 Issue 的回归，而不是恒真）；
  3. 源码层：scrapers.py 与两份 scraper.js 里不再残留裸 `.days` / `/864e5` 阈值判定。

另含一组端到端断言（第 4 层）：把明日方舟列表页的发布时间钉在「恰好 60 天 ± 1 分钟」，
用桩替换网络后跑真实的 `scrapers._arknights` 与 `scraper.js::arknights`，断言两端**同留同弃**——
这正是 Issue #16 里「PC 有、App 没有」的用户可见表现。

运行：python3 tests/test_day_diff.py（需要 node；node 缺失则 SKIP 并退出码 0）
"""
import json
import math
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scrapers

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRAPERS = [os.path.join(ROOT, 'static', 'scraper.js'),
            os.path.join(ROOT, 'android', 'app', 'src', 'main', 'assets', 'www', 'scraper.js')]
PY_SRC = os.path.join(ROOT, 'scrapers.py')
REF = datetime(2026, 8, 3, 12, 0, 0)

# (标签, 天数, 分钟)：覆盖「恰好 N 天」「N 天 ± 1 分钟」——分钟偏移正是两端旧口径的分叉点
BOUNDARIES = [('%d天%+d分' % (d, m), d, m)
              for d in (14, 30, 60, 400, -10) for m in (-1, 0, 1)]

# 源码里的阈值与比较方向（与 8 处判定逐一对应）：
#   14/30/60/400 天 —— 「超期丢弃」；<= 30 天 —— 明日方舟详情页抓取预算；
#   < -10 天 —— 异环「早于公告发布日 = 跨年」，是唯一允许负偏移的一处
THRESHOLDS = [(14, '>'), (30, '>'), (60, '>'), (400, '>'), (30, '<='), (10, '<'), (-10, '<')]

NODE_LOADER = r"""
const fs = require('fs');
let src = fs.readFileSync(process.argv[2], 'utf8');
const S = new Function(src + '\nreturn Scraper;')();
const inp = JSON.parse(process.argv[3]);
process.stdout.write(JSON.stringify(inp.map((p) => S.dayDiff(new Date(p.a), new Date(p.b)))));
"""


def _cmp(val, thr, op):
    return val > thr if op == '>' else (val <= thr if op == '<=' else val < thr)


def _trunc(delta_days):
    """旧 Python 语义：timedelta.days 朝负无穷截断"""
    return math.floor(delta_days)


def js_day_diffs(pairs):
    inp = [{'a': a.isoformat(), 'b': b.isoformat()} for a, b in pairs]
    out = {}
    for script in SCRAPERS:
        p = subprocess.run(['node', '-e', NODE_LOADER, 'node', script,
                            json.dumps(inp, ensure_ascii=False)],
                           capture_output=True, text=True)
        if p.returncode != 0:
            raise RuntimeError('%s 加载失败: %s' % (os.path.basename(script), p.stderr.strip()[-200:]))
        out[os.path.basename(script) + '@' + os.path.basename(os.path.dirname(script))] = json.loads(p.stdout.strip())
    return out


def main():
    if not shutil.which('node'):
        print('SKIP: 未找到 node，跳过多端天数阈值测试')
        return 0
    bad = 0

    pairs = [(REF + timedelta(days=d, minutes=m), REF) for _, d, m in BOUNDARIES]
    py = [scrapers._day_diff(a, b) for a, b in pairs]

    # ── 1) 纯函数层 ──
    try:
        js_all = js_day_diffs(pairs)
    except RuntimeError as e:
        print('FAIL %s' % e)
        return 1
    for name, js in js_all.items():
        for (label, _, _), x, y in zip(BOUNDARIES, py, js):
            if abs(x - y) > 1e-9:
                bad += 1
                print('MISMATCH dayDiff %s [%s]: py=%r js=%r' % (label, name, x, y))
    print('1) dayDiff 边界 %d 组 × %d 份 scraper.js：逐条一致' % (len(BOUNDARIES), len(SCRAPERS)))

    # ── 2) 判定层：两端留/弃一致，且旧截断语义确实会分叉 ──
    divergence = 0
    for thr, op in THRESHOLDS:
        for i, (label, _, _) in enumerate(BOUNDARIES):
            keep_py = not _cmp(py[i], thr, op)
            for name, js in js_all.items():
                if keep_py != (not _cmp(js[i], thr, op)):
                    bad += 1
                    print('MISMATCH 阈值 %s%s 天 [%s]: py_keep=%s js_keep=%s'
                          % (op, thr, label, keep_py, not _cmp(js[i], thr, op)))
            if keep_py != (not _cmp(_trunc(py[i]), thr, op)):
                divergence += 1
    if divergence == 0:
        bad += 1
        print('FAIL 用例未能覆盖旧截断语义的分叉点（测试恒真，无法防回归）')
    print('2) 阈值 × 边界 %d 组：两端留/弃一致；其中 %d 组旧 `.days` 截断语义会判错'
          % (len(THRESHOLDS) * len(BOUNDARIES), divergence))

    # ── 3) 源码层：不留裸 .days / /864e5 阈值判定 ──
    py_src = open(PY_SRC, encoding='utf-8').read()
    hits = re.findall(r'\.days\b', py_src)
    if len(hits) != 1:      # 仅允许 _day_diff docstring 里那处说明
        bad += 1
        print('FAIL scrapers.py 残留 .days %d 处（应为 0 处代码 + 1 处注释）' % len(hits))
    else:
        print('3) scrapers.py 阈值均走 _day_diff()（无裸 .days 判定）')

    for script in SCRAPERS:
        src = open(script, encoding='utf-8').read()
        # 剔除 dayDiff 自身定义行；withTwoDayDefault 的 `+ 2 * 864e5` 是时长加法（非阈值比较），
        # 正则只匹配「比较运算符 + 天数 / 864e5」的形态，该处不会命中
        body = re.sub(r'const dayDiff = \(a, b\) => \(a - b\) / 864e5;', '', src)
        bare = re.findall(r'[<>]=? ?\d+(?:\.\d+)? ?/ 864e5', body)
        if bare:
            bad += 1
            print('FAIL %s 残留裸 /864e5 阈值判定: %s' % (os.path.basename(script), bare))
    print('  两份 scraper.js 阈值均走 dayDiff()')

    # ── 4) 端到端：明日方舟「近 60 天」过滤，两端同留同弃 ──
    bad += _filter_parity()

    print('ALL PASS' if bad == 0 else 'SOME FAILED')
    return 1 if bad else 0


# 明日方舟列表页桩：__next_f 里字段顺序固定 cid→title→displayTime
AK_LIST = ('<script>self.__next_f.push([1,"{\\"cid\\":\\"%s\\",\\"title\\":'
           '\\"【公开招募】标签强制刷新通知\\",\\"displayTime\\":%d}"])</script>')

NODE_FILTER = r"""
const fs = require('fs');
let src = fs.readFileSync(process.argv[2], 'utf8');
const S = new Function(src + '\nreturn Scraper;')();
const html = process.argv[3];
global.fetch = async () => new Response(html, { status: 200, headers: { 'Content-Type': 'text/html' } });
S.fetchAll().then((r) => {
  process.stdout.write(JSON.stringify(r.events.filter((e) => e.game_id === 'arknights').map((e) => e.title)));
}).catch((e) => { process.stdout.write('ERR ' + e.message); });
"""


def _py_arknights(cid, ts):
    """桩掉官网请求，只跑 _arknights 的过滤链路"""
    import scrapers as _s
    real = _s._get
    _s._get = lambda url, **kw: type('R', (), {'text': AK_LIST % (cid, ts)})()
    try:
        return [e['title'] for e in _s._arknights('arknights', '明日方舟')]
    finally:
        _s._get = real


def _filter_parity():
    """返回失败数：60 天边界（±1 分钟）两端条目集合必须一致"""
    bad = 0
    now = datetime.now()
    for label, offset_min in (('60天1分钟前', 60 * 1440 + 1), ('59天23小时59分前', 60 * 1440 - 1)):
        ts = int((now - timedelta(minutes=offset_min)).timestamp())
        cid = 'T%d' % offset_min
        html = AK_LIST % (cid, ts)
        py = _py_arknights(cid, ts)
        for script in SCRAPERS:
            p = subprocess.run(['node', '-e', NODE_FILTER, 'node', script, html],
                               capture_output=True, text=True)
            if p.returncode != 0 or p.stdout.startswith('ERR'):
                bad += 1
                print('FAIL [%s] js 侧执行失败: %s' % (label, (p.stderr or p.stdout).strip()[-200:]))
                continue
            js = json.loads(p.stdout)
            if py != js:
                bad += 1
                print('MISMATCH [%s] 条目集合: py=%r js=%r' % (label, py, js))
    if not bad:
        print('4) 端到端「近 60 天」过滤：60 天 ± 1 分钟两组，两端条目集合一致')
    return bad


if __name__ == '__main__':
    sys.exit(main())
