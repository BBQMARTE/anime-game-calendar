# -*- coding: utf-8 -*-
"""二游活动日历 - 本地服务
自动抓取各二游官方活动/公告,聚合成日历展示。
运行后自动打开浏览器 http://127.0.0.1:5000
"""
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

import requests
from flask import Flask, Response, jsonify, request, send_from_directory
from urllib.parse import urljoin, urlsplit, urlunsplit
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
}


def _drop_expired(events):
    """丢弃已结束的真活动(info/公告保留):do_refresh 与缓存载入共用同一口径"""
    today = _bj_now().strftime('%Y-%m-%d')
    kept = [e for e in events
            if (e.get('kind') or 'event') != 'event'
            or not e.get('end') or str(e['end'])[:10] >= today]
    n = len(events) - len(kept)
    if n:
        print(f'[过滤] 丢弃 {n} 条已过期活动')
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
            _state['events'] = _dedup_against_manual(evs)   # 旧缓存可能存着跨源重复条目,载入时清掉
            _state['sources'] = {k: v for k, v in (data.get('sources') or {}).items()
                                 if k in valid or k == 'bilibili'}
            _state['updated'] = data.get('updated')
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
    """
    raw = str(e.get('id') or '')
    # 显式 id 只收安全字符集:该值会进前端内联 onclick 与 ICS 属性
    if re.fullmatch(r'[A-Za-z0-9_.:-]{1,64}', raw):
        return raw
    key = f"{e.get('game_id', '')}|{e.get('title', '')}|{e.get('start') or ''}"
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
            out.append({
                'id': _manual_id(e),
                'game_id': gid,
                'game': names.get(gid, e.get('game') or gid or '自定义'),
                'title': e.get('title', '未命名事件'),
                'category': e.get('category', '活动'),
                'start': start,
                'end': e.get('end') or None,
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
            prev_by_src = {}
            for e in _state['events']:
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
        with _lock:
            _state['events'] = events
            _state['sources'] = sources
            _state['updated'] = datetime.now().isoformat(timespec='seconds')
            _state['refreshing'] = False
        _save_cache()
        ok = sum(1 for s in sources.values() if s['ok'])
        print(f'[抓取] 完成: {ok}/{len(sources)} 个源成功, 共 {len(events)} 条事件')
        return True
    except Exception as e:  # noqa: BLE001
        with _lock:
            _state['refreshing'] = False
            # 全链路崩了也要让前端可见:旧数据继续展示,来源区标记本轮刷新失败
            _state['sources'] = {**(_state.get('sources') or {}),
                                 '_system': {'name': '本轮抓取', 'ok': False, 'count': 0,
                                             'error': f'{str(e)[:110]}(已沿用上一轮数据)'}}
        print(f'[抓取] 失败: {e}')
        return False


def _refresh_loop():
    while True:
        time.sleep(REFRESH_INTERVAL)
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


@app.route('/scraper.js')
def scraper_js():
    return send_from_directory(app.static_folder, 'scraper.js')


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


@app.route('/api/events')
def api_events():
    with _lock:
        return jsonify(_state)


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
_REPORT_KINDS = ('missing-image', 'wrong-time', 'other')


def _load_reports():
    try:
        with open(REPORT_FILE, 'r', encoding='utf-8-sig') as f:
            d = json.load(f)
        items = d.get('items') if isinstance(d, dict) else None
        return items if isinstance(items, list) else []
    except Exception:  # noqa: BLE001
        return []


@app.route('/api/report', methods=['GET', 'POST'])
def api_report():
    """用户反馈:GET 读待核查清单,POST 追加一条(同游戏同标题同类型 10 分钟内不重复记)"""
    if request.method == 'GET':
        with _report_lock:
            return jsonify({'items': _load_reports()})
    # 与 /api/refresh、/api/todo 同样的简单 CSRF 防护
    if request.headers.get('X-Requested-With') != 'ycal':
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    body = request.get_json(silent=True) or {}
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
                        'evening': cfg.get('evening') or '',
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
                    'evening': cfg.get('evening') or '',
                    'has_webhook': bool((cfg.get('webhook') or '').strip())})


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
    """ICS 订阅源:系统日历/Google 日历可直接订阅(仅真活动,含手动录入)"""
    now = datetime.now(_CST).strftime('%Y%m%dT%H%M%SZ')
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0',
             'PRODID:-//yoyuxi//anime-game-calendar//CN',
             'CALSCALE:GREGORIAN',
             'X-WR-CALNAME:二游活动日历',
             'X-WR-TIMEZONE:Asia/Shanghai']
    with _lock:
        events = list(_state['events'])
    # ?games=hsr,zzz:只订阅自己玩的游戏(逗号分隔;未知 id 自然筛不出事件,无需白名单)
    games = {g.strip() for g in (request.args.get('games') or '').split(',') if g.strip()}
    n = 0
    for e in events:
        if games and e.get('game_id') not in games:
            continue
        if (e.get('kind') or 'event') != 'event':
            continue
        # 无解析到开始时间的条目不得拿 pub(date) 当 DTSTART 伪造事件(Issue #25)
        s_iso = e.get('start')
        if not s_iso or e.get('_nodate'):
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
                  f'DTSTAMP:{now}',
                  f'DTSTART:{ds}',
                  f'DTEND:{de}',
                  f'SUMMARY:{_ics_escape("【" + (e.get("game") or "活动") + "】" + e.get("title", ""))}']
        if e.get('link'):
            lines.append(f'URL:{_ics_escape(e["link"])}')
        lines += ['DESCRIPTION:数据来源:游戏官方公告', 'END:VEVENT']
        n += 1
    lines.append('END:VCALENDAR')
    print(f'[订阅] 生成 ICS: {n} 个事件')
    body = '\r\n'.join(_ics_fold(l) for l in lines)
    return Response(body + '\r\n', mimetype='text/calendar; charset=utf-8')


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
    resp = Response(content, mimetype=ctype)
    resp.headers['X-Content-Type-Options'] = 'nosniff'
    resp.headers['Cache-Control'] = 'public, max-age=86400'  # 图片缓存 1 天
    return resp


# ================= 活动开始提醒 =================
NOTIFY_FILE = os.path.join(DATA_DIR, 'notify.json')


def _ensure_notify_file():
    if not os.path.exists(NOTIFY_FILE):
        with open(NOTIFY_FILE, 'w', encoding='utf-8') as f:
            json.dump({'webhook': '', 'time': '08:30', 'lead_days': 1, 'evening': ''},
                      f, ensure_ascii=False, indent=2)


def _notify_config():
    try:
        # utf-8-sig:容忍记事本等编辑器写入的 BOM(普通 utf-8 会因 BOM 导致 json 解析失败)
        with open(NOTIFY_FILE, 'r', encoding='utf-8-sig') as f:
            cfg = json.load(f)
        return cfg if isinstance(cfg, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _send_notify(title, body):
    """推送 webhook:支持飞书群机器人 / Bark / 通用 JSON {title,body}"""
    url = (_notify_config().get('webhook') or '').strip()
    if not url:
        return False
    try:
        if 'feishu' in url or 'larksuite' in url:
            requests.post(url, json={'msg_type': 'text',
                                     'content': {'text': f'{title}\n{body}'}}, timeout=10)
        else:
            requests.post(url, json={'title': title, 'body': body}, timeout=10)
        print(f'[提醒] 已推送: {title}')
        return True
    except Exception as e:  # noqa: BLE001
        print(f'[提醒] 推送失败: {e}')
        return False


def _bj_now():
    """当前北京时间:数据(manual.json / 抓取结果)与提醒均为该口径,不随服务器时区变化"""
    return datetime.now(_CST)


_DAY_LABELS = {0: '今天', 1: '明天', 2: '后天'}
_LEAD_CHOICES = (0, 1, 3)  # 当天 / 今明两天(历史默认) / 提前3天


def _lead_days(cfg):
    """提醒提前量(天):只放行 0/1/3;缺失或非法一律回落 1(保持历史「今明两天」口径)"""
    try:
        n = int(cfg.get('lead_days', 1))
    except (TypeError, ValueError):
        return 1
    return n if n in _LEAD_CHOICES else 1


def _daily_notify(now=None, evening=False):
    """早间:未来 lead_days+1 天开始 + 今天/明天结束;晚间:只推明天开始 + 今天结束(now 可注入,便于测试)"""
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
    end_days = (today,) if evening else (today, tomorrow)
    starting, ending = [], []
    for e in events:
        if (e.get('kind') or 'event') != 'event':
            continue
        # 未解析到开始时间的条目不得拿 pub(date) 当「今天开始」推送(Issue #25)
        if e.get('_nodate'):
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
    if not starting and not ending:
        _send_notify('二游活动日历',
                     '今晚没有需要注意的活动。' if evening else f'{span}没有新活动开始。')
        return
    parts = []
    if starting:
        parts.append(f'{span} {len(starting)} 个活动开始')
    if ending:
        parts.append(f'{len(ending)} 个活动即将结束')
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
    _send_notify(('晚安提醒:' if evening else '二游活动提醒:') + ' / '.join(parts), '\n'.join(lines))


def _notify_due(now, cfg_time):
    """到点判定:返回当前应记的北京日期(未到点返回 None),口径同 data/notify.json 的 time"""
    try:
        hh, mm = map(int, (cfg_time or '08:30').split(':'))
    except ValueError:
        hh, mm = 8, 30
    return now.strftime('%Y-%m-%d') if (now.hour, now.minute) >= (hh, mm) else None


def _notify_loop():
    """每天到点推送:早间汇总(lead_days) + 可选的晚间「晚安提醒」(evening,只推明天开始/今天结束)"""
    sent = set()   # {'YYYY-MM-DD:slot'} 已发标记,跨日自动失效
    while True:
        now = _bj_now()
        cfg = _notify_config()
        for slot, field in (('main', 'time'), ('evening', 'evening')):
            t = cfg.get(field)
            if slot == 'evening' and not (str(t or '').strip()):
                continue   # 未配置晚间时刻 = 关闭
            day = _notify_due(now, t)
            key = f'{day}:{slot}' if day else ''
            if key and key not in sent:
                sent.add(key)
                if len(sent) > 30:            # 只留最近几天的标记
                    sent = {k for k in sent if k.split(':')[0] >= (now - timedelta(days=7)).strftime('%Y-%m-%d')}
                _daily_notify(now, evening=(slot == 'evening'))
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
