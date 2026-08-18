# -*- coding: utf-8 -*-
"""各二游官方活动/公告抓取器(仅使用公开接口,不登录、不破解)"""
import hashlib
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import requests

from timeparse import extract_events, extract_range, html_to_text

UA = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/126.0 Safari/537.36',
    'Accept-Language': 'zh-CN,zh;q=0.9',
}
TIMEOUT = 15


def _get(url, **kw):
    kw.setdefault('timeout', TIMEOUT)
    headers = dict(UA)
    headers.update(kw.pop('headers', {}) or {})
    last = None
    for _ in range(2):
        try:
            r = requests.get(url, headers=headers, **kw)
            r.raise_for_status()
            if not r.encoding or r.encoding.lower() in ('iso-8859-1', 'ascii'):
                r.encoding = 'utf-8'  # 部分官网未声明 charset,按 UTF-8 解码
            return r
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(0.5)
    raise last


def _classify(title, default='资讯'):
    t = title or ''
    if re.search(r'祈愿|跃迁|卡池|寻访|招募|唤取|调频|UP|概率|光锥|音擎|补给|限定|联动角色|星琼|请托|征募', t, re.I):
        return '角色与专武'
    # 收紧:去掉"开放|开启|玩法"(几乎所有公告都命中),"节|杯|赛"移到更精确上下文
    if re.search(r'活动|挑战|签到|福利|征集|赛事|联动|前瞻|直播|试炼|竞猜|累充|兑换|限时|双倍|巡演|盛典|嘉年华', t, re.I):
        return '活动'
    if re.search(r'维护|更新|修复|公告|说明|公示|封禁|补偿|停服|版本更新说明', t, re.I):
        return '公告'
    # 宽松兜底:如果有「活动名」再加日期+开启/开放,才算活动;否则资讯
    if re.search(r'「[^」]+」.*(?:开启|开放|上线|正式)', t):
        return '活动'
    return default


_BAD_SHORT = {'活动', '菲林', '奖励', '登录', '签到', '福利', '母带'}
# 泛称噪音名(与 scraper.js 的 NOISE_NAME + BAD_SHORT 保持一致)
_NOISE_NAME_RE = re.compile(
    r'^(?:版本活动|限时活动|活动|公告|注意|温馨提示?|说明|维护公告?|更新说明|'
    r'全新版本|版本前瞻|前瞻|直播|特别节目|活动详情|活动一览|版本活动一览|'
    r'活动预告|新版本|版本更新|版本内容|活动玩法|玩法)$')


def is_noise_name(name):
    """判断标题是否属于无意义通用名(如"活动"/"登录"/"福利"/"版本前瞻")"""
    name = (name or '').strip()
    return name in _BAD_SHORT or bool(_NOISE_NAME_RE.match(name))


def _short(title, cat):
    """日历用短标题:活动取第一个「」名,卡池取第二个「」内的角色/武器名"""
    parts = re.findall(r'「([^」]{2,24})」', title or '')
    if not parts:
        return (title or '')[:24]
    name = parts[1] if cat == '角色与专武' and len(parts) >= 2 else parts[0]
    name = re.sub(r'[(（].*?[)）]', '', name).strip()
    if not name or name in _BAD_SHORT:
        return (title or '')[:24]
    return name[:18]


def _ev(game_id, game, title, category, pub, start, end, link, img='', kind='event', ext=None):
    """kind: 'event'=真活动/卡池(上月历,用短标题)  'info'=公告/资讯(仅进资讯列表)
    ext: 可选 {'ann_id','api','params'},前端点击时用它拉取公告正文弹窗展示"""
    title = re.sub(r'\s+', ' ', title).strip()
    if kind == 'event':
        title = _short(title, category)
        # 补 2 天默认窗口:有 start 按 start 补;无 start 用 pub 兜底
        s = start or pub
        if s is not None:
            if end is None:
                end = s + timedelta(days=2)
            elif end < s:
                end = s + timedelta(days=2)
            if start is None:
                start = s  # pub 兜底时也填 start
    ev = {
        # 稳定 ID:基于内容哈希,跨进程重启不变(内建 hash() 受 PYTHONHASHSEED 随机化影响)
        'id': f'{game_id}-{hashlib.md5(f"{title}|{start or pub}".encode("utf-8")).hexdigest()[:8]}',
        'game_id': game_id, 'game': game,
        'title': title,
        'category': category,
        'start': start.isoformat() if start else None,
        'end': end.isoformat() if end else None,
        'date': pub.isoformat() if pub else None,
        'link': link, 'image': img,
        'kind': kind,
    }
    if ext and ext.get('ann_id'):
        ev['ann_id'] = ext['ann_id']
        ev['_content_api'] = ext.get('api', '')
        ev['_content_params'] = ext.get('params', '')
    return ev


