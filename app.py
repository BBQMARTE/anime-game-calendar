# -*- coding: utf-8 -*-
"""二游活动日历 - 本地服务
自动抓取各二游官方活动/公告,聚合成日历展示。
运行后自动打开浏览器 http://127.0.0.1:5000
"""
import gzip
import hashlib
import ipaddress
import json
import os
import re
import socket
import threading
import time
import webbrowser
from datetime import datetime, timedelta, timezone
from io import BytesIO, StringIO
import csv

import requests
from flask import Flask, Response, jsonify, request, send_file, send_from_directory
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit
from urllib3.util import parse_url

import bilibili
import scrapers

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
CACHE_FILE = os.path.join(DATA_DIR, 'cache.json')
REFRESH_INTERVAL = 30 * 60  # 30 分钟自动刷新

os.makedirs(DATA_DIR, exist_ok=True)

app = Flask(__name__, static_folder=os.path.join(BASE_DIR, 'static'))

_lock = threading.Lock()
_state = {
    'updated': None,
    'refreshing': False,
    'events': [],
    'sources': {},
    'games': scrapers.GAMES_META,
    'changes': [],   # 近期变更(含已移除的条目,供统计页展示)
    'last_error': None,   # 最近一次整体刷新失败(供 /api/health 监控),成功后清空
    'last_error_at': None,
}


_INFO_KEEP_DAYS = 60   # 资讯保留窗口(与 r1999 官方源同口径),人工录入不受限


def _drop_expired(events, now=None):
    """丢弃已结束的真活动;资讯只保留近 60 天(人工录入除外)。
    do_refresh 与缓存载入共用同一口径,避免旧公告在「全部资讯」里长期堆积。"""
    now = now or _bj_now().replace(tzinfo=None)
    today = now.strftime('%Y-%m-%d')
    kept, dropped_ev, dropped_info = [], 0, 0
    for e in events:
        if (e.get('kind') or 'event') != 'event':
            if e.get('src') != 'manual' and e.get('date'):
                try:
                    days = (now - datetime.fromisoformat(str(e['date'])[:19])).days
                    if days > _INFO_KEEP_DAYS:
                        dropped_info += 1
                        continue
                except ValueError:
                    pass
            kept.append(e)
            continue
        if e.get('end') and str(e['end'])[:10] < today:
            dropped_ev += 1
            continue
        kept.append(e)
    if dropped_ev or dropped_info:
        print(f'[过滤] 丢弃 {dropped_ev} 条已过期活动、{dropped_info} 条 60 天前旧资讯')
    return kept


def _norm_title(t):
    """标题归一化:去括号补充、标点、空白,用于跨源同活动判定"""
    t = re.sub(r'[(（][^)）]*[)）]', '', str(t or ''))
    return re.sub(r'[·•\s「」【】\[\]:：\-—_/、,，]', '', t).lower()


def _dedup_against_manual(events):
    """人工核查条目优先:爬虫条目与之同游戏且标题互相包含时,丢弃爬虫版。

    版本说明文拆条会产出活动简称(如「影拓丰碑」),与人工录入的完整标题
    (「影拓丰碑·深林呓语（新系列）」)不相等,躲过原有的精确去重,导致同一活动
    在列表里出现两遍——一遍有图(manual)、一遍无图(爬虫),观感极差。
    """
    manned = {}
    for e in events:
        if e.get('src') == 'manual':
            manned.setdefault(e.get('game_id'), []).append(_norm_title(e.get('title')))
    if not manned:
        return events
    kept, dropped = [], 0
    for e in events:
        if e.get('src') == 'manual':
            kept.append(e)
            continue
        nt = _norm_title(e.get('title'))
        hit = len(nt) >= 2 and any(
            len(mt) >= 2 and (nt in mt or mt in nt)
            for mt in manned.get(e.get('game_id'), [])
        )
        if hit:
            dropped += 1
            continue
        kept.append(e)
    if dropped:
        print(f'[去重] {dropped} 条爬虫条目与人工录入是同一活动,已丢弃(保留有图的 manual 版)')
    return kept


# ================= 活动变更追踪(新增 / 改期 / 移除) =================
CHANGES_FILE = os.path.join(DATA_DIR, 'changes.json')
_CHANGE_KEEP_DAYS = 14    # 角标保留窗口:改期信息太旧会和新排期混淆
_CHANGE_STORE_DAYS = 180  # 文件保留窗口:改期次数(ICS SEQUENCE)要能长期累加
_CHANGE_MAX = 300         # 历史条目上限,防止文件无限增长


def _change_key(e):
    """变更比对主键 = 游戏 + 归一化标题。

    不能用条目自带的 id:id 是「标题|开始时间」的内容哈希,官方一改期 id 就变,
    同一条活动会被拆成「新增 + 移除」两条记录。标题才是在改期中稳定不变的锚点。
    """
    return '%s|%s' % (e.get('game_id') or '', _norm_title(e.get('title')))


