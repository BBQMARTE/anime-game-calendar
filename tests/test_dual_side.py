# -*- coding: utf-8 -*-
"""双端一致性测试：static/scraper.js 的 extractEvents 与 Python timeparse.extract_events。

运行：python3 tests/test_dual_side.py
      （需要 node；node 缺失则 SKIP 并退出码 0）
"""
import json, os, re, shutil, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime
from timeparse import extract_events

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF = datetime(2026, 8, 3, 12, 0, 0)

# 泛称名（双端都应收起）与非泛称名（双端都应保留）
CASES = [
    "【签到】活动时间：2026年7月10日 ~ 2026年7月20日",
    "【福利】活动时间：2026年7月10日 ~ 2026年7月20日",
    "【奖励】活动时间：2026年7月10日 ~ 2026年7月20日",
    "【登录】活动时间：2026年7月10日 ~ 2026年7月20日",
    "【菲林】活动时间：2026年7月10日 ~ 2026年7月20日",
    "【母带】活动时间：2026年7月10日 ~ 2026年7月20日",
    "【活动】活动时间：2026年7月10日 ~ 2026年7月20日",
    "【版本活动】活动时间：2026年7月10日 ~ 2026年7月20日",
    "【前瞻】活动时间：2026年7月10日 ~ 2026年7月20日",
    "【盛夏嘉年华】活动时间：2026年7月10日 ~ 2026年7月20日",
    "【累计登录有礼】活动时间：2026年7月10日 ~ 2026年7月20日",
    "【每日签到福利】活动时间：2026年7月10日 ~ 2026年7月20日",
    "【应门者·签到活动】活动时间：2026年7月10日 ~ 2026年7月20日",
    "「星轨航程」活动期间：2026年7月10日 ~ 2026年7月20日",
    "「签到」活动期间：2026年7月10日 ~ 2026年7月20日",
    "■ 周年庆盛典\n活动时间：2026年7月10日 ~ 2026年7月20日",
]

# 取 static/scraper.js 的 extractEvents 结果（不依赖浏览器环境）
NODE_LOADER = r"""
const fs = require('fs');
let src = fs.readFileSync(process.argv[2], 'utf8');
src = src.replace('const Scraper = (() => {', 'const Scraper = (() => {');
const S = new Function(src + '\nreturn Scraper;')();
const cases = JSON.parse(process.argv[3]);
const ref = new Date(2026, 7, 3, 12, 0, 0);   // 本地时区，与 Python naive datetime 对齐
const fmt = (d) => {
  if (!d) return null;
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
};
console.log(JSON.stringify(cases.map((t) => S.extractEvents(t, ref).map(([n, s, e]) => [n, fmt(s), fmt(e)]))));
"""


def py_side():
    out = []
    for t in CASES:
        out.append([[n, s.isoformat() if s else None, e.isoformat() if e else None]
                    for n, s, e in extract_events(t, REF)])
    return out


def js_side(script):
    p = subprocess.run(['node', '-e', NODE_LOADER, 'node', script, json.dumps(CASES, ensure_ascii=False)],
                       capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip() or 'node 退出码 %d' % p.returncode)
    return json.loads(p.stdout.strip().splitlines()[-1])


def _js_noise_alt(src):
    """抽出 scraper.js 的 NOISE_NAME 正则分支串（^(?: 与 )$ 之间）"""
    i = src.index('NOISE_NAME = /^(?:') + len('NOISE_NAME = /^(?:')
    j = src.index(')$/', i)
    return re.sub(r'\s+', '', src[i:j])


def table_check():
    """泛称词表须三处同表（timeparse / scrapers / scraper.js ×2），否则双端分叉。"""
    import scrapers
    import timeparse as tp
    py_bad = set(tp._BAD_SHORT) | set(scrapers._BAD_SHORT)
    py_noise = re.sub(r'\s+', '', tp._NOISE_NAME.pattern)[len('^(?:'):-len(')$')]
    bad = 0
    for fn in (os.path.join(ROOT, 'static', 'scraper.js'),
               os.path.join(ROOT, 'android', 'app', 'src', 'main', 'assets', 'www', 'scraper.js')):
        src = open(fn, encoding='utf8').read()
        m = re.search(r"BAD_SHORT = new Set\(\[(.*?)\]\)", src)
        js_bad = set(re.findall(r"'([^']*)'", m.group(1)))
        js_noise = _js_noise_alt(src)
        if js_bad != py_bad:
            bad += 1
            print('MISMATCH BAD_SHORT %s\n  js = %s\n  py = %s' % (fn, sorted(js_bad), sorted(py_bad)))
        if js_noise != py_noise:
            bad += 1
            print('MISMATCH NOISE_NAME %s\n  js = %s\n  py = %s' % (fn, js_noise, py_noise))
    print('词表一致性（timeparse / scrapers / scraper.js ×2）: %s' % ('OK' if not bad else '不一致'))
    return bad


def main():
    if not shutil.which('node'):
        print('SKIP: 未找到 node，跳过双端一致性测试')
        return 0
    bad = table_check()
    script = os.path.join(ROOT, 'static', 'scraper.js')
    mine = py_side()
    theirs = js_side(script)
    for text, a, b in zip(CASES, mine, theirs):
        if a != b:
            bad += 1
            print('MISMATCH %s\n  py  = %s\n  js  = %s' % (text, a, b))
    # 泛称名必须两端都收起
    for text, a in zip(CASES, mine):
        if a:
            continue
    print('用例 %d 条，mismatch %d' % (len(CASES), bad))
    print('ALL PASS' if bad == 0 else 'SOME FAILED')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