# ---------- 后置活动校验:多维度判断条目是否配上月历 ----------
# 从官方 API 抓到的条目未必是真活动——可能是玩法说明、系统公告、更新日志等
_VALID_DURATION_H = (2, 90 * 24)  # 合理活动时长:2小时 ~ 90天(放行同日直播/限时闪购类短活动)
_NON_EVENT_TITLE = re.compile(r'说明$|指南$|攻略$|规则$|介绍$|一览$|公示$|回顾$')
_EVENT_FEATURE_RE = re.compile(r'活动(?![说指解规一]).{0,12}(?:开启|开放|上线|开始)|「[^」]+」|限时|版本活动|新版|全新')


def _validate_event(e):
    """返回 (有效?, 原因)。invalid→降级为info,不进月历"""
    if e['kind'] != 'event':
        return True, ''
    title = e['title'] or ''
    name = title              # 已是 _short() 短标题

    # 1) 标题含说明书语气→非活动
    if _NON_EVENT_TITLE.search(title):
        return False, '标题像说明书(说明/指南/规则/介绍/一览/公示/回顾结尾)'

    # 1.5) 标题以「活动时间:」「开放时间:」等正文串味开头→非活动
    if re.match(r'^(活动时间|开放时间|开启时间)[:：]', title):
        return False, '标题是正文时间串(活动时间:/开放时间:开头)'

    # 2) 标题过短，且非卡池词→非活动
    if len(name) < 2 and not re.search(r'祈愿|跃迁|寻访|唤取|调频', title):
        return False, f'标题过短({len(name)}字)'

    # 3) 标题是已过滤的噪音通用名→非活动
    if is_noise_name(name) or is_noise_name(title[:30]):
        return False, '标题是噪音通用名'

    # 4) 有 start 和 end:检查时长是否合理(按小时计,放行同日短活动)
    s = e['start']
    ed = e['end']
    if s and ed:
        try:
            dur_h = (datetime.fromisoformat(ed) - datetime.fromisoformat(s)).total_seconds() / 3600
            if dur_h < _VALID_DURATION_H[0]:
                return False, f'活动时长过短({dur_h:.1f}小时)'
            if dur_h > _VALID_DURATION_H[1]:
                return False, f'活动时长过长({dur_h / 24:.0f}天,可能是常驻)'
        except (ValueError, TypeError):
            pass

    # 5) 无起止时间的条目:需要更强活动特征才上月历
    if not e['start']:
        if not _EVENT_FEATURE_RE.search(title):
            return False, '非官方来源且缺乏活动特征词'

    # 6) 标题命中噪音词→降级
    m = _NOISE_RE.search(title)
    if m:
        return False, f'标题命中噪音词:{m.group()}'

    # 7) 商城/网页/H5活动不上月历
    if _SHOP_RE.search(title) or _WEB_RE.search(title):
        return False, '商城/网页活动不排期'

    return True, ''


# ---------------- 米哈游系:游戏内公告(真实活动/卡池排期) ----------------
# 与游戏内「公告」面板同源,每条活动都带精确起止时间

