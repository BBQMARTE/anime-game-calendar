# -*- coding: utf-8 -*-
"""PWA manifest 结构测试(桌面/安卓「添加到主屏幕」用)。

检查:
  - 必需的 name / short_name / start_url / display / icons(192、512 且文件存在)
  - 新增的 categories 与 shortcuts:URL 指向 index 支持的 tab,图标存在
  - static 与 android assets 的 manifest 逐字节一致(发版同步)

运行:python tests/test_manifest.py
"""
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, 'static', 'manifest.webmanifest')
ASSET = os.path.join(ROOT, 'android', 'app', 'src', 'main', 'assets', 'www', 'manifest.webmanifest')
HTML = os.path.join(ROOT, 'static', 'index.html')
bad = 0


def check(label, got, expect):
    global bad
    ok = got == expect
    if not ok:
        bad += 1
    print("[%s] %s: got=%r expect=%r" % ('OK ' if ok else 'FAIL', label, got, expect))


def md5(path):
    with open(path, 'rb') as f:
        return hashlib.md5(f.read()).hexdigest()


def main():
    with open(STATIC, encoding='utf-8') as f:
        m = json.load(f)

    check("名称", (m.get('name'), m.get('short_name')), ('二游活动聚合', '二游日历'))
    check("启动地址与作用域", (m.get('start_url'), m.get('scope')), ('/', '/'))
    check("独立窗口显示", m.get('display'), 'standalone')
    icons = {i.get('sizes'): i.get('src') for i in (m.get('icons') or [])}
    check("192 图标", icons.get('192x192'), '/icon-192.png')
    check("512 图标", icons.get('512x512'), '/icon-512.png')
    for src in (icons.get('192x192'), icons.get('512x512')):
        check("图标文件存在 %s" % src,
              os.path.exists(os.path.join(ROOT, 'static', src.lstrip('/'))), True)

    check("分类非空", bool(m.get('categories')), True)
    shortcuts = m.get('shortcuts') or []
    check("快捷方式数量", len(shortcuts), 2)
    names = [s.get('name') for s in shortcuts]
    check("快捷方式名称", names, ['进行中', '我的收藏'])
    tabs = []
    for s in shortcuts:
        url = s.get('url') or ''
        check("快捷方式 URL 以 / 开头", url.startswith('/'), True)
        qs = url.split('?', 1)[1] if '?' in url else ''
        pairs = dict(p.split('=', 1) for p in qs.split('&') if '=' in p)
        tabs.append(pairs.get('tab'))
        for ic in (s.get('icons') or []):
            check("快捷方式图标存在 %s" % ic.get('src'),
                  os.path.exists(os.path.join(ROOT, 'static', (ic.get('src') or '').lstrip('/'))), True)
    check("快捷方式 tab 指向列表页", tabs, ['ongoing', 'fav'])

    src = open(HTML, encoding='utf-8').read()
    check("前端支持 tab 参数", 'TAB_IDS' in src and 'out.tab=t' in src, True)
    for t in tabs:
        check("TAB_IDS 含 %s" % t, t in src, True)

    check("APK assets 的 manifest 与 static 一致", md5(ASSET), md5(STATIC))

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
