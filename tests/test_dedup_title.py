# -*- coding: utf-8 -*-
"""跨源同活动去重（app._norm_title/_dedup_against_manual）与公告碎片过滤
（scrapers.is_fragment_title）的守门（覆盖 Issue #53）。

这两段逻辑此前零用例：标题归一化口径或碎片规则一改，就可能静默把真活动丢掉
（归一化过宽 → 两条不同活动的标题互相包含 → 爬虫版被去重丢弃；
  碎片规则过宽 → 真活动名被当成正文碎片过滤）。
本测试用真实形态的样本锁定「该丢的丢、不该丢的留」，并校验前端镜像同口径。

运行：python3 tests/test_dedup_title.py
      （需要 flask；缺依赖则 SKIP 并退出码 0；前端断言需要 node，缺 node 则 SKIP 该组）
"""
import json
import os
import shutil
import subprocess
import tempfile
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scrapers

try:
    import app
except ImportError as e:  # pragma: no cover - 缺依赖时不算失败
    print('SKIP: 无法导入 app（%s）' % e)
    sys.exit(0)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIRRORS = [os.path.join(ROOT, 'static', 'scraper.js'),
           os.path.join(ROOT, 'android', 'app', 'src', 'main', 'assets', 'www', 'scraper.js')]
PAGE_MIRRORS = [os.path.join(ROOT, 'static', 'index.html'),
                os.path.join(ROOT, 'android', 'app', 'src', 'main', 'assets', 'www', 'index.html')]

FAIL = []


def ok(cond, name):
    print(('[OK]   ' if cond else '[FAIL] ') + name)
    if not cond:
        FAIL.append(name)


# ---- 1) 标题归一化：大小写/空白/标点/括号补充 不影响判定 ----
NORM_SAME = [
    ('影拓丰碑·深林呓语（新系列）', '影拓丰碑深林呓语'),
    ('「盛夏嘉年华」', '盛夏嘉年华'),
    ('Star Rail 特供', 'starrail特供'),
    ('【活动】7 日签到', '活动7日签到'),
]
for a, b in NORM_SAME:
    ok(app._norm_title(a) == app._norm_title(b), '归一化一致: %s == %s' % (a, b))

# 不同活动归一化后不应相等（避免互相包含误伤）
NORM_DIFF = [
    ('「星轨航程」限时活动', '「星轨航程」卡池'),
    ('盛夏嘉年华', '盛夏嘉年华签到'),
]
for a, b in NORM_DIFF:
    ok(app._norm_title(a) != app._norm_title(b), '归一化区分: %s != %s' % (a, b))


# ---- 2) 跨源去重：manual 版优先，且只在同游戏内生效 ----
class Ev(dict):
    """带内容稳定 id 的事件桩：dict 内容相同去重会被建库层合并，故补 _id 区分。"""
    _seq = 0

    def __init__(self, game_id, title, src):
        Ev._seq += 1
        super().__init__(game_id=game_id, game=game_id, title=title, src=src,
                         kind='event', start='2026-10-01T00:00:00', end=None, _id=Ev._seq)


def ev(title, gid, src):
    return Ev(gid, title, src)


CASES_DEDUP = [
    # (说明, 输入, 期望保留的 (title, src) 列表)
    ('爬虫简称与人工全名同活动时丢爬虫版',
     [ev('影拓丰碑·深林呓语（新系列）', 'ww', 'manual'), ev('影拓丰碑', 'ww', 'npc')],
     [('影拓丰碑·深林呓语（新系列）', 'manual')]),
    ('爬虫标题包含人工标题时同样丢爬虫版',
     [ev('影拓丰碑', 'ww', 'manual'), ev('影拓丰碑·深林呓语', 'ww', 'npc')],
     [('影拓丰碑', 'manual')]),
    ('不同游戏同标题不互相去重',
     [ev('盛夏嘉年华', 'sr', 'manual'), ev('盛夏嘉年华', 'zzz', 'npc')],
     [('盛夏嘉年华', 'manual'), ('盛夏嘉年华', 'npc')]),
    ('同游戏不同活动不误删',
     [ev('「星轨航程」限时活动', 'sr', 'manual'), ev('「星轨航程」卡池', 'sr', 'npc')],
     [('「星轨航程」限时活动', 'manual'), ('「星轨航程」卡池', 'npc')]),
    ('无人工条目时原样返回',
     [ev('盛夏嘉年华', 'sr', 'npc'), ev('星轨航程', 'sr', 'npc')],
     [('盛夏嘉年华', 'npc'), ('星轨航程', 'npc')]),
    ('单字标题不参与包含判定',
     [ev('「火」限时活动', 'sr', 'manual'), ev('火', 'sr', 'npc')],
     [('「火」限时活动', 'manual'), ('火', 'npc')]),
]

