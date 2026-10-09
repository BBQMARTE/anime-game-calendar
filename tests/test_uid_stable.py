# -*- coding: utf-8 -*-
"""手动条目 UID 稳定性测试（覆盖 Issue #17）。

ICS 的 UID 此前取数组下标（manual-<i>），而 data/manual.json 是每日补录/重排的文件，
插入或删除一条就会让旧 UID 落到另一条活动上（RFC5545 §3.8.4.7 要求 UID 在事件
生命周期内持久稳定），订阅端表现为重复条目 / 已完成活动回魂 / 提醒重复。
本测试断言 UID 已改为按内容派生：与顺序无关、同一活动跨快照不变、版本内不重复。

运行：python3 tests/test_uid_stable.py
      （需要 flask；缺依赖则 SKIP 并退出码 0）
"""
import hashlib
import json
import os
import re
import sys
import tempfile

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


def load_manual(arr=None):
    """用临时 DATA_DIR 注入数组，避免依赖真实数据文件的顺序"""
    if arr is None:
        return app._manual_events()
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, 'manual.json'), 'w', encoding='utf-8') as f:
            json.dump(arr, f, ensure_ascii=False)
        real, app.DATA_DIR = app.DATA_DIR, d
        try:
            return app._manual_events()
        finally:
            app.DATA_DIR = real


def ics_uids(events):
    app._state['events'] = events
    raw = app.app.test_client().get('/api/calendar.ics').get_data(as_text=True)
    return re.findall(r'UID:(\S+)', raw)


# ---- 1. 与数组顺序无关：同一活动插到任意位置，UID 不变 ----
A = [
    {'game_id': 'hsr', 'title': '活动甲', 'start': '2026-09-10T12:00', 'end': '2026-09-20T23:59'},
    {'game_id': 'zzz', 'title': '活动乙', 'start': '2026-09-11T12:00', 'end': '2026-09-21T23:59'},
    {'game_id': 'r1999', 'title': '活动丙', 'start': '2026-09-12T12:00', 'end': '2026-09-22T23:59'},
]
B = ([{'game_id': 'hsr', 'title': '新补录活动', 'start': '2026-09-01T12:00', 'end': ''}]
     + A[::-1])
ua = {e['title']: e['id'] for e in load_manual(A)}
ub = {e['title']: e['id'] for e in load_manual(B)}
check('同一条数跨快照 UID 不变', {k: ub.get(k) for k in ua}, ua)

# ---- 2. 同一版本内 UID 与 (game_id, title, start) 一一对应 ----
events = load_manual()
ids = [e['id'] for e in events]
check('UID 唯一（无复用）', len(set(ids)), len(ids))
keyed = {(e['game_id'], e['title'], e['start']): e['id'] for e in events}
check('UID 与内容一一对应', len(keyed), len(ids))

# ---- 3. 派生口径：内容哈希，与 scrapers._ev 同风格 ----
e0 = events[0]
want = 'manual-' + hashlib.md5(
    f"{e0['game_id']}|{e0['title']}|{e0['start'] or ''}".encode('utf-8')).hexdigest()[:8]
check('ID 由内容派生', e0['id'], want)
# 下标形态（1~3 位纯数字）不得再出现；哈希值本身可能是纯数字，故只限短尾缀
check('ID 不再形如 manual-<小下标>',
      any(re.fullmatch(r'manual-\d{1,3}', i) for i in ids), False)

# ---- 4. 数据侧显式 id 优先 ----
explicit = load_manual([{'game_id': 'hsr', 'id': 'official-1', 'title': '显式 ID 活动',
                         'start': '2026-09-10T12:00'}])
check('显式 id 优先（安全字符集内）', explicit[0]['id'], 'official-1')
cjk = load_manual([{'game_id': 'hsr', 'id': '官方一号', 'title': '中文 ID 活动',
                    'start': '2026-09-10T12:00'}])
check('安全字符集外的显式 id 退回内容哈希',
      re.fullmatch(r'manual-[0-9a-f]{8}', cjk[0]['id']) is not None, True)

# ---- 4.5 不安全的显式 id 不吃：退回内容哈希，不进内联属性
unsafe = load_manual([{'game_id': 'hsr', 'id': "x');alert(1);//", 'title': '带引号 ID',
                       'start': '2026-09-10T12:00'}])
check('非法字符的显式 id 被拒绝（退回哈希）',
      re.fullmatch(r'manual-[0-9a-f]{8}', unsafe[0]['id']) is not None, True)

# ---- 5. 端到端 ICS：两份顺序不同的数据，UID 集合相同且与内容绑定 ----
_ev = load_manual(A)
uids_a = ics_uids(_ev)
uids_b = ics_uids(load_manual(A[::-1]))
check('ICS UID 数与事件数一致', len(uids_a), len(_ev))
check('ICS UID 唯一', len(set(uids_a)), len(uids_a))
check('重排后 ICS UID 集合不变', sorted(uids_a), sorted(uids_b))
check('ICS UID 已非下标形态',
      any(re.fullmatch(r'manual-\d{1,3}@ycal', u) for u in uids_a), False)
# 原下标位置换上另一条活动（旧写法会产生同一 UID）→ UID 必须随之改变
replaced = load_manual([dict(A[0], title='活动甲（改版）')] + A[1:])
uids_c = ics_uids(replaced)
check('原位置换活动后 UID 改变', uids_c[0] != uids_a[0], True)

# ---- 6. 与真实数据对拍：UID 不回归到下标形态 ----
real = load_manual()
check('真实 manual.json 条数与 UID 数一致', len(real), len({e['id'] for e in real}))

print('ALL PASS' if bad == 0 else 'SOME FAILED')
sys.exit(1 if bad else 0)