_MIHOYO_ANN = {
    'hsr': ('https://hkrpg-ann-api.mihoyo.com/common/hkrpg_cn/announcement/api/getAnnList',
            'bundle_id=hkrpg_cn&channel_id=1&game=hkrpg&game_biz=hkrpg_cn&lang=zh-cn&level=70&platform=pc&region=prod_gf_cn&uid=100000000',
            'https://sdk.mihoyo.com/hkrpg/announcement/index.html?auth_appid=announcement&authkey_ver=1&bundle_id=hkrpg_cn&channel_id=1&game=hkrpg&game_biz=hkrpg_cn&lang=zh-cn&level=70&platform=pc&region=prod_gf_cn&sign_type=2&uid=100000000'),
    'zzz': ('https://announcement-api.mihoyo.com/common/nap_cn/announcement/api/getAnnList',
            'bundle_id=nap_cn&channel_id=1&game=nap&game_biz=nap_cn&lang=zh-cn&level=60&platform=pc&region=prod_gf_cn&uid=100000000',
            'https://sdk.mihoyo.com/nap/announcement/index.html?auth_appid=announcement&authkey_ver=1&bundle_id=nap_cn&channel_id=1&font_option=light&game=nap&game_biz=nap_cn&lang=zh-cn&level=60&platform=pc&region=prod_gf_cn&sign_type=2&uid=100000000'),
}

_ANN_TIME = re.compile(r'(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})')

# 分级过滤词表
_NOISE_RE = re.compile(
    r'更新说明|更新修复|修复与优化|玩法说明|赛季说明|全新内容一览|内容一览|途径一览|获取途径|'
    r'维护|停服|补偿|防沉迷|用户协议|隐私|封号|封禁|优惠券|企业微信|小程序|'
    r'问题说明|已知问题|异常说明|登录问题|充值|退款|客服|安全公告|问卷|'
    r'系统优化|功能预告|反馈入口|意见反馈|分享活动|邀请好友|前往参与|查看详情|玩法介绍|'
    r'合作者档案|工作台|新艾利都|创作者激励|'
    r'服务器时间|危行任务|潮汐任务|全新活动以及玩法|紧急事件|【版本活动】')
_SHOP_RE = re.compile(r'周边|商城|折扣|上新|贩售|限时出售|礼包|优惠券')
_POOL_RE = re.compile(r'扭蛋|卡池|祈愿|跃迁|调频|补给|概率\s*UP', re.I)
_WEB_RE = re.compile(r'米游社|网页活动|H5')
# 标题活动特征(星铁/绝区零的活动常混在"公告"组,靠标题识别)
_ACT_TITLE_RE = re.compile(r'活动[:：]|活动开启|活动现已|活动进行中|限时双倍|双倍掉落|登录领取|签到')
# 版本更新说明文(内含完整活动/卡池排期,需拆全文)
_VER_NOTE_RE = re.compile(r'版本更新说明|版本内容说明|更新说明')


def _ann_dt(s):
    m = _ANN_TIME.search(s or '')
    if not m:
        return None
    try:
        return datetime(*[int(x) for x in m.groups()])
    except ValueError:
        return None


def _mihoyo_content(api, params, ann_id):
    """取公告正文(getAnnContent),失败返回''"""
    try:
        r = _get(f"{api.replace('getAnnList', 'getAnnContent')}?{params}&ann_id={ann_id}")
        d = r.json().get('data') or {}
        lst = d.get('list') or []
        if lst:
            return lst[0].get('content') or ''
        return d.get('content') or ''
    except Exception:
        return ''


# 绝区零服务端常把地点/角色/系统介绍标为"活动",以下名词单独过滤(与 scraper.js ZZZ_NON_EVENT 一致)
_ZZZ_NON_EVENT = {
    '详见工作台-合作者档案', '罗斯凯利法', '布亚斯特', '齿轮街', '影池独舞',
    '今日穿搭', '月夜密语', '服务器时间', '邦布券', '梦想家', '恶名狩猎', '拉力委托',
    '零号空洞', '式舆防卫战', '危局强袭战', '_exclusive_', '实战模拟店', '电玩店',
    '报刊亭', '咖啡店', '拉面店', '录像店', '改装店', '玩具店', '花店', '便利店',
    '治安局', '对空六课', '奥波勒斯小队', '卡吕冬之子', '维多利亚家政', '狡兔屋', '白祇重工', 'H.S.O.S.6',
    'Random Play', '电玩', '街机', '刮刮卡', '报刊', '喵吉长官', '奖章', '纪念币'
}

