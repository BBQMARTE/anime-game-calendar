# -*- coding: utf-8 -*-
"""从中文游戏公告文本中提取活动时间范围（识别内核 · 最完善版）。

本文件被 scrapers.py / bilibili.py 引用；static/scraper.js 为其 JS 同构副本，
两端逻辑必须保持一致。

设计目标：覆盖尽可能多的真实公告写法——
  * 日期：2026年7月10日 / 2026/07/10 / 2026.07.10 / 07.10 / 7月10日 / 7/10
  * 时间：12:00 / 12:00:00 / 12点 / 12点30分 / 12时30分（半/全角、冒号均可）
  * 区间：x月x日 ~ x月x日（~ ～ — – 至 到 以及带空格的 - 均可），
          即使「没有」活动时间之类的关键词，只要出现紧挨的两个日期也识别
  * 跨年：12月30日 ~ 1月5日 自动把结束日滚到下一年
  * 长期：含「长期/常驻/永久/持续开放」视为无结束的常驻活动
  * 活动名：支持 「」『』【】[]（）〈〉 等多种括号，以及 ■/◆/✦ 标题行
"""
import re
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# 文本清洗
# ---------------------------------------------------------------------------
_TAG = re.compile(r'<[^>]+>')
_ENTITY = re.compile(r'&\w+;')
_WS = re.compile(r'\s+')
_FULLWIDTH = str.maketrans({
    '０': '0', '１': '1', '２': '2', '３': '3', '４': '4',
    '５': '5', '６': '6', '７': '7', '８': '8', '９': '9',
    '：': ':', '．': '.', '～': '~', '—': '-', '－': '-',
})


def html_to_text(html: str) -> str:
    """HTML 转纯文本（去标签、去实体、压缩空白）。"""
    if not html:
        return ''
    text = _TAG.sub(' ', html)
    text = _ENTITY.sub(' ', text)
    return _WS.sub(' ', text)


def _norm(text: str) -> str:
    """半角化（数字/冒号/点/波浪/破折号），便于统一正则。"""
    if not text:
        return ''
    return text.translate(_FULLWIDTH)


# ---------------------------------------------------------------------------
# 长期 / 常驻检测
# ---------------------------------------------------------------------------
_LONG_TERM = re.compile(
    r'(?:长期|常驻|永久|持续开放|常开|长期开放|不限时|无期限)\s*(?:开放|开启|活动|进行|存在)?'
)


def is_long_term(text: str) -> bool:
    return bool(_LONG_TERM.search(text or ''))


# ---------------------------------------------------------------------------
# 活动时间关键词（引导词，命中后在其后文找日期）
# ---------------------------------------------------------------------------
_KW = re.compile(
    r'(活动时间|活动期间|活动开放时间|开放时间|开启时间|上线时间|开始时间|'
    r'祈愿时间|跃迁时间|寻访时间|招募时间|唤取时间|卡池时间|'
    r'上架时间|售卖时间|维护时间|更新时间|兑换时间|领取时间|投稿时间|'
    r'征集时间|挑战时间|接力时间|直播时间|前瞻时间|演出时间|'
    r'预约时间|开放预约时间|报名|截止|结束时间)[:：]?\s*'
)

# 「版本更新后 / 维护后」等：起点用参考日期
_VERSION_AFTER = re.compile(r'(版本更新后|更新完成后|维护后|开服后|开启后|更新后|维护结束)')


# ---------------------------------------------------------------------------
# 日期 / 时间 token 解析
# ---------------------------------------------------------------------------
# 带年份：2026年7月10日 / 2026/07/10 / 2026.07.10 / 2026-07-10
_DATE_Y = re.compile(
    r'(?P<y>\d{4})\s*(?:年|/|\.|\-)\s*'
    r'(?P<m>\d{1,2})\s*(?:月|/|\.|\-)\s*'
    r'(?P<d>\d{1,2})\s*日?'
)
# 不带年份：7月10日 / 7/10 / 07.10（不用 - ，避免拆开 2026-07-10）
_DATE_MD = re.compile(r'(?<![\d/.\-])(?P<m>\d{1,2})\s*(?:月|/|\.)\s*(?P<d>\d{1,2})\s*日?')

# 时间：12:00 / 12:00:00 / 12点(30分) / 12时(30分)
_TIME = re.compile(
    r'\s*'
    r'(?:(?P<h1>[0-2]?\d)\s*[:：]\s*(?P<mi1>[0-5]?\d)(?:\s*[:：]\s*(?P<s1>[0-5]?\d))?'  # 时:分(:秒)
    r'|(?P<h2>[0-2]?\d)\s*点\s*(?P<mi2>[0-5]?\d)?\s*分?'                               # 点
    r'|(?P<h3>[0-2]?\d)\s*时\s*(?P<mi3>[0-5]?\d)?\s*分?)'                              # 时
)

