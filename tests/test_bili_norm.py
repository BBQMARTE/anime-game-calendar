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
from scrapers import _classify, normalize_title_cat

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
const out = inp.map((clean) => {
  const title = S.biliTitle(clean);
  const hot = S.BILI_HOT.test(clean);
  if (S.BILI_NOISE.test(title) && !hot) return null;
  const e = S.ev('r1999', '重返未来：1999', title, S.classify(title, hot ? '活动' : '资讯'),
                 ref, null, null, '', '', 'info');
  return [e.title, e.category];
}).filter(Boolean);
process.stdout.write(JSON.stringify(out));
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

    for script in SCRAPERS:
        p = subprocess.run(['node', '-e', NODE_LOADER, 'node', script,
                            json.dumps(inp, ensure_ascii=False)],
                           capture_output=True, text=True)
        if p.returncode != 0:
            bad += 1
            print('FAIL js 侧无法加载 %s: %s'
                  % (os.path.basename(script), (p.stderr.strip().splitlines() or [''])[-1]))
            continue
        theirs = json.loads(p.stdout.strip(), strict=False)
        for i, (a, b) in enumerate(zip(mine, theirs)):
            if a != b:
                bad += 1
                print('MISMATCH[%d] %r\n  py = %s\n  js = %s'
                      % (i, FIXTURES[i][0], a, b))
        print('%s 对比 %d 条，mismatch %d'
              % (os.path.relpath(script, ROOT), len(FIXTURES),
                 sum(1 for a, b in zip(mine, theirs) if a != b)))

    print('用例 %d 条，mismatch %d' % (len(FIXTURES), bad))
    print('ALL PASS' if bad == 0 else 'SOME FAILED')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
