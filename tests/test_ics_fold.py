# -*- coding: utf-8 -*-
"""ICS 折行回归测试（Issue #11）。

覆盖 RFC5545 §3.1：任意行（含 SUMMARY/URL 等含中文的长属性）按 UTF-8 octet 折行，
单行不超过 75 字节、续行以单空格开头、折叠后内容可无损还原。

运行：python3 tests/test_ics_fold.py
      （需要 flask；缺依赖则 SKIP 并退出码 0）
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import app
    from app import _ics_fold
except ImportError as e:  # pragma: no cover - 缺依赖时不算失败
    print('SKIP: 无法导入 app（%s）' % e)
    sys.exit(0)

all_ok = True


def check(label, got, expect):
    global all_ok
    ok = got == expect
    all_ok = all_ok and ok
    print("[%s] %s: got=%r expect=%r" % ('OK ' if ok else 'FAIL', label, got, expect))
    return ok


def unfold(text):
    """把折叠恢复成原文（去掉 CRLF + 单个空格）"""
    return text.replace('\r\n ', '')


# ---- 1. 短行不动 ----
check('短行不折', _ics_fold('SUMMARY:短标题'), 'SUMMARY:短标题')

# ---- 2. 中文长标题按字节折行，且不劈多字节字符 ----
long_title = 'SUMMARY:【重返未来：1999】《重返未来：1999》2026箱中巡游·特别前瞻'
folded = _ics_fold(long_title)
parts = folded.split('\r\n')
check('长行被折（多段）', len(parts) > 1, True)
check('每段 <= 75 字节', all(len(p.encode('utf-8')) <= 75 for p in parts), True)
check('续行单空格开头', all(p.startswith(' ') for p in parts[1:]), True)
check('折叠可无损还原', unfold(folded), long_title)

# ---- 3. 纯 ASCII 超长行（URL）同样按 75 字节折 ----
url_line = 'URL:https://example.com/ann?id=' + 'a' * 300
folded_url = _ics_fold(url_line)
check('URL 折行每段 <= 75', max(len(p.encode()) for p in folded_url.split('\r\n')) <= 75, True)
check('URL 还原', unfold(folded_url), url_line)

# ---- 4. 4 字节字符（emoji）不被劈开 ----
emoji = 'SUMMARY:' + '🎉' * 60
folded_emoji = _ics_fold(emoji)
check('emoji 折行每段 <= 75', all(len(p.encode('utf-8')) <= 75 for p in folded_emoji.split('\r\n')), True)
check('emoji 还原', unfold(folded_emoji), emoji)

# ---- 5. 端到端：真实数据结构生成订阅源 ----
LONG_LINK = ('https://sdk.hoyoverse.com/mihoyo-sdk-web/mihoyo-h5/#/login'
             '?auth_appid=webview&bundle_id=abc&extra=' + 'x' * 200)
app._state['events'] = [
    {'id': 'manual-0a1b2c', 'game_id': 'r1999', 'game': '重返未来：1999', 'kind': 'event',
     'title': '《重返未来：1999》2026箱中巡游·特别前瞻节目与版本福利总览（含兑换商店与签到）',
     'start': '2026-09-10T00:00', 'end': '2026-09-20T23:59', 'link': LONG_LINK},
    {'id': 'manual-1a2b3c', 'game_id': 'hsr', 'game': '崩坏：星穹铁道', 'kind': 'event',
     'title': '换行\n测试条目', 'start': '2026-09-10T12:00', 'end': None},
    {'id': 'manual-2a3b4c', 'game_id': 'zzz', 'game': '绝区零', 'kind': 'info',
     'title': '资讯条目不进订阅', 'start': '2026-09-10T00:00', 'end': None},
]
client = app.app.test_client()


def fetch(fold):
    """fold=False 时临时关掉折行，用于对比折叠前后内容"""
    orig = app._ics_fold
    if not fold:
        app._ics_fold = lambda line, limit=75: line
    try:
        return client.get('/api/calendar.ics').get_data(as_text=True)
    finally:
        app._ics_fold = orig


raw = fetch(True)
lines = [l for l in raw.split('\r\n') if l]
check('无超过 75 字节的行', max(len(l.encode('utf-8')) for l in lines) <= 75, True)
check('存在续行', any(l.startswith(' ') for l in lines), True)

flat_lines = [l for l in fetch(False).split('\r\n') if l]
unfolded = [l for l in unfold(raw).split('\r\n') if l]
check('折叠前后逻辑行数一致', len(unfolded), len(flat_lines))
check('折叠可还原为折叠前内容（逐行）', unfolded, flat_lines)
check('单属性内换行已转义为空格（不产生裸换行）',
      any(l.startswith('SUMMARY:【崩坏：星穹铁道】换行 测试条目') for l in flat_lines), True)
check('资讯条目（kind=info）不进订阅', any('资讯条目不进订阅' in l for l in flat_lines), False)

# ---- 6. 用 icalendar 回读：VEVENT 数与非折叠版一致 ----
try:
    import icalendar
except ImportError:
    print('SKIP: 未安装 icalendar，跳过回读校验')
else:
    def vevents(text):
        return icalendar.Calendar.from_ical(text).walk('VEVENT')
    a, b = list(vevents(raw)), list(vevents(fetch(False)))
    check('回读 VEVENT 数一致', len(a), len(b))
    check('回读 SUMMARY 集合一致',
          sorted(str(x.get('SUMMARY')) for x in a), sorted(str(x.get('SUMMARY')) for x in b))
    check('回读 UID 唯一', len({str(x.get('UID')) for x in a}), len(a))

print('\n====', 'ALL PASS' if all_ok else 'SOME FAILED', '====')
sys.exit(0 if all_ok else 1)