# 区间分隔符（夹在两个日期之间；至/到 不要求前后空白，用于自然语言「至7月20日」）
_RANGE_SEP = re.compile(r'(?:~|～|—|–|至|到|\s[-\u2010\u2011]\s)')

# 版本号噪声：3.1版本 / V4.4 / 4.4版本
_VERSION_NOISE = re.compile(r'^\s*(?:v|V)?\d+[./]\d+\s*版本')


def _parse_time(text: str, pos: int):
    """从 pos 起尝试解析时间，返回 (hour, minute, endpos) 或 (0,0,pos)。"""
    m = _TIME.match(text, pos)
    if not m:
        return 0, 0, pos, False
    if m.group('h1') is not None:
        h, mi = int(m.group('h1')), int(m.group('mi1') or 0)
    elif m.group('h2') is not None:
        h, mi = int(m.group('h2')), int(m.group('mi2') or 0)
    else:
        h, mi = int(m.group('h3')), int(m.group('mi3') or 0)
    return h, mi, m.end(), True


def _make_dt(year, month, day, hour, minute, ref: datetime):
    if year is None:
        year = ref.year  # 无年份默认参考年（跨年由区间逻辑处理）
    try:
        return datetime(year, month, day, hour, minute)
    except ValueError:
        return None


def find_date_tokens(text: str, ref: datetime):
    """返回按出现顺序排列的日期 token 列表：
    [{'dt': datetime, 'start': int, 'end': int, 'has_time': bool}, ...]
    """
    toks = []
    norm = _norm(text)
    for rx in (_DATE_Y, _DATE_MD):
        for m in rx.finditer(norm):
            after = norm[m.end():m.end() + 4]
            if after.startswith('版本') or _VERSION_NOISE.match(norm[m.start():m.end() + 8]):
                continue
            y = m.groupdict().get('y')
            y = int(y) if y else None
            mo = int(m.group('m'))
            d = int(m.group('d'))
            if not (1 <= mo <= 12 and 1 <= d <= 31):
                continue
            h, mi, endpos, has_time = _parse_time(norm, m.end())
            dt = _make_dt(y, mo, d, h, mi, ref)
            if dt is None:
                continue
            toks.append({'dt': dt, 'start': m.start(), 'end': endpos, 'has_time': has_time})
    toks.sort(key=lambda x: (x['start'], -(x['end'] - x['start'])))
    # 去重：同一真实日期会被 _DATE_Y 与 _DATE_MD 各匹配一次（长串包含短串）
    deduped = []
    for t in toks:
        if any(t['start'] >= k['start'] and t['end'] <= k['end'] for k in deduped):
            continue
        deduped.append(t)
    return deduped


def _apply(tok: dict, is_end: bool):
    dt = tok['dt']
    if is_end and not tok['has_time']:
        dt = dt.replace(hour=23, minute=59, second=59)
    return dt


def _fix_order(start: datetime, end: datetime):
    """结束早于开始时，把结束滚到下一年（处理 12月~1月 跨年区间）。"""
    if end < start:
        end = end.replace(year=end.year + 1)
    return start, end


def _range_in_segment(seg: str, ref: datetime):
    """在一段文本内找日期区间（忽略关键词），返回 (start, end)。"""
    toks = find_date_tokens(seg, ref)
    if len(toks) >= 2:
        s = _apply(toks[0], False)
        e = _apply(toks[1], True)
        return _fix_order(s, e)
    if len(toks) == 1:
        return _apply(toks[0], False), None
    return None, None


def _range_sep_side(text: str, start: int, end: int):
    """判断区间分隔符在 token 的前面还是后面；返回 'before','after','both','near' 或 None。"""
    b = text[max(0, start - 15):start].rstrip()
    sep_b = bool(_RANGE_SEP.search(b[-4:]))       # 前面最后 4 个字符
    a = text[end:min(len(text), end + 20)].lstrip()
    sep_a = bool(_RANGE_SEP.search(a[:4]))         # 后面最前 4 个字符
    if sep_b and sep_a:
        return 'both'
    if sep_b:
        return 'before'
    if sep_a:
        return 'after'
    near = text[max(0, start - 20):end + 20]
    return 'near' if _RANGE_SEP.search(near) else None