# 绝区零版本公告:「七、全新活动」章节专用解析(与 scraper.js zzzExtractEvents 一致)
_ZZZ_SEC = re.compile(r'[七7][\s、.．]+全新活动')
_ZZZ_NEXT_SEC = re.compile(r'(?:^|\n)\s*[八九九十][\s、.．]+全新')
_ZZZ_ITEM = re.compile(r'(?:^|\n)\s*[·\-•]\s*([^\n]{2,35}?)(?=\n|$)')
_ZZZ_DT = re.compile(r'(\d{4})/(\d{2})/(\d{2})\s+(\d{2}):(\d{2})')
_ZZZ_FW = str.maketrans('０１２３４５６７８９：．', '0123456789:.')


def _zzz_extract_events(html, ver_start, ver_end):
    """绝区零版本更新说明:按「七、全新活动」章节拆 · 活动名 + 活动时间 行
    返回 [(name, start, end)]。注意入参须是原始 HTML(依赖块级标签还原换行)。"""
    if not html:
        return []
    text = re.sub(r'</(?:p|div|li|h[1-6]|tr|br)\s*>', '\n', html, flags=re.I)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'&\w+;', ' ', text)
    text = re.sub(r'\n\s*', '\n', text)
    text = re.sub(r'[ \t]+', ' ', text).strip()
    out, seen = [], set()
    m = _ZZZ_SEC.search(text)
    if not m:
        return out
    rest = text[m.end():]
    nm = _ZZZ_NEXT_SEC.search(rest)
    section = rest[:nm.start()] if nm else rest
    for im in _ZZZ_ITEM.finditer(section):
        name = re.sub(r'\s+', ' ', im.group(1)).strip()
        if not name or name in seen or is_noise_name(name):
            continue
        tail = section[im.end():im.end() + 600]
        tm = re.search(r'活动时间[:：]([^\n]+)', tail)
        if not tm:
            continue
        time_str = tm.group(1).strip().translate(_ZZZ_FW)
        # 两种形式: 2026/08/07 10:00(服务器时间) ~ 2026/08/24 03:59(服务器时间)
        #          3.1版本更新后 ~ 3.1版本结束 / 2026/09/08 03:59
        dates = []
        for dm in _ZZZ_DT.finditer(time_str):
            try:
                dates.append(datetime(int(dm.group(1)), int(dm.group(2)),
                                      int(dm.group(3)), int(dm.group(4)), int(dm.group(5))))
            except ValueError:
                pass
        s = dates[0] if dates else None
        e = dates[1] if len(dates) > 1 else None
        if re.search(r'版本更新后|版本维护后|更新后|维护结束', time_str):
            if s is None:
                s = ver_start
            elif e is None:
                # 「版本更新后 ~ 单日期」:该日期是结束时间,起点为版本开服
                e = s
                s = ver_start
        if e is None and re.search(r'版本结束', time_str):
            e = ver_end
        if s is None and e is None:
            continue
        seen.add(name)
        out.append((name, s, e))
    return out


