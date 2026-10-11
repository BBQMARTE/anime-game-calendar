# -*- coding: utf-8 -*-
"""发版 E2E 冒烟:一条命令验证本地服务核心链路(发版后手动跑,或打包前自查)。

运行:python3 tests/smoke_e2e.py [--url http://127.0.0.1:5000]
服务未运行则 SKIP(退出码 0),不阻塞 CI;全部通过输出 ALL PASS(退出码 0)。
"""
import json, os, re, sys, urllib.request, urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = 'http://127.0.0.1:5000'
if '--url' in sys.argv:
    BASE = sys.argv[sys.argv.index('--url') + 1].rstrip('/')

bad = 0


def check(label, ok, detail=''):
    global bad
    if not ok:
        bad += 1
    print('[%s] %s%s' % ('OK ' if ok else 'FAIL', label, (' — ' + str(detail)[:120]) if (detail and not ok) else ''))


def get(path, timeout=8, headers=None):
    req = urllib.request.Request(BASE + path, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception:
        return None, b''


def main():
    # 0. 服务探活:不在跑则 SKIP(冒烟依赖真实服务)
    code, body = get('/api/events', timeout=4)
    if code is None:
        print('SKIP: 本地服务未运行(%s),发版冒烟仅在服务在线时执行' % BASE)
        return 0
    print('冒烟目标: %s\n' % BASE)

    # 1. 核心接口
    try:
        d = json.loads(body.decode('utf-8'))
    except Exception:
        d = {}
    evs = d.get('events') or []
    check('/api/events 200 且含 events', code == 200 and isinstance(evs, list) and len(evs) > 0,
          'code=%s n=%s' % (code, len(evs)))
    check('数据带 updated 时间戳', bool(d.get('updated')), d.get('updated'))

    # 2. 静态资源
    for path, kw in [('/', '二游活动聚合'), ('/scraper.js', ''), ('/sw.js', 'CACHE'),
                     ('/manifest.webmanifest', 'name')]:
        c, b = get(path)
        text = b.decode('utf-8', 'ignore')
        check('GET %s → 200' % path, c == 200 and (kw in text if kw else True), 'code=%s' % c)

    # 3. 功能 API
    c, _ = get('/api/todo')
    check('/api/todo GET 200', c == 200, c)
    c, b = get('/api/notify-config')
    ok_cfg = c == 200 and b'"lead_days"' in b
    check('/api/notify-config GET 200 且含 lead_days', ok_cfg, (c, b[:80]))
    c, b = get('/api/calendar.ics')
    check('/api/calendar.ics 200 且为 ICS', c == 200 and b'BEGIN:VCALENDAR' in b, c)

    # 4. 图片代理拒绝路径(不依赖外网)
    c, _ = get('/api/img?url=not%20a%20url')
    check('图片代理:非法 URL 被拒(400/403)', c in (400, 403), c)
    c, _ = get('/api/img?url=http://169.254.169.254/latest/meta-data/')
    check('图片代理:内网地址被拒(403)', c == 403, c)

    # 5. 数据健康
    now = __import__('datetime').datetime.now().strftime('%Y-%m-%d')
    ev = [e for e in evs if (e.get('kind') or 'event') == 'event']
    expired = [e for e in ev if e.get('end') and str(e['end'])[:10] < now]
    check('无过期真活动(end 早于今天)', len(expired) == 0, [e.get('title') for e in expired[:3]])
    noimg = [e for e in ev if not e.get('image')]
    cover = 1 - len(noimg) / max(1, len(ev))
    check('活动配图覆盖率 ≥ 60%', cover >= 0.6, '%.0f%% (%d 缺)' % (cover * 100, len(noimg)))
    check('进行中活动存在', any(e for e in ev if str(e.get('start') or '')[:10] <= now), '')

    # 6. 前端完整性(关键函数在发版文件里)
    c, b = get('/')
    html = b.decode('utf-8', 'ignore')
    for fn in ['function openStats(', 'function attachSwipeClose(', 'function toggleFav(',
               'function saveNotifyCfg(', 'function isoWeek(', 'function importMemoTpl(']:
        check('index.html 含 %s' % fn.strip('function (').rstrip('('), fn in html, '')

    # 7. SW 版本:发版必递增,且 android assets 已同步
    c, idx_bytes = get('/')   # 重新拉取(前面循环覆盖过 b)
    html = idx_bytes.decode('utf-8', 'ignore')
    m = re.search(r"const CACHE = 'ycal-v(\d+)'", get('/sw.js')[1].decode('utf-8', 'ignore'))
    check('sw.js 含版本号', bool(m), '')
    if m:
        v = m.group(1)
        apk_sw = os.path.join(ROOT, 'android', 'app', 'src', 'main', 'assets', 'www', 'sw.js')
        if os.path.exists(apk_sw):
            mv = re.search(r"const CACHE = 'ycal-v(\d+)'", open(apk_sw, encoding='utf-8').read())
            check('android assets/www/sw.js 与线上同版本(v%s)' % v, bool(mv) and mv.group(1) == v,
                  'apk=%s web=%s' % (mv.group(1) if mv else '?', v))
        idx_apk = os.path.join(ROOT, 'android', 'app', 'src', 'main', 'assets', 'www', 'index.html')
        if os.path.exists(idx_apk):
            same = open(idx_apk, 'rb').read() == idx_bytes   # 字节级对比(文本模式会因 CRLF 归一误判)
            check('android assets/www/index.html 与线上一致', same, '若 FAIL 记得 Copy-Item 同步再打包')

    print('\n%s' % ('ALL PASS' if bad == 0 else '%d FAILED' % bad))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