# ---------------------------------------------------------------------------
# 公共 API
# ---------------------------------------------------------------------------
def extract_range(text: str, ref_date: datetime = None):
    """从文本中提取第一个活动时间范围。

    返回 (start, end) datetime 元组，缺省端为 None；未找到返回 (None, None)。
    - 命中「长期/常驻/永久」返回 (ref_date, None) 表示无结束的常驻活动。
    - 优先按关键词在后文找；找不到关键词则兜底：全文紧挨的两个日期视为区间。
    """
    if not text:
        return None, None
    ref_date = ref_date or datetime.now()
    norm = _norm(text)

    if is_long_term(norm):
        return ref_date, None

    toks = find_date_tokens(norm, ref_date)

    # 1) 关键词优先：在其后 200 字符内取日期
    for kw in _KW.finditer(norm):
        lo, hi = kw.end(), kw.end() + 200
        ctx = norm[max(0, kw.start() - 60):hi]  # 关键词前后文（含「版本更新后」）
        seg_toks = [t for t in toks if lo <= t['start'] < hi]
        if len(seg_toks) >= 2:
            s = _apply(seg_toks[0], False)
            e = _apply(seg_toks[1], True)
            return _fix_order(s, e)
        if len(seg_toks) == 1:
            tok = seg_toks[0]
            if _VERSION_AFTER.search(ctx):
                return ref_date, _apply(tok, True)              # 版本更新后~date → [ref, end]
            side = _range_sep_side(norm, tok['start'], tok['end'])
            if side in ('before', 'both'):
                return ref_date, _apply(tok, True)              # ~date → end
            if side == 'after':
                return _apply(tok, False), None                 # date~ → start
            if side == 'near':
                return ref_date, _apply(tok, True)              # 附近有分隔符，保守当结束
            return _apply(tok, False), None                     # 无分隔符，单日期 = 开始

    # 2) 无关键词兜底：需同时满足①两个日期紧挨 ②它们之间有区间分隔符
    if len(toks) >= 2:
        for i in range(len(toks) - 1):
            gap = toks[i + 1]['start'] - toks[i]['end']
            if gap <= 60:
                between = norm[toks[i]['end']:toks[i + 1]['start']]
                if _RANGE_SEP.search(between):               # 必须有分隔符才配对
                    s = _apply(toks[i], False)
                    e = _apply(toks[i + 1], True)
                    return _fix_order(s, e)

    if len(toks) == 1:
        # 「版本更新后」等也在兜底路径检查
        if _VERSION_AFTER.search(norm):
            return ref_date, _apply(toks[0], True)
        return _apply(toks[0], False), None
    return None, None


# 活动名噪声（泛称，不是具体活动）
_NOISE_NAME = re.compile(
    r'^(?:版本活动|限时活动|活动|公告|注意|温馨提示?|说明|维护公告?|更新说明|'
    r'全新版本|版本前瞻|前瞻|直播|特别节目|活动详情|活动一览|版本活动一览|'
    r'活动预告|新版本|版本更新|版本内容|活动玩法|玩法)$'
)


def _is_noise_name(name: str) -> bool:
    return bool(_NOISE_NAME.match(name.strip()))


# 多括号活动名（支持 「」『』【】[]（）〈〉 等任意配对）
_BRACKET = re.compile(r'[「『【\[〈（](?P<name>(?:[^」』】\]〉）「『【\[〈（]){2,30}?)[」』】\]〉）]')


def extract_events(text: str, ref_date: datetime = None):
    """从版本说明文中提取多个「活动名 + 时间范围」。

    返回 [(name, start, end)]，name 为活动名，start/end 为 datetime 或 None。
    支持 「」『』【】[]（）〈〉 以及各种括号；也支持 ■/◆/✦ 标题行后紧跟活动时间。
    """
    if not text:
        return []
    ref_date = ref_date or datetime.now()
    norm = _norm(text)
    out, seen = [], set()

    # 1) 括号活动名
    for m in _BRACKET.finditer(norm):
        name = m.group('name').strip()
        if not name or name in seen or _is_noise_name(name):
            continue
        seg = norm[m.end():m.end() + 220]
        s, e = _range_in_segment(seg, ref_date)
        if s or e:
            seen.add(name)
            out.append((name, s, e))

    # 2) 标题行：■/◆/✦ 开头的一行，其后 220 字符内有活动时间
    for m in re.finditer(r'[■◆✦★]\s*([^\n■◆✦★]{2,30})', norm):
        name = m.group(1).strip()
        if not name or name in seen or _is_noise_name(name):
            continue
        seg = norm[m.end():m.end() + 220]
        if not re.search(r'活动时间|活动期间|开放时间|开启时间|挑战时间', seg[:120]):
            continue
        s, e = _range_in_segment(seg, ref_date)
        if s or e:
            seen.add(name)
            out.append((name, s, e))

    return out


# ---------------------------------------------------------------------------
# 两天默认值：缺结束时间的活动补 2 天窗口（UI 展示更友好）
# ---------------------------------------------------------------------------
TWO_DAYS = timedelta(days=2)


def with_two_day_default(start, end):
    """结束时间为空时，默认补 2 天。"""
    if start and end is None:
        return start, start + TWO_DAYS
    return start, end


if __name__ == '__main__':
    # 极简自测
    import sys
    sample = sys.argv[1] if len(sys.argv) > 1 else '活动时间：2026年7月10日 12:00 ~ 2026年8月10日 12:00'
    print(extract_range(sample))
