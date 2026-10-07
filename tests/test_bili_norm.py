# -*- coding: utf-8 -*-
"""双端一致性测试：B站动态的标题/分类归一化（Issue #14）。

Python 侧 bilibili.fetch_all() 不走 scrapers._ev()，于是「折叠连续空白」与
「签到类分流」只在前端 ev() 里生效：同一条动态在 PC 端标题多空格、分类留在「活动」，
App 端已折叠并落到「签到」。打钩 key(doneKey = game_id|title)、去重 key、筛选器
随之分叉。

本测试复刻两端各自的链路（纯离线，不联网）：

  Python: bilibili.fetch_all()（_Client 换成固定 fixture）→ _title_of → _classify
          → scrapers.normalize_title_cat
  JS    : scraper.js::biliTitle → classify → ev()（ev() 内部做归一化）

另外单独对拍 bilibili._title_of() 与 scraper.js::biliTitle()：
边界 trim 字符集（全角逗号）、长度计数（UTF-16 码元 vs 码点）、
38 字截断（不切开代理对）必须逐字一致。

Python 侧直接调用真实的 fetch_all()，因此「bilibili 是否真的复用了归一化」也在覆盖内；
把 bilibili.py 里那行 normalize_title_cat 调用删掉，本测试即失败（可反向验证）。

运行：python3 tests/test_bili_norm.py
      （需要 node；node 缺失则 SKIP 并退出码 0）
"""
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bilibili
from bilibili import _title_of

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRAPERS = [os.path.join(ROOT, 'static', 'scraper.js'),
            os.path.join(ROOT, 'android', 'app', 'src', 'main', 'assets', 'www', 'scraper.js')]

# (clean 正文, 期望 title, 期望 category)
# 两端的 HOT/NOISE 词表各自判定，不由用例预置，避免「用例替代码兜底」
FIXTURES = [
    # Issue #14 现象 1：标题里的连续空白未折叠
    ('互动抽奖   狸了个大谱 | V4.6', '互动抽奖 狸了个大谱 | V4.6', '活动'),
    ('绝区零  2.2版本前瞻\t特别节目', '绝区零 2.2版本前瞻 特别节目', '活动'),
    ('互动抽奖   狸了个大谱\n第二行说明', '互动抽奖 狸了个大谱', '活动'),
    # Issue #14 现象 2：「签到」分类分流只在 App 端生效
    ('“锦枫映月——月饼烘焙小教程·五”限时签到活动',
     '“锦枫映月——月饼烘焙小教程·五”限时签到活动', '签到'),
    ('【夏日嘉年华】限时活动开启，每日签到领取奖励',
     '【夏日嘉年华】限时活动开启，每日签到领取奖励', '签到'),
    # 非签到类不应被误分流
    ('「星轨航程」  限时活动开启', '「星轨航程」 限时活动开启', '活动'),
    ('4.0版本「应门者」  特别前瞻节目（直播）',
     '4.0版本「应门者」 特别前瞻节目（直播）', '活动'),
    ('【维护公告】  9月10日停服更新', '【维护公告】 9月10日停服更新', '公告'),
    # Issue #14 现象 3：标题进入归一化之前就分叉（trim 字符集 / 长度口径 / 38 字截断）
    ('当鼓点与低音交织，\n第二行说明', '当鼓点与低音交织', '资讯'),
    ('，,。\n限时签到活动开启，每日登录领取奖励', '限时签到活动开启，每日登录领取奖励', '签到'),
    # 非 BMP 首行：码点长度 4、UTF-16 码元长度 8，两端都按码元 -> 不再补行（口径一致）
    ('😀😀😀😀\n限时签到活动开启，登录领取奖励', '😀😀😀😀', '活动'),
    ('短\n😀😀😀😀😀😀😀😀😀😀限时签到活动', '短 😀😀😀😀😀😀😀😀😀😀限时签到活动', '签到'),
]

# 标题归一化（bilibili._title_of vs scraper.js::biliTitle）对拍语料：
# trim 字符集、补行阈值（< 8）、38 字截断（按 UTF-16 码元，且不切开代理对）
TITLE_CORPUS = [
    '当鼓点与低音交织，\n第二行',
    '，,。\n正文',
    '，。 \n正文',
    ' 空格 开头\n第二行',
    '😀' * 20,
    '😀' * 19,
    '😀' * 19 + 'x',
    '😀' * 19 + 'x' * 5,
    '汉字' * 19,
    '短\n' + '😀' * 10 + '限时签到活动开启',
    'x' * 40,
]

# 在 scraper.js 自执行闭包内追加所需导出（其余导出保持原样）
NODE_LOADER = r"""
const fs = require('fs');
let src = fs.readFileSync(process.argv[2], 'utf8');
const anchor = 'return { GAMES, fetchAll,';
if (!src.includes(anchor)) throw new Error('scraper.js 导出锚点未找到: ' + anchor);
src = src.replace(anchor,
  'return { ev, classify, biliTitle, BILI_NOISE, BILI_HOT, GAMES, fetchAll,');
const S = new Function(src + '\nreturn Scraper;')();
const inp = JSON.parse(process.argv[3]);
const ref = new Date(2026, 7, 3, 12, 0, 0);
// 复刻 bilibiliAll() 里对单条动态的处理顺序（HOT/NOISE 用 scraper.js 自己的词表）
const out = [];
for (const clean of inp) {
  const title = S.biliTitle(clean);
  if (!title) continue;  // 与 bilibili.py 的 `if not title: continue` 对齐
  const hot = S.BILI_HOT.test(clean);
  if (S.BILI_NOISE.test(title) && !hot) continue;
  const e = S.ev('r1999', '重返未来：1999', title, S.classify(title, hot ? '活动' : '资讯'),
                 ref, null, null, '', '', 'info');
  out.push([e.title, e.category]);
}
process.stdout.write(JSON.stringify(out));
"""