def _mihoyo_ingame(gid, gname):
    """游戏内公告列表:只把真活动/真卡池标为 event,其余降为 info;
    版本更新说明文拆出其中的活动/卡池排期"""
    api, params, link = _MIHOYO_ANN[gid]
    r = _get(f'{api}?{params}')
    groups = (r.json().get('data') or {}).get('list') or []
    now = datetime.now()
    out = []
    ver_done = False  # 只拆最新一期版本说明文
    for g in groups:
        type_label = g.get('type_label') or ''
        if '推荐' in type_label:
            continue  # 推荐页签多为周边/广告,直接丢弃
        for a in g.get('list') or []:
            title = a.get('title') or ''
            if '<' in title:  # 绝区零 title 是 HTML,用副标题
                title = a.get('subtitle') or html_to_text(title)
            title = re.sub(r'\s+', ' ', title).strip()
            if not title:
                continue
            start = _ann_dt(a.get('start_time'))
            end = _ann_dt(a.get('end_time'))
            # 过滤:常驻(>400天)、结束超过30天的旧条目
            if start and end and (end - start).days > 400:
                continue
            if end and (now - end).days > 30:
                continue
            # 版本更新说明:拆全文提取活动/角色与专武排期,文章本身不进日历
            if not ver_done and _VER_NOTE_RE.search(title) and a.get('ann_id'):
                raw = _mihoyo_content(api, params, a['ann_id'])
                # 真版本说明文必含「全新活动」章节;HSR接口偶发错返回通行证等内容,跳过
                if raw and '全新活动' in raw:
                    ver_done = True
                    # 绝区零解析依赖块级标签还原换行,须喂原始 HTML;星铁走通用提取
                    items = (_zzz_extract_events(raw, start or now, end) if gid == 'zzz'
                             else extract_events(html_to_text(raw), start or now))
                    for name, s, e in items:
                        if e and e < now:
                            continue
                        if name in _BAD_SHORT or len(name) < 3:
                            continue
                        c2 = _classify(name, '活动')
                        out.append(_ev(gid, gname, name,
                                       c2 if c2 in ('活动', '角色与专武') else '活动',
                                       start or now, s, e, link, '', 'event'))
            tag = (a.get('tag_label') or '') + type_label
            # 分级判定(优先级: 噪音 > 商城 > 卡池 > 活动 > 其他)
            is_zzz_non_event = gid == 'zzz' and title in _ZZZ_NON_EVENT
            if is_zzz_non_event or _NOISE_RE.search(title):
                cat, kind = '资讯', 'info'
            elif _SHOP_RE.search(title):
                cat, kind = '公告', 'info'
            elif _POOL_RE.search(tag) or _POOL_RE.search(title):
                cat, kind = '角色与专武', 'event'
            elif gid == 'zzz' and re.search(r'活动公告|福利活动|卡池公告',
                                            a.get('tag_label') or '') and start and end:
                # 绝区零:独立公告里只认明确的活动/卡池/福利标签,杜绝地区/时装/系统混入
                # (卡池已在上一分支兜住,这里只需排除商城/网页类)
                if _SHOP_RE.search(title) or _WEB_RE.search(title):
                    cat, kind = '资讯', 'info'
                else:
                    cat, kind = '活动', 'event'
            elif ('活动' in type_label or _ACT_TITLE_RE.search(title)) and start and end:
                if _WEB_RE.search(title):
                    cat, kind = '资讯', 'info'  # 米游社网页签到/H5小活动
                else:
                    cat, kind = '活动', 'event'
            else:
                cat, kind = _classify(title, '公告'), 'info'
            out.append(_ev(gid, gname, title, cat, start or now, start, end, link,
                           a.get('banner') or '', kind,
                           {'ann_id': a['ann_id'], 'api': api, 'params': params}
                           if a.get('ann_id') else None))
    return out


# ---------------- 明日方舟:终末地 ----------------

def _ef_extract_version(text, pub):
    """终末地版本更新说明:按「■ 全新寻访及申领 / ■ 全新活动」章节拆排期
    返回 [(name, category, start, end)]"""
    ver_start = pub  # 版本开服时间 = 维护时段的结束时间
    m = re.search(r'(\d{4})/(\d{2})/(\d{2}) \d{2}:\d{2}\s*-\s*(\d{4})/(\d{2})/(\d{2}) (\d{2}):(\d{2})\s*（UTC\+8）', text)
    if m:
        g = [int(x) for x in m.groups()]
        try:
            ver_start = datetime(g[3], g[4], g[5], g[6], g[7])
        except ValueError:
            pass
    t_re = re.compile(r'(\d{4})/(\d{2})/(\d{2})\s+(\d{2}):(\d{2})')

    def dates(seg):
        out = []
        for mm in t_re.finditer(seg):
            try:
                out.append(datetime(*[int(x) for x in mm.groups()]))
            except ValueError:
                pass
        return out

    lines = [l.strip() for l in text.split('\n') if l.strip()]
    out = []
    section = last_name = ''
    now = datetime.now()
    i = 0
    while i < len(lines):
        l = lines[i]
        if l.startswith(('■', '▼')):
            section = l
        elif any(k in section for k in ('寻访', '申领', '活动', '赛季')):
            tm = re.match(r'^[·•]?\s*(活动时间|开放时间|赛季更新)[:：]\s*(.*)$', l)
            if not tm and '「' in l and not l.startswith('※'):
                nm = re.search(r'「([^」]{2,24})」', l)
                last_name = nm.group(1) if nm else last_name
            if tm:
                segs = [tm.group(2)]
                if not t_re.search(segs[0]):  # 时间写在下一行(多期活动)
                    segs = []
                    j = i + 1
                    while j < len(lines) and t_re.search(lines[j]):
                        segs.append(lines[j])
                        j += 1
                for seg in segs:
                    if re.search(r'长期开放|常驻|长期有效', seg) or '次「特许寻访」' in seg:
                        continue  # 常驻/特殊规则池不上排期
                    ds = dates(seg)
                    if '版本更新后' in seg:
                        start, end = ver_start, (ds[0] if ds else None)
                    elif ds:
                        start, end = ds[0], (ds[1] if len(ds) > 1 else None)
                    else:
                        continue
                    if not last_name or (end and end < now):
                        continue
                    cat = '角色与专武' if ('寻访' in section or '申领' in section) else '活动'
                    out.append((last_name, cat, start, end))
        i += 1
    return out