def _load_changes():
    try:
        with open(CHANGES_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        items = data.get('items') if isinstance(data, dict) else None
        return items if isinstance(items, dict) else {}
    except Exception:  # noqa: BLE001 - 文件不存在/损坏都按空历史处理
        return {}


def _save_changes(items):
    try:
        with open(CHANGES_FILE, 'w', encoding='utf-8') as f:
            json.dump({'items': items}, f, ensure_ascii=False)
    except Exception as e:  # noqa: BLE001
        print(f'[变更] 保存失败: {e}')


def _prune_changes(items, now=None):
    """只保留最近 _CHANGE_STORE_DAYS 天的变更,并按时间截断到 _CHANGE_MAX 条"""
    now = now or _bj_now().replace(tzinfo=None)
    cut = (now - timedelta(days=_CHANGE_STORE_DAYS)).isoformat(timespec='seconds')
    kept = {k: v for k, v in items.items() if str((v or {}).get('at') or '') >= cut}
    if len(kept) > _CHANGE_MAX:
        newest = sorted(kept.items(), key=lambda kv: str(kv[1].get('at') or ''), reverse=True)
        kept = dict(newest[:_CHANGE_MAX])
    return kept


def _time_of(e):
    return {'start': (e or {}).get('start') or '', 'end': (e or {}).get('end') or ''}


def _track_changes(prev, cur, now=None):
    """对比上一轮与本轮的真活动,累计「新增 / 改期 / 移除」历史。

    只跟踪 kind=event:资讯类条目每天大量增删,记进来只会变成噪声。
    prev 为空(首次抓取/换库)时只做基线,不把现有活动全部标成「新增」。
    返回 history dict;当前条目上的 _change 由 _attach_changes 统一挂载。
    """
    now = now or _bj_now().replace(tzinfo=None)
    today = now.strftime('%Y-%m-%d')
    hist = _load_changes()

    def events_only(arr):
        out = {}
        for e in arr or []:
            if (e.get('kind') or 'event') == 'event':
                out.setdefault(_change_key(e), []).append(e)
        return out

    prev_map, cur_map = events_only(prev), events_only(cur)
    recorded = 0
    stamp = now.isoformat(timespec='seconds')

    def keep_rev(key):
        try:
            return int((hist.get(key) or {}).get('rev') or 0)
        except (TypeError, ValueError):
            return 0

    # 同名多期(复刻/上下半场)不能只按 key 取「最后一条」:
    # 先按时间窗精确配对,配不上的才可能是「改期 / 新增 / 移除」。
    # 否则同一标题下两条并存时,旧的一期会被误判成改期或移除,另一期也会挂上改期角标。
    for key, cur_list in cur_map.items():
        old_list = prev_map.get(key) or []
        if not old_list:
            if prev_map:   # 基线不算新增
                for e in cur_list:
                    rec = {'type': 'new', 'at': stamp,
                           'game_id': e.get('game_id'), 'title': e.get('title'),
                           'from': None, 'to': _time_of(e)}
                    rev = keep_rev(key)
                    if rev:
                        rec['rev'] = rev
                    hist[key] = rec
                    recorded += 1
            continue
        matched_old, matched_cur = set(), set()
        for i, e in enumerate(cur_list):
            for j, o in enumerate(old_list):
                if j not in matched_old and _time_of(o) == _time_of(e):
                    matched_old.add(j)
                    matched_cur.add(i)
                    break
        old_left = [j for j in range(len(old_list)) if j not in matched_old]
        cur_left = [i for i in range(len(cur_list)) if i not in matched_cur]

        def start_ts(x):
            try:
                return datetime.fromisoformat(str(x.get('start') or '')[:19]).timestamp()
            except (ValueError, TypeError):
                return None

        # 时间窗没对上但同名的,按「开始时间最接近」认成改期
        moves, used_o, used_c = [], set(), set()
        cand = []
        for j in old_left:
            for i in cur_left:
                a, b = start_ts(old_list[j]), start_ts(cur_list[i])
                cand.append((abs(a - b) if a is not None and b is not None else float('inf'), j, i))
        for _d, j, i in sorted(cand):
            if j in used_o or i in used_c:
                continue
            used_o.add(j)
            used_c.add(i)
            moves.append((j, i))

        # 移除:既没配上改期、也不是正常到期
        for j in old_left:
            if j in used_o:
                continue
            o = old_list[j]
            stop = str(o.get('end') or '')[:10]
            if stop and stop < today:
                continue   # 正常到期被清理,不是「官方移除」
            if not stop and not o.get('start'):
                continue   # 无任何时间的条目消失,无参考价值
            hist[key] = {'type': 'removed', 'at': stamp,
                         'game_id': o.get('game_id'), 'title': o.get('title'),
                         'from': _time_of(o), 'to': None}
            recorded += 1
            break   # 一个 key 只留一条摘要,多期同时消失也只报一次

        # 新增:本轮多出来的期数(没配上任何旧条目)
        for i in cur_left:
            if i in used_c or not prev_map:
                continue   # 基线不算新增
            e = cur_list[i]
            rec = {'type': 'new', 'at': stamp,
                   'game_id': e.get('game_id'), 'title': e.get('title'),
                   'from': None, 'to': _time_of(e)}
            rev = keep_rev(key)
            if rev:
                rec['rev'] = rev
            hist[key] = rec
            recorded += 1

        # 改期最后写:同轮同时出现新增/移除时,别把更有信息量的改期摘要覆盖掉
        for j, i in moves:
            o, e = old_list[j], cur_list[i]
            hist[key] = {'type': 'moved', 'at': stamp,
                         'game_id': e.get('game_id'), 'title': e.get('title'),
                         'from': _time_of(o), 'to': _time_of(e),
                         'rev': keep_rev(key) + 1}
            recorded += 1
    for key, old_list in prev_map.items():
        if key in cur_map:
            continue
        for o in old_list:
            stop = str(o.get('end') or '')[:10]
            if stop and stop < today:
                continue
            if not stop and not o.get('start'):
                continue
            hist[key] = {'type': 'removed', 'at': stamp,
                         'game_id': o.get('game_id'), 'title': o.get('title'),
                         'from': _time_of(o), 'to': None}
            recorded += 1
            break   # 一个 key 只留一条摘要,多期同时消失也只报一次
    hist = _prune_changes(hist, now)
    _save_changes(hist)
    if recorded:
        print(f'[变更] 本轮记录 {recorded} 条活动变更(新增/改期/移除)')
    return hist


def _attach_changes(events, hist=None):
    """把窗口内的「新增 / 改期」挂到当前条目上(前端据此显示角标与原时间)。

    removed 不挂:条目已不在列表里,没有可展示的宿主。
    """
    now = _bj_now().replace(tzinfo=None)
    cut = (now - timedelta(days=_CHANGE_KEEP_DAYS)).isoformat(timespec='seconds')
    hist = hist if hist is not None else _load_changes()
    for e in events or []:
        rec = hist.get(_change_key(e))
        if not rec:
            continue
        # 改期次数不限角标窗口:SEQUENCE 要在 180 天的历史里持续累加
        if rec.get('rev'):
            try:
                e['_seq'] = int(rec['rev'])
            except (TypeError, ValueError):
                pass
        if str(rec.get('at') or '') < cut:
            continue
        # 同名多期(复刻/上下半场)共用一把 key:角标只挂给时间窗与记录一致的那一期,
        # 否则旧的一期会显示成「刚刚改期/新增」
        if rec.get('type') in ('new', 'moved') and _time_of(e) != (rec.get('to') or {}):
            continue
        if rec.get('type') in ('new', 'moved'):
            e['_change'] = {k: rec.get(k) for k in ('type', 'at', 'from', 'to')}


# ================= 爬虫条目 ID 稳定化 =================
EVENT_IDS_FILE = os.path.join(DATA_DIR, 'event_ids.json')
_EVENT_ID_KEEP_DAYS = 180
_EVENT_ID_MAX = 2000


def _load_event_ids():
    try:
        with open(EVENT_IDS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        items = data.get('items') if isinstance(data, dict) else None
        return items if isinstance(items, dict) else {}
    except Exception:  # noqa: BLE001 - 文件不存在/损坏按空登记表
        return {}


def _save_event_ids(items):
    try:
        with open(EVENT_IDS_FILE, 'w', encoding='utf-8') as f:
            json.dump({'items': items}, f, ensure_ascii=False)
    except Exception as e:  # noqa: BLE001
        print(f'[ID] 保存失败: {e}')


def _stabilize_event_ids(events, now=None):
    """复用历史 ID:爬虫条目的 id 目前由「标题|开始时间」哈希派生,官方一改期就变。

    ID 同时是日历订阅的 UID 与收藏/打钩的键——跟着开始时间变,会让订阅端多出
    一条旧时间的条目,收藏也会丢。这里按「游戏+归一化标题」登记首次见到的 ID,
    同一条活动后续刷新一律复用,改期不再换 ID。

    人工条目(显式 id)与 B站条目(opus_id)本来就稳定,直接跳过。
    本轮内同一 key 出现多条时,后来者保留自己的派生 id,避免 UID 撞车。
    """
    now = now or _bj_now().replace(tzinfo=None)
    today = now.strftime('%Y-%m-%d')
    reg = _load_event_ids()
    used = set()
    for e in events or []:
        if e.get('src') in ('manual', 'bilibili'):
            used.add(e.get('id'))
            continue
        key = _change_key(e)
        rec = reg.get(key)
        cur = e.get('id')
        if rec and rec.get('id') and rec['id'] not in used:
            e['id'] = rec['id']
        elif rec:
            # 该 key 的历史 id 已被本轮另一条占用:保留本条自己的派生 id
            used.add(cur)
            rec['last_seen'] = today
            continue
        else:
            reg[key] = {'id': cur, 'last_seen': today}
        used.add(e.get('id'))
        reg[key]['last_seen'] = today
    cut = (now - timedelta(days=_EVENT_ID_KEEP_DAYS)).strftime('%Y-%m-%d')
    reg = {k: v for k, v in reg.items() if str((v or {}).get('last_seen') or '') >= cut}
    if len(reg) > _EVENT_ID_MAX:
        newest = sorted(reg.items(), key=lambda kv: str(kv[1].get('last_seen') or ''), reverse=True)
        reg = dict(newest[:_EVENT_ID_MAX])
    _save_event_ids(reg)
    return reg


def _changes_list(hist, limit=20, now=None):
    """把变更历史转成按时间倒序的列表(接口用)。removed 条目已不在活动列表里,
    只能靠这份摘要让用户知道「官方把这活动撤了」。

    文件里保留 180 天用于累计 SEQUENCE,但对外只展示角标窗口(14 天)内的记录。
    """
    now = now or _bj_now().replace(tzinfo=None)
    cut = (now - timedelta(days=_CHANGE_KEEP_DAYS)).isoformat(timespec='seconds')
    rows = []
    for key, rec in (hist or {}).items():
        if not isinstance(rec, dict) or not rec.get('type'):
            continue
        if str(rec.get('at') or '') < cut:
            continue
        rows.append({'key': key, 'type': rec.get('type'), 'at': rec.get('at'),
                     'game_id': rec.get('game_id'), 'title': rec.get('title'),
                     'from': rec.get('from'), 'to': rec.get('to')})
    rows.sort(key=lambda r: str(r.get('at') or ''), reverse=True)
    return rows[:limit]


def _strip_stale_changes(events):
    """启动载入旧缓存时清掉过期的 _change 角标(否则界面会一直显示几周前的改期)"""
    cut = (_bj_now().replace(tzinfo=None) - timedelta(days=_CHANGE_KEEP_DAYS)).isoformat(timespec='seconds')
    return [({k: v for k, v in e.items() if k != '_change'}
             if str(((e.get('_change') or {}).get('at')) or '') < cut else e)
            for e in events or []]


def _load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            # 过滤已从注册表移除的游戏(旧缓存残留)
            valid = {g['id'] for g in scrapers.GAMES_META}
            evs = [e for e in data.get('events', [])
                   if e.get('game_id') in valid or e.get('src') == 'manual']
            evs = _drop_expired(evs)                # 缓存可能落后于现实(隔天启动),过期活动不放行
            # 旧缓存可能存着跨源重复条目,载入时清掉;顺带清掉过期的改期角标
            _state['events'] = _strip_stale_changes(_dedup_against_manual(evs))
            _state['sources'] = {k: v for k, v in (data.get('sources') or {}).items()
                                 if k in valid or k == 'bilibili'}
            _state['updated'] = data.get('updated')
            _state['changes'] = _changes_list(_prune_changes(_load_changes()))
            print(f"[缓存] 已载入 {len(_state['events'])} 条事件 (更新于 {_state['updated']})")
        except Exception as e:  # noqa: BLE001
            print(f'[缓存] 载入失败: {e}')


def _save_cache():
    try:
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump({k: _state[k] for k in ('updated', 'events', 'sources')},
                      f, ensure_ascii=False)
    except Exception as e:  # noqa: BLE001
        print(f'[缓存] 保存失败: {e}')


def _manual_id(e):
    """手动条目的稳定 ID(同时是 ICS 的 UID 主键):按内容派生,不依赖数组下标。

    data/manual.json 是每日补录/重排的文件,旧写法 manual-<下标> 会把同一 UID
    复用给另一条活动(RFC5545 §3.8.4.7 要求 UID 在事件生命周期内持久稳定)。
    数据侧显式给出 id 且为安全字符集([A-Za-z0-9_.:-])时优先用它;该值会进
    前端内联 onclick 与 ICS 属性,不收其它字符。

    派生键**不含 start**:官方改期后 UID 若跟着变,日历订阅端会留下旧时间的
    旧条目、再冒出一条新条目(用户看到同活动两份)。现网 197 条已在 manual.json
    固化显式 id;未写 id 的新条目按「游戏+标题」派生,改期也能原地更新。
    同一游戏出现同名活动(复刻/多期)时请显式给不同的 id,避免 UID 撞车。
    """
    raw = str(e.get('id') or '')
    # 显式 id 只收安全字符集:该值会进前端内联 onclick 与 ICS 属性
    if re.fullmatch(r'[A-Za-z0-9_.:-]{1,64}', raw):
        return raw
    key = f"{e.get('game_id', '')}|{e.get('title', '')}"
    return 'manual-' + hashlib.md5(key.encode('utf-8')).hexdigest()[:8]


def _manual_events():
    """读取 data/manual.json 中的手动添加事件

    无结束时间的条目在此**不补** end:补出来的合成值会进入 validate_events 的时长校验,
    起点晚于 22:00 的条目必然被判「时长过短」降级。默认窗口只由消费点负责
    (api_ics() 与前端 evEnd() 同一口径:起点 + 2 天,与抓取条目一致,见 Issue #34)。
    """
    path = os.path.join(DATA_DIR, 'manual.json')
    if not os.path.exists(path):
        return []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            arr = json.load(f)
        names = {g['id']: g['name'] for g in scrapers.GAMES_META}
        out = []
        for e in arr:
            if not isinstance(e, dict) or 'title' not in e:
                continue  # 跳过说明性条目
            gid = e.get('game_id', '')
            start = e.get('start') or None
            end = e.get('end') or None
            # 签到（N日）类手动条目:标题已写明时长,补出真实结束时间(与 scrapers._ev 同口径)
            n = scrapers._signin_days(e.get('title', ''))
            if start and not end and n:
                try:
                    end = (datetime.fromisoformat(str(start)) + timedelta(days=n)).isoformat(timespec='seconds')
                except ValueError:
                    pass
            out.append({
                'id': _manual_id(e),
                'game_id': gid,
                'game': names.get(gid, e.get('game') or gid or '自定义'),
                'title': e.get('title', '未命名事件'),
                'category': e.get('category', '活动'),
                'start': start,
                'end': end,
                'date': start or datetime.now().isoformat(timespec='seconds'),
                'link': e.get('link', ''),
                'image': e.get('image', ''),
                'src': 'manual',
                'kind': e.get('kind', 'event'),  # 手动填入默认上月历
            })
        return out
    except Exception as e:  # noqa: BLE001
        print(f'[手动事件] 读取失败: {e}')
        return []


def _stamp_sources(sources, prev, stamp=None):
    """给每个数据源记「最近一次成功时间」;本轮失败的源沿用上一次的 last_ok。

    只给前端/health 看,不参与抓取逻辑;失败源保留旧值,便于判断「失败多久了」。
    """
    stamp = stamp or datetime.now().isoformat(timespec='seconds')
    out = dict(sources or {})
    for k, st in out.items():
        if not isinstance(st, dict):
            continue
        if st.get('ok'):
            st['last_ok'] = stamp
        else:
            old = (prev or {}).get(k) or {}
            if old.get('last_ok'):
                st['last_ok'] = old['last_ok']
    return out


def do_refresh():
    with _lock:
        if _state['refreshing']:
            return False
        _state['refreshing'] = True
    try:
        print(f"[抓取] {datetime.now():%H:%M:%S} 开始刷新...")
        events, sources = scrapers.fetch_all()
        try:
            bev, bstat = bilibili.fetch_all()
            events.extend(bev)
            sources['bilibili'] = bstat
        except Exception as e:  # noqa: BLE001
            sources['bilibili'] = {'name': 'B站动态', 'ok': False, 'count': 0, 'error': str(e)[:120]}
        events.extend(_manual_events())
        # 降级容错:本轮失败的源沿用上一轮该源的条目,避免一次网络抖动让整源活动消失 30 分钟
        with _lock:
            prev_all = list(_state['events'])
            prev_by_src = {}
            for e in prev_all:
                prev_by_src.setdefault(e.get('src'), []).append(e)
        for src_name, st in list(sources.items()):
            if not (st or {}).get('ok'):
                have = [e for e in events if e.get('src') == src_name]
                old = prev_by_src.get(src_name) or []
                if not have and old:
                    events.extend(old)
                    print(f'[降级] {src_name} 本轮失败,沿用上轮 {len(old)} 条(下轮重试)')
        # 统一去重(同游戏同标题):手动录入的条目经人工核实,优先保留
        seen = {}
        for e in events:
            key = (e.get('game_id'), e.get('title'))
            old = seen.get(key)
            if old is None or (e.get('src') == 'manual' and old.get('src') != 'manual'):
                seen[key] = e
        events = list(seen.values())
        # 过滤已结束的真活动(info/公告类保留,历史资讯仍有参考价值)
        events = _drop_expired(events)
        # 跨源同活动去重:人工核查条目优先(爬虫拆条会产出无图简称副本)
        events = _dedup_against_manual(events)
        # 合并全部来源(抓取/手动)后统一校验,与 App 端 scraper.js::fetchAll 的时机一致
        scrapers.validate_events(events)
        events.sort(key=lambda e: (e['start'] or e['date'] or ''), reverse=True)
        # 复用历史 ID(改期不换 UID,收藏/打钩不丢),再做变更对比
        _stabilize_event_ids(events)
        # 与上一轮对比,记录官方新增/改期/移除,并把近期变更挂到条目上(前端角标)
        hist = _track_changes(prev_all, events)
        _attach_changes(events, hist)
        with _lock:
            sources = _stamp_sources(sources, _state.get('sources') or {})
            _state['events'] = events
            _state['changes'] = _changes_list(hist)
            _state['sources'] = sources
            _state['updated'] = datetime.now().isoformat(timespec='seconds')
            _state['last_error'] = None
            _state['last_error_at'] = None
            _state['refreshing'] = False
        _save_cache()
        ok = sum(1 for s in sources.values() if s['ok'])
        print(f'[抓取] 完成: {ok}/{len(sources)} 个源成功, 共 {len(events)} 条事件')
        return True
    except Exception as e:  # noqa: BLE001
        with _lock:
            _state['refreshing'] = False
            _state['last_error'] = str(e)[:200]
            _state['last_error_at'] = datetime.now().isoformat(timespec='seconds')
            # 全链路崩了也要让前端可见:旧数据继续展示,来源区标记本轮刷新失败
            _state['sources'] = {**(_state.get('sources') or {}),
                                 '_system': {'name': '本轮抓取', 'ok': False, 'count': 0,
                                             'error': f'{str(e)[:110]}(已沿用上一轮数据)'}}
        print(f'[抓取] 失败: {e}')
        return False


_REFRESH_RETRY = 5 * 60   # 整体刷新失败后 5 分钟补试一次,避免一次网络抖动空窗半小时

def _refresh_loop():
    while True:
        time.sleep(REFRESH_INTERVAL)
        if not do_refresh():   # 失败(或与手动刷新撞车)时补试一次
            time.sleep(_REFRESH_RETRY)
            do_refresh()


@app.route('/')
def index():
    resp = send_from_directory(app.static_folder, 'index.html')
    resp.headers['Cache-Control'] = 'no-cache'  # 每次协商,杜绝浏览器启发式缓存旧页面
    return resp


@app.after_request
def _no_cache_static(resp):
    """HTML/JS 每次协商更新(由 SW 或 304 保证速度);图片代理自带长缓存头不动"""
    ct = resp.headers.get('Content-Type', '')
    if 'text/html' in ct or 'javascript' in ct or 'manifest+json' in ct:
        resp.headers.setdefault('Cache-Control', 'no-cache')
    return resp


_GZIP_TYPES = ('text/html', 'text/javascript', 'application/javascript',
               'application/json', 'application/manifest+json', 'text/plain',
               'text/calendar')


@app.after_request
def _gzip_text_resp(resp):
    """文本响应按 Accept-Encoding 压缩:首屏 index.html 106KB → 约 20KB。

    SW 每次版本升级都会重新拉 index/manual-data/scraper 三个文本资源,
    远程(Tailscale)访问时未压缩合计约 220KB,压缩后约 45KB。
    图片/已压缩响应(带 Content-Encoding)与 304 不处理;浏览器透明解压,
    前端代码无需改动。
    """
    try:
        if resp.status_code != 200 or resp.headers.get('Content-Encoding'):
            return resp
        if resp.mimetype not in _GZIP_TYPES:
            return resp
        if 'gzip' not in (request.headers.get('Accept-Encoding') or '').lower():
            return resp
        resp.direct_passthrough = False
        data = resp.get_data()
        if len(data) < 1024:
            return resp
        resp.set_data(gzip.compress(data, 6))
        resp.headers['Content-Encoding'] = 'gzip'
        resp.headers['Vary'] = 'Accept-Encoding'
    except Exception:  # noqa: BLE001 - 压缩失败退回未压缩响应,不影响功能
        return resp
    return resp


@app.route('/scraper.js')
def scraper_js():
    return send_from_directory(app.static_folder, 'scraper.js')


@app.route('/manual-data.js')
def manual_data_js():
    return send_from_directory(app.static_folder, 'manual-data.js', mimetype='text/javascript')


@app.route('/manifest.webmanifest')
def manifest():
    return send_from_directory(app.static_folder, 'manifest.webmanifest',
                               mimetype='application/manifest+json')


@app.route('/sw.js')
def sw_js():
    return send_from_directory(app.static_folder, 'sw.js', mimetype='text/javascript')


@app.route('/icon-<int:size>.png')
def icon(size):
    name = {192: 'icon-192.png', 512: 'icon-512.png'}.get(size)
    if not name:
        return jsonify({'error': 'not found'}), 404
    return send_from_directory(app.static_folder, name)


THUMB_DIR = os.path.join(app.static_folder, 'thumb')
THUMB_MAX = 200   # 列表行 40px(2x 屏 80px),200px 足够且比原图小一个量级


@app.route('/api/thumb')
def api_thumb():
    """本地封面图的缩略图:按需压缩(默认 200px,?w=800 用于详情大图)并缓存。

    原图动辄几百 KB,首屏几十张 40px 缩略图直接拉原图很慢;这里只接受
    /static/img/ 下的文件,不开放任意路径/远程地址。压缩失败退回原图。
    """
    raw = str(request.args.get('path') or '')
    if not raw.startswith('/static/img/'):
        return jsonify({'error': 'bad path'}), 400
    src = os.path.join(app.static_folder, raw[len('/static/'):])
    try:
        root = os.path.realpath(app.static_folder)
        real = os.path.realpath(src)
        if os.path.commonpath([real, root]) != root:
            return jsonify({'error': 'bad path'}), 400
    except ValueError:
        return jsonify({'error': 'bad path'}), 400
    if not os.path.isfile(real):
        return jsonify({'error': 'not found'}), 404
    try:
        want_w = int(request.args.get('w') or THUMB_MAX)
    except ValueError:
        want_w = THUMB_MAX
    width = want_w if 80 <= want_w <= 1200 else THUMB_MAX   # 列表 200 / 详情大图 800
    rel = os.path.relpath(real, os.path.join(app.static_folder, 'img'))
    stem = os.path.splitext(rel)[0]
    dst = os.path.join(THUMB_DIR, stem + ('' if width == THUMB_MAX else '@%d' % width) + '.jpg')
    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if not os.path.exists(dst) or os.path.getmtime(dst) < os.path.getmtime(real):
            small = _shrink_image(open(real, 'rb').read(), width)
            if not small:
                return send_file(real)
            with open(dst, 'wb') as f:
                f.write(small)
    except Exception:  # noqa: BLE001 - 压缩失败退回原图,不影响列表
        return send_file(real)
    resp = send_file(dst, mimetype='image/jpeg')
    resp.headers['Cache-Control'] = 'public, max-age=604800'
    return resp


@app.route('/api/events')
def api_events():
    """事件全量接口:带 ETag,数据没变时浏览器拿 304;支持 gzip。

    前端每 60 秒轮询一次,整包约 130KB。带 ETag 后未刷新时只有几百字节的
    304 往返;首次/刷新后则按 Accept-Encoding 压成 gzip(实测 130KB → 约 15KB,
    Tailscale 外网访问时尤其省流量)。ETag 取 updated(每轮刷新必变)+ 事件数
    + 变更数,足够区分状态;弱 ETag 不区分编码,304 本来就没有响应体。
    """
    with _lock:
        etag = 'W/"%s-%d-%d"' % (_state.get('updated') or '0',
                                 len(_state.get('events') or []),
                                 len(_state.get('changes') or []))
    headers = {'ETag': etag, 'Cache-Control': 'no-cache',
               'Vary': 'Accept-Encoding'}
    if request.headers.get('If-None-Match') == etag:
        return Response(status=304, headers=headers)
    with _lock:
        payload = jsonify(_state)
    data = payload.get_data()
    if 'gzip' in (request.headers.get('Accept-Encoding') or '').lower():
        data = gzip.compress(data, 6)
        headers['Content-Encoding'] = 'gzip'
    return Response(data, mimetype='application/json', headers=headers)


def _start_refresh():
    """后台触发一次刷新;已有刷新在进行中则返回 False"""
    with _lock:
        if _state['refreshing']:
            return False
    threading.Thread(target=do_refresh, daemon=True).start()
    return True


@app.route('/api/refresh', methods=['POST'])
def api_refresh():
    # 简单 CSRF 防护:跨站简单请求带不了自定义头,可阻止恶意网页触发本服务抓取
    if request.headers.get('X-Requested-With') != 'ycal':
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    # 刷新在后台执行,接口立即返回;前端轮询 /api/events 等 updated 变化即可
    started = _start_refresh()
    with _lock:
        return jsonify({'ok': True, 'started': started, 'updated': _state['updated']})


# ================= 备忘录(每周待办) =================
TODO_FILE = os.path.join(DATA_DIR, 'todo.json')
_todo_lock = threading.Lock()


_TODO_ID_RE = re.compile(r'[A-Za-z0-9_-]{1,40}')


def _todo_id(raw, fallback=''):
    """备忘录 id 归一化:只放行 [A-Za-z0-9_-] 且不超 40 字符。

    id 会作为属性值渲染到前端(见 index.html::noteHtml),引号/括号/分号等非法字符
    与超长值一律回退为 fallback(f't<序号>'),避免脏数据逃出属性进入可执行上下文。
    """
    s = str(raw or '')
    return s if _TODO_ID_RE.fullmatch(s) else fallback


def _todo_used_id(raw, used):
    """归一化 id 并保证同批唯一:非法值与已被占用的值都补一个空闲的 t<序号>。

    归一化会把「原本唯一但脏」的历史 id 折成同一个兜底值,若不比对 used,
    两条不同条目会共用 id,前端按 id 定位的删除/打钩就会误伤相邻条目。
    """
    _id = _todo_id(raw)
    if not _id or _id in used:
        n = len(used)
        while f't{n}' in used:
            n += 1
        _id = f't{n}'
    used.add(_id)
    return _id


def _load_todo():
    if os.path.exists(TODO_FILE):
        try:
            with open(TODO_FILE, 'r', encoding='utf-8') as f:
                d = json.load(f)
            if isinstance(d, dict) and isinstance(d.get('items'), list):
                # 读取侧同样归一化:历史脏数据(旧版本原样保存)不得带病回流到前端
                used = set()
                for it in d['items']:
                    if isinstance(it, dict):
                        it['id'] = _todo_used_id(it.get('id'), used)
                return d
        except Exception as e:  # noqa: BLE001
            print(f'[备忘录] 读取失败: {e}')
    return {'items': []}


@app.route('/api/todo', methods=['GET', 'POST'])
def api_todo():
    """待办清单:GET 读取,POST 整体覆盖保存(前端负责每周重置判定)"""
    if request.method == 'GET':
        return jsonify(_load_todo())
    # 与 /api/refresh 同样的简单 CSRF 防护
    if request.headers.get('X-Requested-With') != 'ycal':
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    body = request.get_json(silent=True) or {}
    items = body.get('items')
    if not isinstance(items, list):
        return jsonify({'ok': False, 'error': 'items required'}), 400
    clean = []
    used = set()
    for it in items[:200]:  # 上限保护,避免异常数据撑爆文件
        if not isinstance(it, dict):
            continue
        title = str(it.get('title') or '').strip()[:60]
        if not title:
            continue
        clean.append({
            'id': _todo_used_id(it.get('id'), used),
            'game_id': str(it.get('game_id') or ''),
            'title': title,
            'cycle': 'weekly' if it.get('cycle') == 'weekly' else 'once',
            'done': bool(it.get('done')),
            'done_week': str(it.get('done_week') or '')[:10],
        })
    with _todo_lock:
        try:
            with open(TODO_FILE, 'w', encoding='utf-8') as f:
                json.dump({'items': clean, 'updated': datetime.now().isoformat(timespec='seconds')},
                          f, ensure_ascii=False, indent=1)
            ok = True
        except Exception as e:  # noqa: BLE001
            print(f'[备忘录] 保存失败: {e}')
            ok = False
    return jsonify({'ok': ok, 'count': len(clean)})


# ================= 打钩/收藏多设备同步 =================
USERSTATE_FILE = os.path.join(DATA_DIR, 'userstate.json')
_userstate_lock = threading.Lock()
_USERSTATE_MAX = 600          # 每个集合的键上限(超出按时间戳保留最新的)
_TS_MAX = 10 ** 13            # 合法毫秒时间戳上限,防异常数据


def _load_userstate():
    """读取已保存的打钩/收藏状态。

    值是「有符号毫秒时间戳」:正数=已标记(值为操作时间),负数=已取消(绝对值为取消时间)。
    用符号表示撤销、用绝对值比新旧,这样多设备并发时也能正确合并(plain 0 无法比大小)。
    """
    out = {'done': {}, 'fav': {}}
    try:
        with open(USERSTATE_FILE, 'r', encoding='utf-8-sig') as f:
            d = json.load(f)
    except Exception:  # noqa: BLE001
        return out
    for kind in ('done', 'fav'):
        v = d.get(kind) if isinstance(d, dict) else None
        if not isinstance(v, dict):
            continue
        for key, ts in v.items():
            if isinstance(ts, (int, float)) and 0 < abs(int(ts)) <= _TS_MAX:
                out[kind][str(key)[:120]] = int(ts)
    return out


def _merge_userstate(cur, inc):
    """按键合并:绝对值较大(更晚)的一方胜出,符号决定状态 → last-writer-wins"""
    for kind in ('done', 'fav'):
        src = inc.get(kind)
        if not isinstance(src, dict):
            continue
        dst = cur.setdefault(kind, {})
        for key, ts in src.items():
            if not isinstance(ts, (int, float)):
                continue
            ts = int(ts)
            if ts == 0 or abs(ts) > _TS_MAX:
                continue
            key = str(key)[:120]
            if abs(ts) > abs(dst.get(key, 0)):
                dst[key] = ts
        if len(dst) > _USERSTATE_MAX:
            for k in sorted(dst, key=lambda x: abs(dst[x]))[:len(dst) - _USERSTATE_MAX]:
                dst.pop(k, None)
    return cur


@app.route('/api/userstate', methods=['GET', 'POST'])
def api_userstate():
    """打钩/收藏状态跨设备同步:GET 读取全量,POST 增量合并(键=game_id|title)"""
    if request.method == 'GET':
        with _userstate_lock:
            return jsonify(_load_userstate())
    # 与 /api/refresh、/api/todo 同样的简单 CSRF 防护
    if request.headers.get('X-Requested-With') != 'ycal':
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return jsonify({'ok': False, 'error': 'bad body'}), 400
    with _userstate_lock:
        cur = _merge_userstate(_load_userstate(), body)
        try:
            with open(USERSTATE_FILE, 'w', encoding='utf-8') as f:
                json.dump({'done': cur['done'], 'fav': cur['fav'],
                           'updated': datetime.now().isoformat(timespec='seconds')},
                          f, ensure_ascii=False, indent=1)
            ok = True
        except Exception as e:  # noqa: BLE001
            print(f'[状态] 保存失败: {e}')
            ok = False
    return jsonify({'ok': ok, 'done': cur['done'], 'fav': cur['fav']})


# ================= 用户报错/缺图反馈 =================
REPORT_FILE = os.path.join(DATA_DIR, 'reports.json')
_report_lock = threading.Lock()
_REPORT_MAX = 300
_REPORT_KINDS = ('missing-image', 'wrong-time', 'other', 'no-end')


def _load_reports():
    try:
        with open(REPORT_FILE, 'r', encoding='utf-8-sig') as f:
            d = json.load(f)
        items = d.get('items') if isinstance(d, dict) else None
        return items if isinstance(items, list) else []
    except Exception:  # noqa: BLE001
        return []


def _report_title_match(report_title, event_title):
    """反馈标题与活动标题是否同一条:完全相等,或反馈标题达到 120 字截断上限时按前缀匹配"""
    rt = str(report_title or '')
    et = str(event_title or '')
    return rt == et or (len(rt) >= 120 and et.startswith(rt))


def _autoclose_reports(items):
    """数据已补全的待核查反馈自动标记 done:
    no-end → 该活动现在有结束时间;missing-image → 该活动现在有封面;
    wrong-time → 同游戏同标题的活动已找不到「反馈时的开始/结束」这一版(说明时间已被更正)。
    只在同游戏、同标题(超长标题按截断前缀)、且报告带开始日期时要求日期一致,避免同名活动误关。"""
    with _lock:
        events = list(_state['events'])
    idx = {}
    for e in events:
        idx.setdefault((e.get('game_id') or ''), []).append(e)
    changed = 0
    for it in items:
        if it.get('done'):
            continue
        kind = it.get('kind')
        if kind not in ('no-end', 'missing-image', 'wrong-time'):
            continue
        cands = idx.get(str(it.get('game_id') or ''))
        if not cands:
            continue
        if kind == 'wrong-time':
            # 没有记录反馈时的开始时间就无法判断是否改过,保持待核查
            if not str(it.get('start') or ''):
                continue
            snap = (str(it.get('start') or ''), str(it.get('end') or ''))
            matched = [e for e in cands if _report_title_match(it.get('title'), e.get('title'))]
            # 同名多期时,只要还有一期与反馈快照完全一致就不算已更正
            if matched and not any(
                    (str(e.get('start') or ''), str(e.get('end') or '')) == snap for e in matched):
                it['done'] = True
                it['note'] = ((it.get('note') or '') + ('；' if it.get('note') else '')
                              + '自动核实: 时间已更正')[:200]
                changed += 1
            continue
        rstart = str(it.get('start') or '')[:10]
        hit = ''
        for e in cands:
            if not _report_title_match(it.get('title'), e.get('title')):
                continue
            estart = str(e.get('start') or '')[:10]
            if rstart and estart and rstart != estart:
                continue
            if kind == 'no-end':
                if e.get('end'):
                    hit = '已补到结束时间'
                    break
                if _is_point_item(e):
                    # 版本上线 / 前瞻直播本来就没有结束时间,反馈不需要人工再补,直接收尾
                    hit = '单点里程碑无需结束时间'
                    break
            if kind == 'missing-image' and (e.get('image') or '').strip():
                hit = '封面已补'
                break
        if not hit:
            continue
        it['done'] = True
        it['note'] = ((it.get('note') or '') + ('；' if it.get('note') else '') + '自动核实: ' + hit)[:200]
        changed += 1
    return changed


@app.route('/api/report', methods=['GET', 'POST', 'DELETE'])
def api_report():
    """用户反馈:GET 读清单(数据补全时自动标记已处理),POST 追加,DELETE 撤回/清除"""
    if request.method == 'GET':
        with _report_lock:
            items = _load_reports()
            changed = _autoclose_reports(items)
            if changed:
                try:
                    with open(REPORT_FILE, 'w', encoding='utf-8') as f:
                        json.dump({'items': items}, f, ensure_ascii=False, indent=1)
                except Exception as e:  # noqa: BLE001
                    print(f'[反馈] 自动处理状态保存失败: {e}')
            return jsonify({'items': items})
    # 与 /api/refresh、/api/todo 同样的简单 CSRF 防护
    if request.headers.get('X-Requested-With') != 'ycal':
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    body = request.get_json(silent=True) or {}
    if request.method == 'DELETE':
        if body.get('done') is True:            # 清除全部已处理反馈(保留待核查)
            with _report_lock:
                items = _load_reports()
                keep = [it for it in items if not it.get('done')]
                removed = len(items) - len(keep)
                if not removed:
                    return jsonify({'ok': False, 'removed': 0, 'error': 'not found'})
                try:
                    with open(REPORT_FILE, 'w', encoding='utf-8') as f:
                        json.dump({'items': keep}, f, ensure_ascii=False, indent=1)
                except Exception as e:  # noqa: BLE001
                    print(f'[反馈] 清除已处理失败: {e}')
                    return jsonify({'ok': False, 'removed': 0, 'error': 'save failed'})
            return jsonify({'ok': True, 'removed': removed, 'count': len(keep)})
        at = str(body.get('at') or '')
        if not at:
            return jsonify({'ok': False, 'error': 'at required'}), 400
        title = str(body.get('title') or '').strip()[:120]
        game_id = str(body.get('game_id') or '')[:20]
        kind = str(body.get('kind') or '')
        with _report_lock:
            items = _load_reports()
            keep = [it for it in items if not (
                str(it.get('at')) == at and it.get('title') == title
                and str(it.get('game_id') or '') == game_id
                and str(it.get('kind') or '') == kind
                and not it.get('done'))]
            removed = len(items) - len(keep)
            if not removed:
                return jsonify({'ok': False, 'removed': 0, 'error': 'not found'})
            try:
                with open(REPORT_FILE, 'w', encoding='utf-8') as f:
                    json.dump({'items': keep}, f, ensure_ascii=False, indent=1)
            except Exception as e:  # noqa: BLE001
                print(f'[反馈] 撤回保存失败: {e}')
                return jsonify({'ok': False, 'removed': 0, 'error': 'save failed'})
        return jsonify({'ok': True, 'removed': removed, 'count': len(keep)})
    title = str(body.get('title') or '').strip()[:120]
    if not title:
        return jsonify({'ok': False, 'error': 'title required'}), 400
    kind = body.get('kind') if body.get('kind') in _REPORT_KINDS else 'other'
    now = datetime.now()
    item = {
        'game_id': str(body.get('game_id') or '')[:20],
        'title': title,
        'kind': kind,
        'note': str(body.get('note') or '').strip()[:200],
        'start': str(body.get('start') or '')[:19],
        'end': str(body.get('end') or '')[:19],
        'link': str(body.get('link') or '')[:300],
        'at': now.isoformat(timespec='seconds'),
        'done': False,
    }
    with _report_lock:
        items = _load_reports()
        for old in items:
            if (old.get('game_id') == item['game_id'] and old.get('title') == title
                    and old.get('kind') == kind and not old.get('done')):
                try:
                    if (now - datetime.fromisoformat(str(old.get('at')))).total_seconds() < 600:
                        return jsonify({'ok': True, 'duplicate': True})
                except ValueError:
                    pass
        items.append(item)
        items = items[-_REPORT_MAX:]
        try:
            with open(REPORT_FILE, 'w', encoding='utf-8') as f:
                json.dump({'items': items}, f, ensure_ascii=False, indent=1)
            ok = True
        except Exception as e:  # noqa: BLE001
            print(f'[反馈] 保存失败: {e}')
            ok = False
    return jsonify({'ok': ok, 'count': len(items)})


# ================= 提醒配置(notify.json 的 API 化) =================
def _save_notify_cfg(cfg):
    with open(NOTIFY_FILE, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


@app.route('/api/notify-config', methods=['GET', 'POST'])
def api_notify_config():
    """提醒配置:GET 返回脱敏视图(不回传 webhook 凭据),POST 局部更新(未提交的字段保留原值)"""
    cfg = _notify_config()
    if request.method == 'GET':
        return jsonify({'time': cfg.get('time') or '08:30',
                        'lead_days': _lead_days(cfg),
                        'end_lead_days': _end_lead(cfg),
                        'evening': cfg.get('evening') or '',
                        'fav_only': bool(cfg.get('fav_only')),
                        'has_webhook': bool((cfg.get('webhook') or '').strip())})
    if request.headers.get('X-Requested-With') != 'ycal':
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    body = request.get_json(silent=True) or {}
    # 推送时刻:HH:MM 校验
    if 'time' in body:
        t = str(body.get('time') or '').strip()
        try:
            hh, mm = map(int, t.split(':'))
            assert 0 <= hh <= 23 and 0 <= mm <= 59
        except Exception:  # noqa: BLE001
            return jsonify({'ok': False, 'error': 'bad time'}), 400
        cfg['time'] = f'{hh:02d}:{mm:02d}'
    # 提前量:只放行 0/1/3
    if 'lead_days' in body:
        cfg['lead_days'] = _lead_days({'lead_days': body.get('lead_days')})
    # 结束提醒提前量:只放行 0/1/2/3(今天起 N+1 天)
    if 'end_lead_days' in body:
        cfg['end_lead_days'] = _end_lead({'end_lead_days': body.get('end_lead_days')})
    # 晚间二次提醒:HH:MM 或空串(空 = 关闭)
    if 'evening' in body:
        t = str(body.get('evening') or '').strip()
        if t:
            try:
                hh, mm = map(int, t.split(':'))
                assert 0 <= hh <= 23 and 0 <= mm <= 59
            except Exception:  # noqa: BLE001
                return jsonify({'ok': False, 'error': 'bad evening'}), 400
            cfg['evening'] = f'{hh:02d}:{mm:02d}'
        else:
            cfg['evening'] = ''
    # 只推送收藏的活动:布尔开关(收藏状态来自 data/userstate.json)
    if 'fav_only' in body:
        cfg['fav_only'] = bool(body.get('fav_only'))
    # webhook:空串=清除;http(s) 才收(防 file:// 等奇形怪状值)
    if 'webhook' in body:
        w = str(body.get('webhook') or '').strip()
        if w and not w.lower().startswith(('http://', 'https://')):
            return jsonify({'ok': False, 'error': 'bad webhook'}), 400
        cfg['webhook'] = w
    try:
        _ensure_notify_file()
        _save_notify_cfg(cfg)
    except Exception as e:  # noqa: BLE001
        print(f'[提醒] 配置保存失败: {e}')
        return jsonify({'ok': False, 'error': 'io'}), 500
    return jsonify({'ok': True, 'time': cfg.get('time') or '08:30',
                    'lead_days': _lead_days(cfg),
                    'end_lead_days': _end_lead(cfg),
                    'evening': cfg.get('evening') or '',
                    'fav_only': bool(cfg.get('fav_only')),
                    'has_webhook': bool((cfg.get('webhook') or '').strip())})


@app.route('/api/notify-test', methods=['POST'])
def api_notify_test():
    """设置面板的「发送测试消息」:立刻向已保存的 webhook 推一条,并回传可读结果。

    单靠每日定时推送排查成本太高(要等到点才知道通不通),这个接口让用户当场
    确认飞书/Bark 是否收到。只读已保存的地址,不允许把任意 URL 借道转发。
    """
    if request.headers.get('X-Requested-With') != 'ycal':
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    url = (_notify_config().get('webhook') or '').strip()
    if not url:
        return jsonify({'ok': False, 'error': '还没有填写推送地址'}), 400
    now = _bj_now()
    ok, detail = _post_webhook(
        url, '二游活动日历',
        '这是一条测试消息 ✅ 如果收到说明推送配置正常。\n'
        f'发送时间:{now.strftime("%Y-%m-%d %H:%M")}')
    return jsonify({'ok': ok, 'detail': detail, 'time': now.strftime('%H:%M')})


# ================= ICS 日历订阅 =================
_CST = timezone(timedelta(hours=8))  # 数据时间为北京时间


def _ics_escape(s):
    return str(s or '').replace('\\', '\\\\').replace(';', '\\;').replace(',', '\\,').replace('\n', ' ')


def _ics_fold(line, limit=75):
    """ICS 行折叠(RFC5545 §3.1):按 UTF-8 octet 计数,超 75 折行,续行以单空格开头。

    中文标题按 UTF-8 每字 3 字节,很易越线;折行时不得把多字节字符劈成两半。
    """
    data = str(line).encode('utf-8')
    if len(data) <= limit:
        return line
    chunks, i, size = [], 0, limit
    while i < len(data):
        chunk = data[i:i + size]
        # 回退到字符边界:截断处可能落在多字节字符中间,逐字节回退直到能解码
        while chunk:
            try:
                chunk.decode('utf-8')
                break
            except UnicodeDecodeError:
                chunk = chunk[:-1]
        chunks.append(chunk.decode('utf-8'))
        i += len(chunk)
        size = limit - 1  # 续行首字符是被折叠出来的空格
    return '\r\n '.join(chunks)


def _default_end(start_iso):
    """无结束时间时的默认窗口:起点 + 2 天(仅消费点兜底)。

    与抓取条目同一口径(_ev → timeparse.with_two_day_default 也是补 2 天):
    缺结束时间的活动在「抓取 / 手动」两条道、PC 与 App 两端都补 2 天,
    不再出现以前「抓取补 2 天、手动补当天末」的分叉(Issue #34)。
    前端 evEnd() 与 ICS DTEND 统一用这个口径。不在 _manual_events() 里补:
    合成 end 会进 validate_events 的时长校验,起点晚于 22:00 的条目会被降级(Issue #13)。
    起点落在 datetime.max 附近时补窗会越界,此时放弃结束时间(返回 None),与两端同口径。
    """
    try:
        s = datetime.fromisoformat(str(start_iso))
    except (ValueError, TypeError):
        return None
    try:
        return (s + timedelta(days=2)).isoformat(timespec='seconds')
    except OverflowError:
        return None


_STALE_UNKNOWN_DAYS = 30

# 单点里程碑:版本上线 / 前瞻直播这类只有开始时刻、没有持续期的条目。
# 它们本来就没有结束时间,不该算「缺结束」「更早开始未知」,也不该冒充「进行中」。
_POINT_TITLE_RE = re.compile(r'(\d+\.\d+\s*版本.*上线)|(正式上线)|(前瞻.*(节目|通讯|直播))')


def _is_point_item(e):
    """是否为单点里程碑(与前端 isPointItem() 同一正则)。"""
    e = e or {}
    if (e.get('kind') or 'event') != 'event':
        return False
    return bool(_POINT_TITLE_RE.search(str(e.get('title') or '')))


def _is_stale_unknown(e, now=None):
    """开始超过 30 天仍无结束时间:不构成「进行中」,也不进订阅。

    与前端 isStaleUnknown() 逐秒同口径(now - 30 天,而不是只看日期),
    避免「30 天前 20:00 开始的条目页面已折叠、订阅却还挂着」这种半天的分叉。
    只有日期没有时分的 start 按当天 0 点算,两端都是这个行为。
    单点里程碑(版本上线/前瞻直播)本来就没有结束时间,不在此列。
    """
    e = e or {}
    if _is_point_item(e):
        return False
    start = e.get('start')
    if not start or e.get('end'):
        return False
    try:
        s = datetime.fromisoformat(str(start)[:19])
    except (ValueError, TypeError):
        return False
    now = now or _bj_now().replace(tzinfo=None)
    return s < now - timedelta(days=_STALE_UNKNOWN_DAYS)


def _is_ongoing(e, now=None):
    """与前端 isOngoingEvent() 同一口径:已开始且(有结束就比结束,无结束排除历史条目与单点里程碑)"""
    now = now or _bj_now().replace(tzinfo=None)
    e = e or {}
    if _is_point_item(e):
        return False
    try:
        s = datetime.fromisoformat(str(e.get('start') or '')[:19])
    except (ValueError, TypeError):
        return False
    if s > now:
        return False
    end = e.get('end')
    if end:
        try:
            return datetime.fromisoformat(str(end)[:19]) >= now
        except (ValueError, TypeError):
            return False
    return not _is_stale_unknown(e, now)


def _ics_utc(iso, day_end=False):
    """本地 ISO 时间串 → ICS UTC 时间;day_end=True 且无时分则取当天 23:59"""
    try:
        dt = datetime.fromisoformat(str(iso))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_CST)
    if day_end and not (dt.hour or dt.minute or dt.second):
        dt = dt.replace(hour=23, minute=59)
    return dt.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')


@app.route('/api/calendar.ics')
def api_ics():
    """ICS 订阅源:系统日历/Google 日历可直接订阅(仅真活动,含手动录入)

    带 ETag:日历客户端（Apple/Google）周期拉取时数据没变就只回 304,
    不必每次重新生成并传输整份日历。
    """
    now = datetime.now(_CST).strftime('%Y%m%dT%H%M%SZ')
    with _lock:
        events = list(_state['events'])
        updated = _state.get('updated') or '0'
    # ?games=hsr,zzz:只订阅自己玩的游戏(逗号分隔;未知 id 自然筛不出事件,无需白名单)
    games = {g.strip() for g in (request.args.get('games') or '').split(',') if g.strip()}
    # ?cats=活动,签到:只订阅指定分类(角色与专武/公告/资讯同理)
    cats = {c.strip() for c in (request.args.get('cats') or '').split(',') if c.strip()}
    # ?fav=1:只订阅收藏的活动(收藏状态来自 data/userstate.json,键= game_id|title)
    fav_flag = request.args.get('fav') in ('1', 'true', 'yes')
    fav_keys = set()
    if fav_flag:
        fav = _load_userstate().get('fav') or {}
        fav_keys = {k for k, v in fav.items() if v > 0}
    # 收藏变化不一定伴随 updated 变化,单独用收藏键做签名,改收藏后日历能立刻更新
    fav_sig = (hashlib.md5(('|'.join(sorted(fav_keys))).encode('utf-8')).hexdigest()[:8]
               if fav_flag else '-')
    # ?alarm=30:在活动开始前 N 分钟由日历客户端提醒(0~1440,非法值忽略)
    try:
        alarm = int((request.args.get('alarm') or '').strip() or 0)
    except ValueError:
        alarm = 0
    if alarm < 1 or alarm > 1440:
        alarm = 0
    etag = 'W/"ics-%s-%d-%s-%s-%s-%s-%s"' % (updated, len(events),
                                            ','.join(sorted(games)) or '-',
                                            ','.join(sorted(cats)) or '-',
                                            'fav' if fav_flag else 'all', fav_sig,
                                            'a%d' % alarm if alarm else '-')
    headers = {'ETag': etag, 'Cache-Control': 'no-cache', 'Vary': 'Accept-Encoding'}
    if request.headers.get('If-None-Match') == etag:
        return Response(status=304, headers=headers)
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0',
             'PRODID:-//yoyuxi//anime-game-calendar//CN',
             'CALSCALE:GREGORIAN',
             'X-WR-CALNAME:二游活动日历',
             'X-WR-TIMEZONE:Asia/Shanghai']
    today = _bj_now().replace(tzinfo=None).strftime('%Y-%m-%d')
    n = 0
    for e in events:
        if games and e.get('game_id') not in games:
            continue
        if cats and e.get('category') not in cats:
            continue
        if fav_flag and ('%s|%s' % (e.get('game_id') or '', e.get('title') or '')) not in fav_keys:
            continue
        if (e.get('kind') or 'event') != 'event':
            continue
        # 无解析到开始时间的条目不得拿 pub(date) 当 DTSTART 伪造事件(Issue #25)
        s_iso = e.get('start')
        if not s_iso or e.get('_nodate'):
            continue
        # 已结束的条目不进订阅(状态里通常已被 _drop_expired 过滤,这里防御性兜底)
        if e.get('end') and str(e['end'])[:10] < today:
            continue
        # 与前端「更早开始·结束未知」的折叠口径一致:开始超过 30 天仍无结束的,
        # 不再补默认 2 天窗口塞进订阅日历(以前会留下一堆过去的事件)
        if _is_stale_unknown(e):
            continue
        # 单点里程碑(版本上线/前瞻直播)不在 stale 口径里,这里单独跳过已经过去的日子,
        # 避免补 2 天窗口后把旧直播又塞回订阅生成一堆过期事件
        if _is_point_item(e) and str(s_iso)[:10] < today:
            continue
        ds = _ics_utc(s_iso)
        # 无结束时间的条目补默认窗口(与前端 evEnd 同口径),否则会产出 DTEND==DTSTART
        # 显式 end 无时分时取当天 23:59(既有口径);补出的默认窗口已是「起点 + 2 天」,
        # 再按当天末调整会多出一天,故不传 day_end。
        end_iso = e.get('end')
        de = _ics_utc(end_iso, day_end=True) if end_iso else _ics_utc(_default_end(s_iso))
        if not ds or not de:
            continue
        lines += ['BEGIN:VEVENT',
                  f'UID:{e.get("id", n)}@ycal',
                  f'SEQUENCE:{int(e.get("_seq") or 0)}',
                  f'DTSTAMP:{now}',
                  f'DTSTART:{ds}',
                  f'DTEND:{de}',
                  f'SUMMARY:{_ics_escape("【" + (e.get("game") or "活动") + "】" + e.get("title", ""))}',
                  f'CATEGORIES:{_ics_escape(e.get("game") or "活动")}']
        if e.get('link'):
            lines.append(f'URL:{_ics_escape(e["link"])}')
        if alarm:
            lines += ['BEGIN:VALARM', 'TRIGGER:-PT%dM' % alarm, 'ACTION:DISPLAY',
                      'DESCRIPTION:' + _ics_escape('活动开始提醒'), 'END:VALARM']
        lines += ['DESCRIPTION:数据来源:游戏官方公告', 'END:VEVENT']
        n += 1
    lines.append('END:VCALENDAR')
    print(f'[订阅] 生成 ICS: {n} 个事件')
    body = '\r\n'.join(_ics_fold(l) for l in lines)
    return Response(body + '\r\n', mimetype='text/calendar; charset=utf-8', headers=headers)


@app.route('/api/health')
def api_health():
    """运行状态:给自动化脚本 / 云端 NPC / 外部监控一次拿到更新时间、事件数与各源成败"""
    with _lock:
        updated = _state['updated']
        events = list(_state['events'])
        sources = dict(_state['sources'] or {})
        refreshing = _state['refreshing']
        last_error = _state.get('last_error')
        last_error_at = _state.get('last_error_at')
    hours = None
    if updated:
        try:
            hours = max(0.0, (datetime.now() - datetime.fromisoformat(str(updated))).total_seconds() / 3600)
        except (ValueError, TypeError):
            hours = None
    now = _bj_now().replace(tzinfo=None)
    real = [e for e in events if (e.get('kind') or 'event') == 'event']
    reports = _load_reports()
    cut14 = (now - timedelta(days=_CHANGE_KEEP_DAYS)).isoformat(timespec='seconds')
    changes_recent = sum(1 for rec in (_load_changes() or {}).values()
                         if str((rec or {}).get('at') or '') >= cut14)
    return jsonify({
        'ok': True,
        'updated': updated,
        'stale': bool(hours is not None and hours >= 24),
        'stale_hours': round(hours, 1) if hours is not None else None,
        'refreshing': refreshing,
        'last_error': last_error,
        'last_error_at': last_error_at,
        'events': len(events),
        'events_real': len(real),
        'ongoing': sum(1 for e in real if _is_ongoing(e, now)),
        'stale_unknown': sum(1 for e in real if _is_stale_unknown(e, now)),
        'changes_recent': changes_recent,
        'feedback_total': len(reports),
        'feedback_pending': sum(1 for r in reports if not (r or {}).get('done')),
        'missing_end': sum(1 for e in real if not e.get('end') and not _is_point_item(e)),
        'missing_images': sum(1 for e in real if not (e.get('image') or '').strip()),
        'sources': {k: {'ok': bool((v or {}).get('ok')),
                        'count': (v or {}).get('count', 0),
                        'last_ok': (v or {}).get('last_ok')}
                    for k, v in sources.items() if not str(k).startswith('_')},
        'server_time': datetime.now().isoformat(timespec='seconds'),
    })


def _dq_filter(rows, dq, now=None):
    """数据质量筛选(?dq=noimg|noend|stale),与前端/统计计数逐条同口径。

    只针对真活动(kind=event):资讯条目本来就没有结束时间,算进来只会虚高。
    缺图 = 图片为空或纯空白;缺结束 = 没有 end 且不是单点里程碑(版本上线/前瞻直播);
    更早开始未知 = 开始超 30 天仍无结束(复用 _is_stale_unknown,与列表折叠/订阅排除一致)。
    """
    if dq not in ('noimg', 'noend', 'stale'):
        return rows
    rows = [e for e in rows if (e.get('kind') or 'event') == 'event']
    if dq == 'noimg':
        return [e for e in rows if not (e.get('image') or '').strip()]
    if dq == 'noend':
        return [e for e in rows if not e.get('end') and not _is_point_item(e)]
    return [e for e in rows if _is_stale_unknown(e, now)]


# 游戏简称,与前端 GAME_SHORT 逐项一致(搜索「崩铁」能命中「崩坏：星穹铁道」)
_GAME_SHORT = {'hsr': '崩铁', 'zzz': '绝区零', 'endfield': '终末地', 'arknights': '方舟',
               'wuwa': '鸣潮', 'ananta': '异环', 'r1999': '1999'}


def _q_hay(e):
    """搜索检索串 = 标题 + 游戏名 + 游戏简称 + 分类,与前端列表搜索同口径。"""
    gid = e.get('game_id') or ''
    name = e.get('game') or ''
    return ' '.join([e.get('title') or '', name, _GAME_SHORT.get(gid) or name[:2],
                     e.get('category') or '']).lower()


def _q_filter(rows, q):
    """?q=:空格分隔的关键词逐个 AND 匹配检索串,大小写不敏感。"""
    terms = [t for t in (q or '').lower().split() if t]
    if not terms:
        return rows
    return [e for e in rows if all(t in _q_hay(e) for t in terms)]


@app.route('/api/export.csv')
def api_export_csv():
    """导出 CSV(Excel 直接打开):按 ?games= / ?cats= / ?q= 筛选,与列表视口同口径。

    带 UTF-8 BOM,否则 Windows Excel 打开会把中文识别成乱码;内容含全部条目
    (活动与公告资讯),「类型」列区分,方便用户在表格里自行透视。
    """
    with _lock:
        events = list(_state['events'])
    games = {g.strip() for g in (request.args.get('games') or '').split(',') if g.strip()}
    cats = {c.strip() for c in (request.args.get('cats') or '').split(',') if c.strip()}
    rows = [e for e in events
            if (not games or e.get('game_id') in games)
            and (not cats or e.get('category') in cats)]
    # ?q=:当前搜索词(空格分隔按 AND),导出与屏幕上一模一样的条目
    rows = _q_filter(rows, (request.args.get('q') or '').strip())
    # 收藏 / 已做完来自 data/userstate.json(键= game_id|title,正值=已标记)
    userstate = _load_userstate()
    fav = userstate.get('fav') or {}
    done = userstate.get('done') or {}
    # ?fav=1:只导出收藏的活动
    if request.args.get('fav') in ('1', 'true', 'yes'):
        rows = [e for e in rows
                if fav.get('%s|%s' % (e.get('game_id') or '', e.get('title') or ''), 0) > 0]
    # ?dq=noimg|noend|stale:只导出当前数据质量视图里的条目(与列表筛选条同一口径)
    rows = _dq_filter(rows, (request.args.get('dq') or '').strip())
    rows.sort(key=lambda e: (e.get('start') or e.get('date') or '~', e.get('title') or ''))
    buf = StringIO()
    w = csv.writer(buf)
    w.writerow(['游戏', '标题', '分类', '开始', '结束', '类型', '来源', '链接', '收藏', '已做完'])
    src_label = {'manual': '已核实', 'bilibili': 'B站'}
    for e in rows:
        key = '%s|%s' % (e.get('game_id') or '', e.get('title') or '')
        w.writerow([
            e.get('game') or e.get('game_id') or '',
            e.get('title') or '',
            e.get('category') or '',
            e.get('start') or '',
            e.get('end') or '',
            '活动' if (e.get('kind') or 'event') == 'event' else '资讯',
            src_label.get(e.get('src'), '自动'),
            e.get('link') or '',
            '是' if fav.get(key, 0) > 0 else '否',
            '是' if done.get(key, 0) > 0 else '否',
        ])
    body = '\ufeff' + buf.getvalue()
    return Response(body, content_type='text/csv; charset=utf-8',
                    headers={'Content-Disposition': 'attachment; filename=ycal-events.csv'})


# ================= 图片代理(绕过图床跨域/防盗链) =================
# 浏览器直接加载 B站等图床会被 ORB/防盗链拦截,统一走服务端同源转发
IMG_HOSTS = ('hdslb.com', 'biliimg.com', 'mihoyo.com', 'hoyoverse.com', 'hoyolab.com',
             'kurogame.com', 'kurobbs.com', 'hypergryph.com', 'gryphline.com', 'hycdn.cn',
             'wanmei.com', 'taptap.cn', 'taptap.io', 'weibo.cn', 'weibo.com',
             'sinaimg.cn', 'bilivideo.com', 'akamaized.net', 'im9.com', 'ipaperclip.net',
             'sl916.com', 'bluepoch.com')
IMG_MAX_BYTES = 10 * 1024 * 1024  # 单张图片体积上限,超过即中断(避免并发请求吃满内存)
IMG_MAX_REDIRECTS = 5


class _ImgTooLarge(Exception):
    """图片响应超过体积上限"""


def _url_host(url):
    """取 requests 实际连接用的 host(与 urllib3 口径一致)。

    urlparse 与 urllib3 对 URL 中 `\\` 的处理不同:
    `http://127.0.0.1:8899\\@i0.hdslb.com/x.png` 前者给 i0.hdslb.com(白名单域),
    后者给 127.0.0.1(实际连接目标)。校验必须按后者, 否则可借 `\\@` 绕过白名单打内网。
    解析失败返回空串(交由白名单判定拒绝)。
    """
    try:
        u = parse_url(url)
    except ValueError:
        return ''
    # 无 scheme 的串(如 'not a url')会被 urllib3 当成 host,必须拒绝;
    # 本代理只处理 http/https,其余口径一律空串交由白名单拒绝
    if not u.host or (u.scheme or '').lower() not in ('http', 'https'):
        return ''
    return u.host.lower()


def _img_host_allowed(host):
    """host 是否命中图床白名单(子域放行)"""
    host = (host or '').lower()
    return bool(host) and any(host == h or host.endswith('.' + h) for h in IMG_HOSTS)


def _is_private_host(host):
    """内网/本机地址判定(纯函数,不做 DNS 解析)"""
    host = (host or '').strip().strip('[]').lower()
    if not host or host == 'localhost' or host.endswith('.localhost'):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved


def _resolves_to_private(host):
    """域名解析落在内网地址时视为不可信(DNS 重绑定);解析失败不拦,交由请求层报错"""
    try:
        infos = socket.getaddrinfo(host, None)
    except (OSError, UnicodeError):  # 非法 IDNA label(如 'x..hdslb.com')抛 UnicodeError
        return False
    return any(_is_private_host(info[4][0]) for info in infos)


def _img_host_blocked(host):
    """直连或跳转的目标 host 是否应拒绝:非白名单域,或指向内网/本机"""
    return not _img_host_allowed(host) or _is_private_host(host) or _resolves_to_private(host)


def _img_normalize_url(url):
    """图床地址归一:重返未来1999图床的 https 被 EdgeOne JS 挑战拦(requests 过不了),改写为 http 直出。

    只换 scheme,host/路径/查询串原样保留;非 https 的 sl916 地址直接返回,
    避免按固定长度切片把 `http://` 开头的地址切坏成他人域名。
    """
    try:
        parts = urlsplit(url)
        host = (parts.hostname or '').lower()
    except ValueError:
        return url
    if parts.scheme == 'https' and host.endswith('.sl916.com'):
        return urlunsplit(parts._replace(scheme='http'))
    return url


def _fetch_image(url, headers, max_redirects=IMG_MAX_REDIRECTS, max_bytes=IMG_MAX_BYTES):
    """取图:手动跟随跳转并逐跳校验 host,响应流式读取并限制体积。

    返回 (status_code, content_type, content);跳转目标不合规抛 ValueError,
    体积超限抛 _ImgTooLarge。非 200 或非 image/* 时 content 为 None。
    """
    redirects = 0
    while True:
        r = requests.get(url, headers=headers, timeout=10, allow_redirects=False, stream=True)
        loc = r.headers.get('Location')
        if r.status_code in (301, 302, 303, 307, 308) and loc:
            r.close()
            redirects += 1
            if redirects > max_redirects:
                raise ValueError('too many redirects')
            nxt = urljoin(url, loc)
            if not nxt.startswith(('http://', 'https://')):
                raise ValueError('redirect bad scheme')
            host = _url_host(nxt)
            if _img_host_blocked(host):
                raise ValueError('redirect host not allowed: %s' % host)
            url = nxt
            continue
        break

    try:
        ctype = (r.headers.get('Content-Type') or '').split(';')[0].strip().lower()
        if r.status_code != 200 or not ctype.startswith('image/'):
            return r.status_code, ctype, None
        clen = r.headers.get('Content-Length') or ''
        if clen.isdigit() and int(clen) > max_bytes:
            raise _ImgTooLarge('content-length %s' % clen)
        buf = bytearray()
        for chunk in r.iter_content(64 * 1024):
            buf += chunk
            if len(buf) > max_bytes:
                raise _ImgTooLarge('body over %d bytes' % max_bytes)
        return r.status_code, ctype, bytes(buf)
    finally:
        r.close()


def _shrink_image(content, width=200):
    """把位图缩到指定宽度并转 JPEG;失败/非位图返回 None(调用方回退原图)。

    列表行只有 40px,远程原图往往几百 KB;这里按需缩小而非落盘缓存,
    省掉一次磁盘读写,浏览器侧仍按 URL(含 w 参数)缓存一天。
    """
    try:
        from PIL import Image
        im = Image.open(BytesIO(content)).convert('RGB')
        if im.width > width:
            im = im.resize((width, max(1, round(im.height * width / im.width))), Image.LANCZOS)
        out = BytesIO()
        im.save(out, 'JPEG', quality=80, optimize=True)
        return out.getvalue()
    except Exception:  # noqa: BLE001
        return None


@app.route('/api/img')
def api_img():
    url = (request.args.get('url') or '').strip()
    if not url.startswith(('http://', 'https://')):
        return jsonify({'error': 'bad url'}), 400
    host = _url_host(url)
    if _img_host_blocked(host):
        return jsonify({'error': 'host not allowed'}), 403
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    if 'hdslb' in host or 'biliimg' in host:
        headers['Referer'] = 'https://www.bilibili.com/'  # B站图床防盗链
    url = _img_normalize_url(url)
    try:
        status, ctype, content = _fetch_image(url, headers)
    except _ImgTooLarge as e:
        print(f'[图片代理] 体积超限 {host}: {e}')
        return jsonify({'error': 'image too large'}), 502
    except Exception as e:  # noqa: BLE001
        print(f'[图片代理] 失败 {host}: {e}')
        return jsonify({'error': 'proxy error'}), 502
    if status != 200 or content is None:
        return jsonify({'error': 'fetch failed'}), 502
    if ctype == 'image/svg+xml':
        # SVG 内嵌脚本会在同源上下文执行,不放行
        return jsonify({'error': 'svg not allowed'}), 502
    # 列表缩略图:?w=200 时缩宽转 JPEG(SVG/GIF 与非位图回退原图)
    try:
        want_w = int(request.args.get('w') or 0)
    except ValueError:
        want_w = 0
    if 80 <= want_w <= 800 and ctype not in ('image/gif', 'image/svg+xml'):
        small = _shrink_image(content, want_w)
        if small:
            content, ctype = small, 'image/jpeg'
    resp = Response(content, mimetype=ctype)
    resp.headers['X-Content-Type-Options'] = 'nosniff'
    resp.headers['Cache-Control'] = 'public, max-age=86400'  # 图片缓存 1 天
    return resp


# ================= 活动开始提醒 =================
NOTIFY_FILE = os.path.join(DATA_DIR, 'notify.json')


def _ensure_notify_file():
    if not os.path.exists(NOTIFY_FILE):
        with open(NOTIFY_FILE, 'w', encoding='utf-8') as f:
            json.dump({'webhook': '', 'time': '08:30', 'lead_days': 1, 'evening': '',
                       'fav_only': False},
                      f, ensure_ascii=False, indent=2)


def _notify_config():
    try:
        # utf-8-sig:容忍记事本等编辑器写入的 BOM(普通 utf-8 会因 BOM 导致 json 解析失败)
        with open(NOTIFY_FILE, 'r', encoding='utf-8-sig') as f:
            cfg = json.load(f)
        return cfg if isinstance(cfg, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _pushplus_token(url):
    """从 PushPlus 地址取 token:支持 /send/<token> 与 ?token=<token> 两种常见写法"""
    parts = urlsplit(url)
    tok = (parse_qs(parts.query).get('token') or [''])[0]
    if tok:
        return tok.strip()
    m = re.search(r'/send/([A-Za-z0-9_-]+)', parts.path)
    return m.group(1) if m else ''


def _post_webhook(url, title, body):
    """推送一次并返回 (是否成功, 可读说明)。

    webhook 常见失败是「HTTP 200 但业务 code 非 0」(飞书 token 失效、Bark key 错),
    只看状态码会把这类错误当成成功;这里同时核对常见返回体的 code / statusCode,Bark
    的 200 视为成功。支持的地址:飞书群机器人 / Bark / Server酱 / PushPlus / 通用 JSON。
    """
    low = url.lower()
    try:
        if 'feishu' in low or 'larksuite' in low:
            r = requests.post(url, json={'msg_type': 'text',
                                         'content': {'text': f'{title}\n{body}'}}, timeout=10)
        elif 'sctapi.ftqq.com' in low or 'sc.ftqq.com' in low:
            # Server酱:表单 title/desp,不是 JSON
            r = requests.post(url, data={'title': title, 'desp': body}, timeout=10)
        elif 'pushplus' in low:
            token = _pushplus_token(url)
            if not token:
                return False, 'PushPlus 地址需要带 token(如 https://www.pushplus.plus/send/你的token)'
            r = requests.post('https://www.pushplus.plus/send',
                              json={'token': token, 'title': title, 'content': body}, timeout=10)
        else:
            r = requests.post(url, json={'title': title, 'body': body}, timeout=10)
    except Exception as e:  # noqa: BLE001
        return False, f'网络错误: {str(e)[:120]}'
    data = None
    try:
        data = r.json()
    except Exception:  # noqa: BLE001
        pass
    if isinstance(data, dict):
        for key in ('code', 'StatusCode', 'status'):
            if data.get(key) not in (None, 0, 200):
                msg = str(data.get('msg') or data.get('message') or '')[:80]
                return False, f'{key}={data.get(key)} {msg}'.strip()
    if r.status_code >= 400:
        return False, f'HTTP {r.status_code}'
    return True, f'HTTP {r.status_code}'


def _send_notify(title, body):
    """推送 webhook:支持飞书群机器人 / Bark / 通用 JSON {title,body}"""
    url = (_notify_config().get('webhook') or '').strip()
    if not url:
        return False
    ok, detail = _post_webhook(url, title, body)
    print(f'[提醒] {"已推送" if ok else "推送失败"}: {title} ({detail})')
    return ok


def _bj_now():
    """当前北京时间:数据(manual.json / 抓取结果)与提醒均为该口径,不随服务器时区变化"""
    return datetime.now(_CST)


_DAY_LABELS = {0: '今天', 1: '明天', 2: '后天'}
_LEAD_CHOICES = (0, 1, 3)  # 当天 / 今明两天(历史默认) / 提前3天
_END_LEAD_CHOICES = (0, 1, 2, 3)  # 结束提醒:仅当天 / 今明 / 3 天 / 4 天


def _lead_days(cfg):
    """提醒提前量(天):只放行 0/1/3;缺失或非法一律回落 1(保持历史「今明两天」口径)"""
    try:
        n = int(cfg.get('lead_days', 1))
    except (TypeError, ValueError):
        return 1
    return n if n in _LEAD_CHOICES else 1


def _end_lead(cfg):
    """结束提醒提前量(天):今天 + N 天;0=仅当天;缺失或非法回落 1(今明两天)"""
    try:
        n = int(cfg.get('end_lead_days', 1))
    except (TypeError, ValueError):
        return 1
    return n if n in _END_LEAD_CHOICES else 1


def _friendly_dt(iso):
    """'2026-11-05T10:00' → '11月5日 10:00';空/非法 → 时间待定(推送文案用)"""
    try:
        d = datetime.fromisoformat(str(iso or '')[:19])
    except ValueError:
        return '时间待定'
    txt = f'{d.month}月{d.day}日'
    return txt + (f' {d:%H:%M}' if (d.hour or d.minute) else '')


def _daily_notify(now=None, evening=False):
    """生成并推送当日汇总(now 可注入,便于测试)。

    早间:未来 lead_days+1 天开始 + 今天起 end_lead+1 天结束;晚间:只推明天开始 + 今天结束。
    返回 None=没有需要推送的内容(不算失败);True/False=推送成功/失败。
    """
    cfg = _notify_config()
    if not (cfg.get('webhook') or '').strip():
        return
    with _lock:
        events = list(_state['events'])
    now = now or _bj_now()
    lead = _lead_days(cfg)
    days = {}
    for i in range(lead + 1):
        days[(now + timedelta(days=i)).strftime('%Y-%m-%d')] = i
    today = now.strftime('%Y-%m-%d')
    tomorrow = (now + timedelta(days=1)).strftime('%Y-%m-%d')
    naive_now = now.replace(tzinfo=None)   # 条目时间是北京时间裸值,比较前去掉时区
    # 晚安提醒只覆盖「明天开始」与「今天结束」,避免与早间推送重复刷屏
    start_days = {tomorrow: 1} if evening else days
    end_lead = _end_lead(cfg)
    end_days = ((today,) if evening
                else tuple((now + timedelta(days=i)).strftime('%Y-%m-%d')
                           for i in range(end_lead + 1)))
    fav_only = bool(cfg.get('fav_only'))
    fav_all = _load_userstate().get('fav') or {}      # 改期提醒只针对收藏,与 fav_only 开关无关
    fav_map = fav_all if fav_only else {}
    # 收藏活动改期提醒:最近 24 小时内抓到的 moved 记录(早晚只推早间,避免重复)
    fav_moved = []
    if not evening:
        with _lock:
            changes = list(_state.get('changes') or [])
        cut = (naive_now - timedelta(hours=24)).isoformat(timespec='seconds')
        for c in changes:
            if (c or {}).get('type') != 'moved':
                continue
            if str((c or {}).get('at') or '') < cut:
                continue
            key = f"{c.get('game_id') or ''}|{c.get('title') or ''}"
            if fav_all.get(key, 0) <= 0:
                continue
            fav_moved.append(c)
    starting, ending = [], []
    for e in events:
        if (e.get('kind') or 'event') != 'event':
            continue
        # 未解析到开始时间的条目不得拿 pub(date) 当「今天开始」推送(Issue #25)
        if e.get('_nodate'):
            continue
        # 只推送收藏的活动:键与前端 doneKey 一致(game_id|title),正值=收藏
        if fav_only and fav_map.get(f"{e.get('game_id') or ''}|{e.get('title') or ''}", 0) <= 0:
            continue
        s = str(e.get('start') or e.get('date') or '')
        if s[:10] in start_days:
            starting.append((s, e))
        # 结束提醒:即将结束且尚未结束(限时活动最后一天最容易漏)
        ed = str(e.get('end') or '')
        if ed[:10] in end_days:
            try:
                if datetime.fromisoformat(ed) <= naive_now:
                    continue
            except ValueError:
                pass
            ending.append((ed, e))
    span = '明天' if evening else ({0: '今天', 1: '今明两天'}.get(lead) or f'未来 {lead + 1} 天')
    if not starting and not ending and not fav_moved:
        if fav_only:
            return   # 只推收藏时没有命中就静默,避免每天空推打扰
        return _send_notify('二游活动日历',
                            '今晚没有需要注意的活动。' if evening else f'{span}没有新活动开始。')
    parts = []
    if starting:
        parts.append(f'{span} {len(starting)} 个活动开始')
    if ending:
        parts.append(f'{len(ending)} 个活动即将结束')
    if fav_moved:
        parts.append(f'{len(fav_moved)} 个收藏活动改期')
    lines = []
    for s, e in sorted(starting, key=lambda x: x[0]):
        i = start_days[s[:10]]
        when = _DAY_LABELS.get(i) or f'{i}天后'
        tm = s[11:16] if len(s) >= 16 else ''
        lines.append(f'· {when}{tm and " " + tm} 【{e.get("game") or ""}】{e.get("title", "")}')
    if ending:
        if lines:
            lines.append('')
        lines.append('⏰ 即将结束(别漏了):')
        for ed, e in sorted(ending, key=lambda x: x[0]):
            when = '今天' if ed[:10] == today else '明天'
            tm = ed[11:16] if len(ed) >= 16 else ''
            lines.append(f'· {when}{tm and " " + tm} 截止 【{e.get("game") or ""}】{e.get("title", "")}')
    if fav_moved:
        if lines:
            lines.append('')
        lines.append('🔁 收藏活动改期:')
        gmap = {g['id']: g['name'] for g in scrapers.GAMES_META}
        for c in sorted(fav_moved, key=lambda x: str(x.get('at') or ''), reverse=True):
            old = _friendly_dt((c.get('from') or {}).get('start'))
            new = _friendly_dt((c.get('to') or {}).get('start'))
            lines.append('· 【%s】%s:%s → %s' % (
                gmap.get(c.get('game_id'), c.get('game_id') or ''),
                c.get('title') or '', old, new))
    return _send_notify(('晚安提醒:' if evening else '二游活动提醒:') + ' / '.join(parts), '\n'.join(lines))


def _notify_due(now, cfg_time):
    """到点判定:返回当前应记的北京日期(未到点返回 None),口径同 data/notify.json 的 time"""
    try:
        hh, mm = map(int, (cfg_time or '08:30').split(':'))
    except ValueError:
        hh, mm = 8, 30
    return now.strftime('%Y-%m-%d') if (now.hour, now.minute) >= (hh, mm) else None


NOTIFY_STATE_FILE = os.path.join(DATA_DIR, 'notify_state.json')   # 已推送标记(运行时生成,不入库)
_notify_state_lock = threading.Lock()
_NOTIFY_MAX_TRIES = 3


def _load_notify_marks():
    try:
        with open(NOTIFY_STATE_FILE, 'r', encoding='utf-8') as f:
            d = json.load(f)
        m = d.get('marks') if isinstance(d, dict) else None
        return m if isinstance(m, dict) else {}
    except Exception:  # noqa: BLE001 - 文件不存在/损坏按空标记
        return {}


def _save_notify_marks(marks):
    with _notify_state_lock:
        try:
            with open(NOTIFY_STATE_FILE, 'w', encoding='utf-8') as f:
                json.dump({'marks': marks}, f, ensure_ascii=False, indent=1)
        except Exception as e:  # noqa: BLE001
            print(f'[提醒] 标记保存失败: {e}')


def _prune_notify_marks(marks, now):
    """只保留最近 7 天的标记,文件不无限增长"""
    cut = (now - timedelta(days=7)).strftime('%Y-%m-%d')
    return {k: v for k, v in marks.items() if str(k).split(':')[0] >= cut}


def _notify_once(now=None, marks=None):
    """一轮到点检查:每天每个时段只推一次,失败最多重试 _NOTIFY_MAX_TRIES 次。

    标记落盘而不是只存内存:08:30 已经推过的服务在中午重启,不能再把当天汇总
    推一遍(以前 sent 只在进程内,重启就会重复推送)。推送失败(webhook 短暂
    不可用)的记录会保留,下一分钟继续重试,而不是整天不再提醒。
    """
    now = now or _bj_now()
    marks = marks if marks is not None else _load_notify_marks()
    cfg = _notify_config()
    for slot, field in (('main', 'time'), ('evening', 'evening')):
        t = cfg.get(field)
        if slot == 'evening' and not (str(t or '').strip()):
            continue   # 未配置晚间时刻 = 关闭
        day = _notify_due(now, t)
        if not day:
            continue
        key = f'{day}:{slot}'
        rec = marks.get(key) or {}
        if rec.get('done'):
            continue
        ok = _daily_notify(now, evening=(slot == 'evening'))
        tries = int(rec.get('tries') or 0) + 1
        done = ok is None or bool(ok) or tries >= _NOTIFY_MAX_TRIES
        marks[key] = {'done': done,
                      'ok': None if ok is None else bool(ok),   # None=没有内容需要推送
                      'tries': tries, 'at': now.isoformat(timespec='seconds')}
    marks = _prune_notify_marks(marks, now)
    _save_notify_marks(marks)
    return marks


def _notify_loop():
    """每天到点推送:早间汇总(lead_days) + 可选的晚间「晚安提醒」"""
    marks = _load_notify_marks()
    while True:
        try:
            marks = _notify_once(marks=marks)
        except Exception as e:  # noqa: BLE001 - 单轮异常不能让提醒线程退出
            print(f'[提醒] 本轮检查失败: {e}')
        time.sleep(60)


def _port_in_use(port):
    """connect 探测:能连上才是真有服务在跑
    (裸 bind 探测会被 TIME_WAIT 残留误报,导致快速重启时拒绝启动)"""
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=0.4):
            return True
    except OSError:
        return False


def _lan_ip():
    """取本机局域网 IP(通过 UDP 连接探测,不实际发包)"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(('223.5.5.5', 80))
            return s.getsockname()[0]
    except OSError:
        return None


def main():
    port = 5000
    url = f'http://127.0.0.1:{port}'
    # 是否启动后自动弹浏览器:默认关闭。后台/自动化方式启动服务时绝不该抢走用户的屏幕
    # (曾因此盖住用户正在看的游戏剧情)。仅当启动器显式设置 YCAL_OPEN=1 时才自动打开页面。
    auto_open = os.environ.get('YCAL_OPEN') == '1'
    if _port_in_use(port):
        # 已有实例在运行:不重复启动(避免新旧进程共存数据错乱),直接打开页面
        print('=' * 50)
        print(f'  服务已在运行中,无需重复启动: {url}')
        print('  如需使用最新代码,请先关闭旧的服务窗口再启动')
        print('=' * 50)
        if auto_open:
            webbrowser.open(url)
        return
    _load_cache()
    _ensure_notify_file()
    # 启动后立即在后台刷新一次(不阻塞服务启动)
    threading.Thread(target=do_refresh, daemon=True).start()
    threading.Thread(target=_refresh_loop, daemon=True).start()
    threading.Thread(target=_notify_loop, daemon=True).start()
    lan = _lan_ip()
    print('=' * 50)
    print(f'  二游活动聚合已启动: {url}')
    if lan:
        print(f'  局域网访问(手机/平板): http://{lan}:{port}')
    print(f'  ICS 日历订阅: {url}/api/calendar.ics')
    print(f'  活动提醒: 配置 data/notify.json 的 webhook(默认 {(_notify_config().get("time") or "08:30")})')
    print('  每 30 分钟自动抓取一次,关闭本窗口即停止服务')
    print('=' * 50)
    if auto_open:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    # 绑定 0.0.0.0:局域网内设备(平板/手机)可直接访问
    app.run(host='0.0.0.0', port=port, debug=False)


if __name__ == '__main__':
    main()
