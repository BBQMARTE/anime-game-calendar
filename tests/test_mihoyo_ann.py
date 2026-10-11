# -*- coding: utf-8 -*-
"""米哈游公告正文按 ann_id 精确匹配测试（覆盖 Issue #20）。

上游 getAnnContent 会忽略 ann_id 参数、把整个公告列表（每条自带 content）一起返回。
此前 `_mihoyo_content()` 与 JS `mihoyoContent()` 固定取 list[0]，导致：
- 所有米哈游详情弹窗显示同一篇无关公告；
- hsr 的版本说明拆解守卫 `'全新活动' in raw` 恒为假，拆解 0 条。

本脚本用假响应离线断言修复后的行为，并比对 Python / static/scraper.js 双端。
运行：python3 tests/test_mihoyo_ann.py
      （需要 flask/requests；JS 侧需要 node，缺则跳过该组，退出码 0）
"""
import io
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import scrapers
except ImportError as e:  # pragma: no cover - 缺依赖时不算失败
    print('SKIP: 无法导入 scrapers（%s）' % e)
    sys.exit(0)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BAD = 0


def check(label, got, expect):
    global BAD
    ok = got == expect
    BAD += 0 if ok else 1
    print('[%s] %s: got=%r expect=%r' % ('OK ' if ok else 'FAIL', label, got, expect))


# ---- 假响应：整个列表返回，list[0] 恒为无关公告（复现上游行为）----
LIST = [
    {'ann_id': 1421, 'content': '<p>货币战争•零和博弈 双倍晋升点</p>'},
    {'ann_id': 1414, 'content': '<p>挥掷千星的筹码 全新活动</p>'},
    {'ann_id': 1392, 'content': '<p>异器盈界 限时双倍</p>'},
]


class FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def fake_get(payload):
    def _get(url, **kw):
        return FakeResp(payload)
    return _get


DATA = {'data': {'list': LIST, 'total': len(LIST)}}

orig_get = scrapers._get
scrapers._get = fake_get(DATA)
try:
    # 命中：返回该条自身正文
    check('ann_id=1414 取到自身正文', scrapers._mihoyo_content('http://x/getAnnList', 'p=1', 1414),
          '<p>挥掷千星的筹码 全新活动</p>')
    check('ann_id=1421 取到自身正文', scrapers._mihoyo_content('http://x/getAnnList', 'p=1', 1421),
          '<p>货币战争•零和博弈 双倍晋升点</p>')
    check('ann_id 为字符串同样命中', scrapers._mihoyo_content('http://x/getAnnList', 'p=1', '1392'),
          '<p>异器盈界 限时双倍</p>')
    # 不命中：不得静默返回 list[0]（上游忽略参数时 list[0] 是别人的正文）
    check('ann_id=999999 不返回他人正文', scrapers._mihoyo_content('http://x/getAnnList', 'p=1', 999999), '')
    # 单条列表：接口确实只回一条时保持回退
    scrapers._get = fake_get({'data': {'list': [{'ann_id': 7, 'content': 'only'}]}})
    check('单条列表回退该条', scrapers._mihoyo_content('http://x/getAnnList', 'p=1', 1414), 'only')
    # 空列表：回退 data.content
    scrapers._get = fake_get({'data': {'list': [], 'content': 'top'}})
    check('空列表回退 data.content', scrapers._mihoyo_content('http://x/getAnnList', 'p=1', 1414), 'top')
    # 请求异常：不抛异常，返回空串
    scrapers._get = lambda url, **kw: (_ for _ in ()).throw(RuntimeError('boom'))
    check('请求异常返回空串', scrapers._mihoyo_content('http://x/getAnnList', 'p=1', 1414), '')
finally:
    scrapers._get = orig_get