# 每组用各自的新副本：Ev 的 _id 只在同一批内保证唯一
def fresh(items):
    """每组独立副本：Ev 的 _id 仅在同批内唯一。"""
    return [Ev(i['game_id'], i['title'], i['src']) for i in items]


got = []
for _, items, _ in CASES_DEDUP:
    out = app._dedup_against_manual(fresh(items))
    got.append([(e['title'], e['src']) for e in out])
for (name, _, expect), out in zip(CASES_DEDUP, got):
    ok(out == expect, '去重: %s' % name)


# ---- 3) 公告碎片过滤：奖励清单/叙述句=碎片；真活动名=非碎片 ----
FRAGMENT_TRUE = [
    '【累计登录1天】:浮金波纹*5、特级调谐器*10',
    '本回合固定计入10笑点',
    '星际和平盛典:一镜到底 星际和平娱乐倾力打造的大',
    '爱，幽灵与机器人 一条废弃机铠管线经由幽灵斯科特',
]
FRAGMENT_FALSE = [
    '盛夏嘉年华',
    '「星轨航程」限时活动',
    '影拓丰碑·深林呓语（新系列）',
    '签到活动：7日签到',
]
for t in FRAGMENT_TRUE:
    ok(scrapers.is_fragment_title(t) is True, '碎片: %s' % t)
for t in FRAGMENT_FALSE:
    ok(scrapers.is_fragment_title(t) is False, '非碎片: %s' % t)
ok(scrapers.is_fragment_title('') is True, '碎片: 空标题')


# ---- 4) 双端同口径：两份 scraper.js 的 normTitle / isFragmentTitle 与 Python 一致 ----
NODE_PROBE = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');
// normTitle / isFragmentTitle 未从 Scraper 导出：连同其依赖常量一起从源码抽出求值
const pick = (name) => {
  const i = src.indexOf('function ' + name + '(');
  if (i < 0) return null;
  const deps = ['FRAGMENT_RE'].map((d) => {
    const k = src.indexOf('const ' + d + ' =');
    return k < 0 ? '' : src.slice(k, src.indexOf(';', k) + 1);
  }).join('\n');
  return new Function(deps + '\nreturn ' + src.slice(i, src.indexOf('\n  }', i) + 4))();
};
const FN_NORM = pick('normTitle') || (() => null);
const FN_FRAG = pick('isFragmentTitle') || (() => null);
const p = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
console.log(JSON.stringify({
  norm: p.norm.map(t => FN_NORM(t)),
  frag: p.frag.map(t => FN_FRAG(t)),
}));
"""


def probe_node():
    node = shutil.which('node')
    if not node:
        print('SKIP: 无 node，跳过双端口径断言')
        return
    payload = json.dumps({'norm': [a for a, _ in NORM_SAME] + [a for a, _ in NORM_DIFF],
                          'frag': FRAGMENT_TRUE + FRAGMENT_FALSE})
    py_norm = [app._norm_title(a) for a, _ in NORM_SAME] + [app._norm_title(a) for a, _ in NORM_DIFF]
    py_frag = [scrapers.is_fragment_title(t) for t in FRAGMENT_TRUE + FRAGMENT_FALSE]
    outs = []
    for f in MIRRORS:
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False, encoding='utf-8') as tf:
            tf.write(payload)
            pf = tf.name
        with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8') as sf:
            sf.write(NODE_PROBE)
            script = sf.name
        r = subprocess.run([node, script, f, pf], capture_output=True, text=True)
        os.unlink(script)
        os.unlink(pf)
        if r.returncode != 0:
            ok(False, 'node 加载失败')
            continue
        outs.append(json.loads(r.stdout))
    if not outs:
        return
    ok(outs[0]['norm'] == py_norm, 'JS normTitle 与 Python _norm_title 逐字一致')
    ok(outs[0]['frag'] == py_frag, 'JS isFragmentTitle 与 Python is_fragment_title 一致')
    ok(all(o == outs[0] for o in outs), '两份 scraper.js 结论一致（双端同构）')


probe_node()

print()
if FAIL:
    print('FAILED %d 项' % len(FAIL))
    sys.exit(1)
print('ALL PASS')