NODE_TITLE_LOADER = r"""
const fs = require('fs');
let src = fs.readFileSync(process.argv[2], 'utf8');
const anchor = 'return { GAMES, fetchAll,';
if (!src.includes(anchor)) throw new Error('scraper.js 导出锚点未找到: ' + anchor);
src = src.replace(anchor, 'return { biliTitle, GAMES, fetchAll,');
const S = new Function(src + '\nreturn Scraper;')();
const inp = JSON.parse(process.argv[3]);
process.stdout.write(JSON.stringify(inp.map((s) => S.biliTitle(s))));
"""


class _FakeClient:
    """不联网的 _Client：把 fixture 原样喂给 fetch_all()"""

    def __init__(self, items):
        self.items = items

    def time_map(self, uid):
        return {it['opus_id']: 1784982000 + i for i, it in enumerate(self.items)}

    def opus_feed(self, uid, n=6):
        return self.items


def py_side(fixtures):
    """跑真实的 bilibili.fetch_all()，返回 [(title, category)]"""
    items = [{'opus_id': str(9000 + i), 'content': clean, 'cover': {'url': ''}, 'jump_url': ''}
             for i, clean in enumerate(fixtures)]
    saved = (bilibili._Client, bilibili.GAME_UIDS, bilibili.time.sleep)
    bilibili._Client = lambda: _FakeClient(items)
    bilibili.GAME_UIDS = [('r1999', '重返未来：1999', 1197454103)]
    bilibili.time.sleep = lambda *_a: None
    try:
        evs, _status = bilibili.fetch_all(per_game=len(items))
    finally:
        bilibili._Client, bilibili.GAME_UIDS, bilibili.time.sleep = saved
    return [[e['title'], e['category']] for e in evs]


def main():
    if not shutil.which('node'):
        print('SKIP: 未找到 node，跳过 B站归一化双端测试')
        return 0

    inp = [clean for clean, _, _ in FIXTURES]
    bad = 0
    mine = py_side(inp)
    if len(mine) != len(FIXTURES):
        print('FAIL fetch_all() 返回 %d 条，期望 %d 条（fixture 是否被噪声/空标题过滤？）'
              % (len(mine), len(FIXTURES)))
        return 1

    for i, (title, cat) in enumerate(mine):
        exp_t, exp_c = FIXTURES[i][1], FIXTURES[i][2]
        if title != exp_t or cat != exp_c:
            bad += 1
            print('FAIL py[%d] %r\n  期望 = (%r, %r)\n  实际 = (%r, %r)'
                  % (i, FIXTURES[i][0], exp_t, exp_c, title, cat))

    exp_titles = [_title_of(c) for c in TITLE_CORPUS]

    for script in SCRAPERS:
        rel = os.path.relpath(script, ROOT)

        p = subprocess.run(['node', '-e', NODE_LOADER, 'node', script,
                            json.dumps(inp, ensure_ascii=False)],
                           capture_output=True, text=True)
        if p.returncode != 0:
            bad += 1
            print('FAIL js 侧无法加载 %s: %s'
                  % (rel, (p.stderr.strip().splitlines() or [''])[-1]))
        else:
            theirs = json.loads(p.stdout.strip(), strict=False)
            # 先断言条目数：zip() 会静默吞掉条目数差
            if len(mine) != len(theirs):
                bad += 1
                print('FAIL %s 条目数不一致: py %d / js %d' % (rel, len(mine), len(theirs)))
            else:
                n = 0
                for i, (a, b) in enumerate(zip(mine, theirs)):
                    if a != b:
                        bad += 1
                        n += 1
                        print('MISMATCH[%d] %r\n  py = %s\n  js = %s'
                              % (i, FIXTURES[i][0], a, b))
                print('%s 归一化对比 %d 条，mismatch %d' % (rel, len(mine), n))

        # 标题归一化（trim 字符集 / UTF-16 长度口径 / 38 字截断）逐条对拍
        q = subprocess.run(['node', '-e', NODE_TITLE_LOADER, 'node', script,
                            json.dumps(TITLE_CORPUS, ensure_ascii=False)],
                           capture_output=True, text=True)
        if q.returncode != 0:
            bad += 1
            print('FAIL js 侧 biliTitle 无法加载 %s: %s'
                  % (rel, (q.stderr.strip().splitlines() or [''])[-1]))
            continue
        js_titles = json.loads(q.stdout.strip())
        if len(js_titles) != len(exp_titles):
            bad += 1
            print('FAIL %s biliTitle 条数不一致: py %d / js %d'
                  % (rel, len(exp_titles), len(js_titles)))
            continue
        n = 0
        for i in range(len(exp_titles)):
            if exp_titles[i] != js_titles[i]:
                bad += 1
                n += 1
                print('TITLE MISMATCH[%d] %r\n  py = %r\n  js = %r'
                      % (i, TITLE_CORPUS[i], exp_titles[i], js_titles[i]))
        print('%s biliTitle 对比 %d 条，mismatch %d' % (rel, len(exp_titles), n))

    print('用例 %d 条，mismatch %d' % (len(FIXTURES), bad))
    print('ALL PASS' if bad == 0 else 'SOME FAILED')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