# ---- JS 侧：stub fetch 后直接调 mihoyoContent，语义须与 Python 一致 ----
LOADER = r"""
const fs = require('fs');
let src = fs.readFileSync(process.argv[2], 'utf8');
const anchor = 'return { GAMES, fetchAll,';
if (!src.includes(anchor)) throw new Error('scraper.js 导出锚点未找到: ' + anchor);
src = src.replace(anchor, 'return { annPick, mihoyoContent, GAMES, fetchAll,');
const S = new Function(src + '\nreturn Scraper;')();
const LIST = JSON.parse(process.argv[3]);
const MISS = JSON.parse(process.argv[4]);
globalThis.fetch = async (url) => {
  const miss = /ann_id=(?:999999|1414)/.test(url) && MISS;
  return { ok: true, text: async () => JSON.stringify({ data: { list: miss ? [] : LIST, content: miss ? 'top' : undefined } }) };
};
(async () => {
  const out = {
    own: await S.mihoyoContent('http://x/getAnnList', 'p=1', 1414),
    other: await S.mihoyoContent('http://x/getAnnList', 'p=1', 1421),
    str: await S.mihoyoContent('http://x/getAnnList', 'p=1', '1392'),
    top: await S.mihoyoContent('http://x/getAnnList', 'p=1', 999999),
  };
  // 单条列表
  globalThis.fetch = async () => ({ ok: true, text: async () => JSON.stringify({ data: { list: [{ ann_id: 7, content: 'only' }] } }) });
  out.one = await S.mihoyoContent('http://x/getAnnList', 'p=1', 1414);
  process.stdout.write(JSON.stringify(out));
})();
"""


def main():
    if not shutil.which('node'):
        print('SKIP: 未找到 node，跳过 JS 侧比对')
        return BAD
    for js in ('static/scraper.js', 'android/app/src/main/assets/www/scraper.js'):
        p = subprocess.run(['node', '-e', LOADER, 'node', os.path.join(ROOT, js),
                            json.dumps(LIST), 'false'],
                           capture_output=True, text=True, timeout=60)
        if p.returncode != 0:
            check('%s 可加载' % js, (p.stderr or '').strip().splitlines()[-1:] or ['(no stderr)'], [])
            continue
        out = json.loads(p.stdout.strip(), strict=False)
        check('%s mihoyoContent 命中 ann_id' % js, out['own'], '<p>挥掷千星的筹码 全新活动</p>')
        check('%s mihoyoContent 另一条不同' % js, out['other'], '<p>货币战争•零和博弈 双倍晋升点</p>')
        check('%s mihoyoContent 字符串 ann_id' % js, out['str'], '<p>异器盈界 限时双倍</p>')
        check('%s mihoyoContent 不命中不返回他人正文' % js, out['top'], '')
        check('%s mihoyoContent 单条列表回退' % js, out['one'], 'only')
    return BAD


def front_side():
    """前端弹窗与双端镜像：docs 侧同样按 ann_id 匹配，且两处副本逐字节一致"""
    global BAD
    import hashlib
    import re
    pairs = [('static/index.html', 'android/app/src/main/assets/www/index.html'),
             ('static/scraper.js', 'android/app/src/main/assets/www/scraper.js'),
             ('static/sw.js', 'android/app/src/main/assets/www/sw.js')]
    for a, b in pairs:
        pa, pb = os.path.join(ROOT, a), os.path.join(ROOT, b)
        ha = hashlib.md5(open(pa, 'rb').read()).hexdigest()[:8]
        hb = hashlib.md5(open(pb, 'rb').read()).hexdigest()[:8]
        check('%s 与镜像 md5 一致' % os.path.basename(a), ha, hb)
    for f in ('static/index.html', 'android/app/src/main/assets/www/index.html'):
        html = io.open(os.path.join(ROOT, f), encoding='utf-8').read()
        seg = html[html.index('async function showMihoyoDetail'):]
        seg = seg[:seg.index('function renderView')]
        check('%s 详情弹窗按 ann_id 匹配' % os.path.basename(f), 'Scraper.annPick(lst,e.ann_id)' in seg, True)
        check('%s 详情弹窗不再裸取 list[0].content' % os.path.basename(f),
              re.search(r'lst\.length\?\(lst\[0\]\.content', seg) is None, True)
    for f in ('static/sw.js', 'android/app/src/main/assets/www/sw.js'):
        txt = io.open(os.path.join(ROOT, f), encoding='utf-8').read()
        m = re.search(r"const CACHE = 'ycal-v(\d+)'", txt)
        check('%s CACHE 已递增到 v33+' % os.path.basename(f), int(m.group(1)) >= 33, True)
    return BAD


BAD = front_side()
n = main()
print('\nALL PASS' if n == 0 else '\n%d FAILED' % n)
sys.exit(0 if n == 0 else 1)
