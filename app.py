# -*- coding: utf-8 -*-
"""二游活动日历 - 本地服务
自动抓取各二游官方活动/公告,聚合成日历展示。
运行后自动打开浏览器 http://127.0.0.1:5000
"""
import json
import os
import socket
import threading
import time
import webbrowser
from datetime import datetime, timedelta, timezone

import requests
from flask import Flask, Response, jsonify, request, send_from_directory

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


def _load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            # 过滤已从注册表移除的游戏(旧缓存残留)
            valid = {g['id'] for g in scrapers.GAMES_META}
            _state['events'] = [e for e in data.get('events', [])
                                if e.get('game_id') in valid or e.get('src') == 'manual']
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


def _manual_events():
    """读取 data/manual.json 中的手动添加事件"""
    path = os.path.join(DATA_DIR, 'manual.json')
    if not os.path.exists(path):
        return []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            arr = json.load(f)
        names = {g['id']: g['name'] for g in scrapers.GAMES_META}
        out = []
        for i, e in enumerate(arr):
            if not isinstance(e, dict) or 'title' not in e:
                continue  # 跳过说明性条目
            gid = e.get('game_id', '')
            start = e.get('start') or None
            out.append({
                'id': f'manual-{i}',
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
        # 统一去重(同游戏同标题):手动录入的条目经人工核实,优先保留
        seen = {}
        for e in events:
            key = (e.get('game_id'), e.get('title'))
            old = seen.get(key)
            if old is None or (e.get('src') == 'manual' and old.get('src') != 'manual'):
                seen[key] = e
        events = list(seen.values())
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
        print(f'[抓取] 失败: {e}')
        return False


def _refresh_loop():
    while True:
        time.sleep(REFRESH_INTERVAL)
        do_refresh()


@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')


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


# ================= ICS 日历订阅 =================
_CST = timezone(timedelta(hours=8))  # 数据时间为北京时间


def _ics_escape(s):
    return str(s or '').replace('\\', '\\\\').replace(';', '\\;').replace(',', '\\,').replace('\n', ' ')


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
    n = 0
    for e in events:
        if (e.get('kind') or 'event') != 'event':
            continue
        s_iso = e.get('start') or e.get('date')
        if not s_iso:
            continue
        ds = _ics_utc(s_iso)
        de = _ics_utc(e.get('end'), day_end=True) if e.get('end') else _ics_utc(s_iso, day_end=True)
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
    return Response('\r\n'.join(lines) + '\r\n', mimetype='text/calendar; charset=utf-8')


# ================= 活动开始提醒 =================
NOTIFY_FILE = os.path.join(DATA_DIR, 'notify.json')


def _ensure_notify_file():
    if not os.path.exists(NOTIFY_FILE):
        with open(NOTIFY_FILE, 'w', encoding='utf-8') as f:
            json.dump({'webhook': '', 'time': '08:30'}, f, ensure_ascii=False, indent=2)


def _notify_config():
    try:
        with open(NOTIFY_FILE, 'r', encoding='utf-8') as f:
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


def _daily_notify():
    """今明两天开始的活动汇总推送"""
    if not (_notify_config().get('webhook') or '').strip():
        return
    with _lock:
        events = list(_state['events'])
    today = datetime.now().strftime('%Y-%m-%d')
    tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
    starting = []
    for e in events:
        if (e.get('kind') or 'event') != 'event':
            continue
        s = str(e.get('start') or e.get('date') or '')
        if s[:10] in (today, tomorrow):
            starting.append((s, e))
    if not starting:
        _send_notify('二游活动日历', '今明两天没有新活动开始。')
        return
    lines = []
    for s, e in sorted(starting, key=lambda x: x[0]):
        when = '今天' if s[:10] == today else '明天'
        tm = s[11:16] if len(s) >= 16 else ''
        lines.append(f'· {when}{tm and " " + tm} 【{e.get("game") or ""}】{e.get("title", "")}')
    _send_notify(f'二游活动提醒:今明两天 {len(starting)} 个活动开始', '\n'.join(lines))


def _notify_loop():
    """每天到点推送一次(配置在 data/notify.json,改完下一轮生效)"""
    sent_day = None
    while True:
        try:
            hh, mm = map(int, (_notify_config().get('time') or '08:30').split(':'))
        except ValueError:
            hh, mm = 8, 30
        now = datetime.now()
        key = now.strftime('%Y-%m-%d')
        if (now.hour, now.minute) >= (hh, mm) and sent_day != key:
            _daily_notify()
            sent_day = key
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
    if _port_in_use(port):
        # 已有实例在运行:不重复启动(避免新旧进程共存数据错乱),直接打开页面
        print('=' * 50)
        print(f'  服务已在运行中,无需重复启动: {url}')
        print('  如需使用最新代码,请先关闭旧的服务窗口再启动')
        print('=' * 50)
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
    threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    # 绑定 0.0.0.0:局域网内设备(平板/手机)可直接访问
    app.run(host='0.0.0.0', port=port, debug=False)


if __name__ == '__main__':
    main()
