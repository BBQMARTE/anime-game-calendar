# -*- coding: utf-8 -*-
"""timeparse 识别内核自测（覆盖各种真实公告写法 + 两天默认值）。"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime
import scrapers
from timeparse import extract_range, extract_events, with_two_day_default, find_date_tokens, is_long_term

REF = datetime(2026, 8, 3, 12, 0, 0)  # 参考时间：2026-08-03


def check(label, got, expect):
    ok = got == expect
    print(f"[{'OK ' if ok else 'FAIL'}] {label}: got={got} expect={expect}")
    return ok


all_ok = True


def rng(text, ref=REF):
    s, e = extract_range(text, ref)
    return (s.strftime('%Y-%m-%d %H:%M') if s else None,
            e.strftime('%Y-%m-%d %H:%M') if e else None)


# 1. 标准「年 月 日 时:分 ~ 年 月 日 时:分」
all_ok &= check("标准区间", rng("活动时间：2026年7月10日 12:00 ~ 2026年8月10日 12:00"),
                ("2026-07-10 12:00", "2026-08-10 12:00"))

# 2. 斜杠日期
all_ok &= check("斜杠日期", rng("活动时间 2026/07/10 12:00 - 2026/08/10 12:00"),
                ("2026-07-10 12:00", "2026-08-10 12:00"))

# 3. 点分隔日期
all_ok &= check("点日期", rng("活动期间：2026.07.10 ~ 2026.08.10"),
                ("2026-07-10 00:00", "2026-08-10 23:59"))

# 4. 月日不带年（同年，补 00:00 / 23:59）
all_ok &= check("月日无年", rng("活动时间：7月10日 12:00 ~ 7月20日 12:00"),
                ("2026-07-10 12:00", "2026-07-20 12:00"))

# 5. 跨年区间 12月~1月
all_ok &= check("跨年", rng("活动时间：2025年12月30日 ~ 2026年1月5日"),
                ("2025-12-30 00:00", "2026-01-05 23:59"))

# 6. 跨年（无年）12月~1月
all_ok &= check("跨年无年", rng("活动时间：12月30日 ~ 1月5日"),
                ("2026-12-30 00:00", "2027-01-05 23:59"))

# 7. 「点」时间
all_ok &= check("点时间", rng("开启时间：2026年7月10日 10点 ~ 2026年7月20日 10点30分"),
                ("2026-07-10 10:00", "2026-07-20 10:30"))

# 8. 「时」时间
all_ok &= check("时时间", rng("开放时间 2026年7月10日 12时 ~ 2026年7月20日 12时"),
                ("2026-07-10 12:00", "2026-07-20 12:00"))

# 9. 无关键词，仅紧挨两个日期（兜底）
all_ok &= check("无关键词兜底", rng("本次嘉年华将于7月10日开启，至7月20日结束"),
                ("2026-07-10 00:00", "2026-07-20 23:59"))

# 10. 波浪号
all_ok &= check("波浪号", rng("活动时间：2026年7月10日～2026年8月10日"),
                ("2026-07-10 00:00", "2026-08-10 23:59"))

# 11. 「至」
all_ok &= check("至", rng("活动时间：2026年7月10日 至 2026年8月10日"),
                ("2026-07-10 00:00", "2026-08-10 23:59"))

# 12. 版本更新后 ~ 某日
all_ok &= check("版本更新后", rng("版本更新后开放，活动时间：~2026年8月10日 12:00"),
                ("2026-08-03 12:00", "2026-08-10 12:00"))

# 13. 长期/常驻
all_ok &= check("长期常驻检测", is_long_term("本活动为长期开放活动"), True)
s, e = extract_range("长期开放，欢迎随时参与", REF)
all_ok &= check("长期返回ref", (s.strftime('%Y-%m-%d') if s else None, e), ("2026-08-03", None))

# 14. 单个日期（无结束）
all_ok &= check("单日期", rng("开启时间：2026年7月10日 12:00"),
                ("2026-07-10 12:00", None))

# 15. 版本号噪声不误判 (3.1版本 不应被当成 3月1日)
all_ok &= check("版本号噪声", rng("3.1版本更新，新增内容"), (None, None))

# 16. 全角数字/冒号
all_ok &= check("全角", rng("活动时间：２０２６年７月１０日１２：００〜２０２６年８月１０日"),
                ("2026-07-10 12:00", "2026-08-10 23:59"))

# 17. 秒级时间
all_ok &= check("秒级", rng("活动时间：2026年7月10日 12:00:00 ~ 2026年8月10日 12:00:00"),
                ("2026-07-10 12:00", "2026-08-10 12:00"))

# 18. 活动名提取（「」）
evs = extract_events("「星轨航程」活动期间：2026年7月10日 ~ 2026年7月20日", REF)
all_ok &= check("活动名「」", (evs[0][0], evs[0][1].strftime('%Y-%m-%d') if evs[0][1] else None),
                ("星轨航程", "2026-07-10"))

# 19. 活动名提取（【】）
evs = extract_events("【盛夏歌会】开放时间：2026年7月10日 ~ 2026年7月20日", REF)
all_ok &= check("活动名【】", (evs[0][0], evs[0][1].strftime('%Y-%m-%d') if evs[0][1] else None),
                ("盛夏歌会", "2026-07-10"))

# 20. 标题行 ■
evs = extract_events("■ 周年庆盛典\n活动时间：2026年7月10日 ~ 2026年7月20日", REF)
all_ok &= check("标题行■", (evs[0][0] if evs else None, evs[0][1].strftime('%Y-%m-%d') if evs and evs[0][1] else None),
                ("周年庆盛典", "2026-07-10"))

# 21. 噪音名过滤（【版本活动】不应作为活动名）
evs = extract_events("【版本活动】「夏日大作战」活动时间：2026年7月10日 ~ 2026年7月20日", REF)
names = [e[0] for e in evs]
all_ok &= check("噪音名过滤", ("版本活动" not in names and "夏日大作战" in names), True)

# 22. 泛称活动名过滤（与 scraper.js isNoiseName 同表：NOISE_NAME + BAD_SHORT）
for _bad in ("签到", "福利", "奖励", "登录", "菲林", "母带", "活动", "版本活动", "前瞻"):
    evs = extract_events("【%s】活动时间：2026年7月10日 ~ 2026年7月20日" % _bad, REF)
    all_ok &= check("泛称名过滤 %s" % _bad, evs, [])
# 真活动名（含「签到/登录」字样但不是纯泛称）不被误杀
for _good in ("应门者·签到活动", "累计登录有礼", "每日签到福利", "盛夏嘉年华"):
    evs = extract_events("【%s】活动时间：2026年7月10日 ~ 2026年7月20日" % _good, REF)
    all_ok &= check("活动名保留 %s" % _good, [e[0] for e in evs], [_good])


# 23. 两天默认值
s, e = with_two_day_default(REF, None)
all_ok &= check("两天默认", e, REF + __import__('datetime').timedelta(days=2))


# 24. 不存在日期 / 跨年越界（Issue #9）：_make_dt 丢弃 token、_fix_order 不抛异常
def _safe_win(start):
    """补 2 天窗口不得越界（返工前 9999 年起点会抛 OverflowError，经 _ev 吞成单源 0 条）"""
    try:
        return with_two_day_default(start, None)[1]
    except Exception as ex:                                  # noqa: BLE001
        return 'EXC %s' % type(ex).__name__


def _safe_ev(title, pub, start, end):
    """scrapers._ev 不得抛异常（未捕获异常会让 scrapers._run_one 判单源 0 条）"""
    try:
        ev = scrapers._ev('g1', '测试', title, '活动', pub, start, end, '')
        return ev['start'], ev['end']
    except Exception as ex:                                  # noqa: BLE001
        return 'EXC %s' % type(ex).__name__


def _safe_range(text, ref=REF):
    """extract_range 不得抛异常（未捕获异常会让 scrapers._run_one 判单源 0 条）"""
    try:
        return rng(text, ref)
    except Exception as ex:                                  # noqa: BLE001
        return 'EXC %s' % type(ex).__name__


all_ok &= check("闰日跨年不抛异常", _safe_range("活动时间：12月31日 ~ 2月29日", datetime(2028, 12, 1)),
                ("2028-12-31 00:00", "2029-02-28 23:59"))
all_ok &= check("9999 年不滚年", _safe_range("限时活动 9999年12月30日 ~ 9999年2月28日", datetime(9999, 1, 1)),
                ("9999-12-30 00:00", None))
all_ok &= check("9998 年界内滚年", _safe_range("活动时间：9998年12月30日 ~ 9998年2月28日", datetime(9998, 1, 1)),
                ("9998-12-30 00:00", "9999-02-28 23:59"))
# 不存在的日期（平年 2月29日 / 4月31日 / 2月30日）丢 token：区间起点落回参考日、终点取末 token
# （与 scraper.js 的 mkDate 回读校验同口径，双端逐字段一致见 tests/test_parity.py）
all_ok &= check("不存在的日期 token 数",
                [t['dt'].strftime('%m-%d') for t in find_date_tokens("2026年2月29日 ~ 2026年3月5日", REF)],
                ['03-05'])
all_ok &= check("平年2月29日丢token", _safe_range("活动时间：2026年2月29日 ~ 2026年3月5日"),
                ("2026-08-03 12:00", "2026-03-05 23:59"))
all_ok &= check("4月31日丢token", _safe_range("活动时间：2026年4月31日 ~ 2026年5月10日"),
                ("2026-08-03 12:00", "2026-05-10 23:59"))
all_ok &= check("2月30日丢token", _safe_range("活动时间：2月30日 10点至2026年3月21日 12时30分"),
                ("2026-08-03 12:00", "2026-03-21 12:30"))
# 闰年 2月29日 是合法日期，仍照常解析
all_ok &= check("闰年2月29日保留", _safe_range("活动时间：2028年2月29日 ~ 2028年3月5日"),
                ("2028-02-29 00:00", "2028-03-05 23:59"))
# 正常跨年不回归
all_ok &= check("正常跨年不回归", _safe_range("活动时间：2026年12月31日 ~ 2026年1月5日"),
                ("2026-12-31 00:00", "2027-01-05 23:59"))

# 25. 补 2 天窗口不得越界（Issue #9 返工：9999 年起点 + 无结束时间 → scrapers._ev 曾抛 OverflowError）
all_ok &= check("9999 起点补窗不越界（不抛异常、放弃结束时间）",
                _safe_win(datetime(9999, 12, 30)), None)
all_ok &= check("9999 起点 _ev 不抛异常",
                _safe_ev("限时活动", datetime(9999, 1, 10), datetime(9999, 12, 30), None),
                ("9999-12-30T00:00:00", None))
all_ok &= check("9999 起点仍可补窗上月内（9999-12-29）", str(_safe_win(datetime(9999, 12, 29))),
                "9999-12-31 00:00:00")
all_ok &= check("非边界起点照常补窗", str(_safe_win(datetime(2026, 1, 1))), "2026-01-03 00:00:00")
all_ok &= check("12:60 与 Python _TIME 同口径",
                rng("活动时间：9月10日 12:60 ~ 9月20日 12:00"),
                ("2026-09-10 12:06", "2026-09-20 12:00"))
all_ok &= check("95:00 与 Python _TIME 同口径（不匹配为时分）",
                rng("活动时间：9月10日 95:00 ~ 9月20日 12:00"),
                ("2026-09-10 00:00", "2026-09-20 12:00"))

print("\n====", "ALL PASS" if all_ok else "SOME FAILED", "====")
sys.exit(0 if all_ok else 1)