def _endfield(gid, gname):
    html = _get('https://endfield.hypergryph.com/news').text
    # 文章ID在 self.__next_f 流式数据中: \"cid\":\"9335\",...,\"title\":\"...\"
    cid_of = {}
    unesc = html.replace('\\"', '"')
    for m in re.finditer(r'"cid":"(\d+)"[^}]{0,400}?"title":"((?:[^"\\]|\\.)*?)"', unesc):
        cid_of[re.sub(r'\s+', ' ', m.group(2)).strip()] = m.group(1)
    pat = re.compile(
        r'NoticeList_item__\w+"[^>]*>.*?<img src="([^"]+)" alt="([^"]*)".*?'
        r'NoticeList_type__\w+">([^<]+)</span>.*?'
        r'NoticeList_date__\w+">([\d.]+)</span>.*?'
        r'NoticeList_title__\w+">([^<]+)</div>',
        re.S)
    out = []
    ver_done = False  # 只拆最新一期版本说明文
    for img, _alt, typ, date_s, title in pat.findall(html):
        title = title.strip()
        try:
            pub = datetime.strptime(date_s.strip(), '%Y.%m.%d')
        except ValueError:
            pub = datetime.now()
        cid = cid_of.get(title)
        link = f'https://endfield.hypergryph.com/news/{cid}' if cid else 'https://endfield.hypergryph.com/news'
        # 版本更新说明:内含全新活动/寻访及申领排期,拆出为独立事件
        if not ver_done and _VER_NOTE_RE.search(title):
            ver_done = True
            try:
                raw = _get(link, timeout=15).text
                raw = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', raw, flags=re.S)
                text = re.sub(r'&\w+;', ' ', re.sub(r'<[^>]+>', '\n', raw))
                for name, cat, s, e in _ef_extract_version(text, pub):
                    out.append(_ev(gid, gname, name, cat, pub, s, e, link, '', 'event'))
            except Exception:
                pass
        cat = _classify(title, '活动' if '活动' in typ else ('公告' if '公告' in typ else '资讯'))
        kind = 'event' if cat in ('活动', '角色与专武') and not _NOISE_RE.search(title) else 'info'
        out.append(_ev(gid, gname, title, cat, pub, None, None, link, img, kind))
    return out


# ---------------- 鸣潮 ----------------

def _wuthering(gid, gname):
    r = _get('https://media-cdn-mingchao.kurogame.com/akiwebsite/website2.0/json/G152/zh/ArticleMenu.json')
    arr = r.json()
    arr.sort(key=lambda x: x.get('startTime', ''), reverse=True)
    out = []
    extracted = False  # 只从最新一期版本说明文中批量提取,避免历史版本活动刷屏
    for a in arr[:60]:
        title = (a.get('articleTitle') or '').strip()
        try:
            pub = datetime.strptime(a.get('startTime', ''), '%Y-%m-%d %H:%M:%S')
        except ValueError:
            pub = datetime.now()
        link = f"https://mc.kurogame.com/main/news/detail/{a.get('articleId')}"
        if not extracted and re.search(r'内容说明', title):
            extracted = True
            try:
                full = _get(f"https://media-cdn-mingchao.kurogame.com/akiwebsite/website2.0/json/G152/zh/article/{a.get('articleId')}.json",
                            timeout=15).json()
                text = html_to_text(full.get('articleContent', ''))
                now = datetime.now()
                for name, start, end in extract_events(text, pub):
                    if end and end < now:  # 只保留未结束的活动
                        continue
                    out.append(_ev(gid, gname, name, _classify(name, '活动'), pub, start, end, link))
            except Exception:
                pass
        text = html_to_text(a.get('articleContent', ''))
        start, end = extract_range(text, pub)
        cat = _classify(title, '公告' if a.get('articleType') == 52 else '活动')
        # 官网文章只有「唤取/卡池」类且有排期才上月历,其余文章均为资讯
        if _POOL_RE.search(title) and start:
            cat, kind = '角色与专武', 'event'
        elif cat in ('活动', '角色与专武') and start and end and not _NOISE_RE.search(title):
            kind = 'event'
        else:
            kind = 'info'
        out.append(_ev(gid, gname, title, cat, pub, start, end, link, kind=kind))
    return out


