# -*- coding: utf-8 -*-
"""timeparse 识别内核自测（覆盖各种真实公告写法 + 两天默认值）。"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime
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

# 22. 两天默认值
s, e = with_two_day_default(REF, None)
all_ok &= check("两天默认", e, REF + __import__('datetime').timedelta(days=2))

print("\n====", "ALL PASS" if all_ok else "SOME FAILED", "====")
sys.exit(0 if all_ok else 1)