# ---------------- 异环 ----------------

_AN_TIME_KW = re.compile(r'(活动时间|开放时间|开启时间)[:：]\s*([^。●]{0,60})')
_AN_DATE = re.compile(r'(\d{1,2})月(\d{1,2})日(?:\s*(\d{1,2})[:：](\d{2}))?')
_AN_VER_RE = re.compile(r'更新公告|维护公告')


def _ananta_extract_version(text, pub):
    """异环版本更新/停服维护公告:找全部时间规格,名字取前面最近的「」/【】
    返回 [(name, cat, start, end)]"""
    ver_start = pub  # 版本开服时间 = 维护时段的结束时间
    m = re.search(r'(\d{1,2})月(\d{1,2})日(\d{1,2})[:：](\d{2})\s*[–—\-~]\s*(\d{1,2})[:：](\d{2})\s*进行(?:停服|版本更新)?维护', text)
    if m:
        g = [int(x) for x in m.groups()[:6]]
        try:
            ver_start = datetime(pub.year, g[0], g[1], g[4], g[5])
        except ValueError:
            pass

    def dates(seg):
        out = []
        for mm in _AN_DATE.finditer(seg):
            try:
                d = datetime(pub.year, int(mm.group(1)), int(mm.group(2)),
                             int(mm.group(3)) if mm.group(3) else 0,
                             int(mm.group(4)) if mm.group(4) else 0)
            except ValueError:
                continue
            if (d - pub).days < -10:  # 早于公告发布日 = 跨年,补一年
                d = d.replace(year=d.year + 1)
            out.append(d)
        return out

    now = datetime.now()
    out = []
    seen = set()
    for tm in _AN_TIME_KW.finditer(text):
        seg = tm.group(2)
        if re.search(r'长期|常驻|永久', seg):
            continue  # 常驻内容不上排期
        ds = dates(seg)
        if '更新后' in seg:
            ends = [d for d in ds if d > ver_start]
            if not ends:
                continue  # 仅「版本更新后」无结束时间 = 常驻内容
            start, end = ver_start, ends[-1]
        elif ds:
            start = ds[0]
            end = ds[1] if len(ds) > 1 else None
        else:
            continue
        if end and end < start:  # 跨年结束时间
            end = end.replace(year=end.year + 1)
        if not end or end < now:
            continue
        # 名字: 时间关键字前最近的一个「」/【】(不跨句号/条目符)
        ctx0 = max(text.rfind('。', 0, tm.start()), text.rfind('●', 0, tm.start())) + 1
        names = re.findall(r'「([^」]{2,24})」|【([^】]{2,24})】', text[ctx0:tm.start()])
        if not names:
            continue
        name = (names[-1][0] or names[-1][1]).strip()
        blob = text[ctx0:tm.start()] + seg
        if re.search(r'折扣价格|在售时间|上架商城|商城购买|涂装价格|礼包', blob):
            continue  # 商城时装/礼包不上排期
        cat = '角色与专武' if re.search(r'限定S级|研募', blob) else '活动'
        if (name, start) in seen:
            continue
        seen.add((name, start))
        out.append((name, cat, start, end))
    return out


def _ananta(gid, gname):
    pat = re.compile(
        r'<a href="(/news/\w+/\d+/\d+\.html)"[^>]*>\s*<div class="listItem">.*?'
        r'<h2 class="title">(.*?)</h2>.*?'
        r'<p class="date">([\d-]+)</p>\s*<p class="type">([^<]*)</p>',
        re.S)
    entries = []  # (title, pub, link, default)
    seen = set()
    for cat, default in [('gameevent', '活动'), ('gamebroad', '公告'), ('gamenews', '资讯')]:
        r = _get(f'https://yh.wanmei.com/news/{cat}/index.html')
        for href, title, date_s, _typ in pat.findall(r.text)[:5]:
            if href in seen:
                continue
            seen.add(href)
            title = re.sub(r'<[^>]+>|\s+', ' ', title).strip()
            try:
                pub = datetime.strptime(date_s.strip(), '%Y-%m-%d')
            except ValueError:
                pub = datetime.now()
            entries.append((title, pub, 'https://yh.wanmei.com' + href, default))
    # 并行抓详情页
    def _one(e):
        try:
            return e[2], html_to_text(_get(e[2], timeout=10).text)
        except Exception:
            return e[2], ''
    texts = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        for link, txt in pool.map(_one, [e for e in entries if e[3] in ('活动', '公告')]):
            if txt:
                texts[link] = txt
    out = []
    ver_n = 0  # 只拆最新两期版本/维护公告(上半+下半)
    for title, pub, link, default in entries:
        start = end = None
        text = texts.get(link)
        if text:
            start, end = extract_range(text, pub)
            # 版本/维护公告:内含卡池与限时活动排期,拆出为独立事件
            if ver_n < 2 and _AN_VER_RE.search(title):
                ver_n += 1
                for name, c2, s, e in _ananta_extract_version(text, pub):
                    out.append(_ev(gid, gname, name, c2, pub, s, e, link, '', 'event'))
        cat = _classify(title, default)
        kind = 'event' if cat in ('活动', '角色与专武') and not _NOISE_RE.search(title) else 'info'
        if end and (datetime.now() - end).days > 30:
            continue  # 结束超30天的旧活动丢弃
        out.append(_ev(gid, gname, title, cat, pub, start, end, link, kind=kind))
    return out


# ---------------- 注册表与调度 ----------------

REGISTRY = [
    ('hsr',       '崩坏：星穹铁道', '#b688ff', lambda: _mihoyo_ingame('hsr', '崩坏：星穹铁道')),
    ('zzz',       '绝区零',         '#ff7a45', lambda: _mihoyo_ingame('zzz', '绝区零')),
    ('endfield',  '明日方舟：终末地', '#ff5f8f', lambda: _endfield('endfield', '明日方舟：终末地')),
    ('wuwa',      '鸣潮',           '#35d0ba', lambda: _wuthering('wuwa', '鸣潮')),
    ('ananta',    '异环',           '#f254c7', lambda: _ananta('ananta', '异环')),
]

GAMES_META = [{'id': g, 'name': n, 'color': c} for g, n, c, _ in REGISTRY]


def _run_one(entry):
    gid, name, _color, fn = entry
    t0 = time.time()
    try:
        events = fn()
        return events, {'ok': True, 'count': len(events), 'took': round(time.time() - t0, 1)}
    except Exception as e:  # noqa: BLE001
        return [], {'ok': False, 'count': 0, 'error': str(e)[:120], 'took': round(time.time() - t0, 1)}


def fetch_all():
    """并发抓取全部游戏。返回 (events, sources_status)"""
    events, sources = [], {}
    with ThreadPoolExecutor(max_workers=len(REGISTRY)) as pool:
        for (gid, name, _c, _f), res in zip(REGISTRY, pool.map(_run_one, REGISTRY)):
            evs, status = res
            events.extend(evs)
            sources[gid] = {'name': name, **status}
    # 去重(同游戏同标题保留信息最全的一条)
    seen = {}
    for e in events:
        key = (e['game_id'], e['title'])
        old = seen.get(key)
        if not old or (not old['start'] and e['start']):
            seen[key] = e

    # 后置校验:对每个 event 做质量检查,不通过→降级为 info(不进月历)
    dropped = 0
    for e in seen.values():
        if e['kind'] == 'event':
            valid, reason = _validate_event(e)
            if not valid:
                e['kind'] = 'info'
                e['_reject'] = reason
                dropped += 1
    if dropped:
        print(f'[validateEvent] {dropped} 个条目降级(非真活动)')

    events = sorted(seen.values(), key=lambda e: (e['start'] or e['date'] or ''), reverse=True)
    return events, sources
