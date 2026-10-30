# -*- coding: utf-8 -*-
"""安卓离线模式手动活动测试。

APK 连不上服务器时会退回 file:// 离线模式,此时没有 /api/events,
data/manual.json 里人工核实的活动需要随包提供(tools/make_manual_bundle.py
生成 window.YCAL_MANUAL)。scraper.js::manualEvents() 在 localStorage 为空时
回退到这份数据,其它逻辑(签到天数补结束等)不变。

运行:python3 tests/test_manual_offline.py(node 缺失则 SKIP)
"""
import json
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANUAL = os.path.join(ROOT, 'data', 'manual.json')
STATIC_JS = os.path.join(ROOT, 'static', 'manual-data.js')
APK_JS = os.path.join(ROOT, 'android', 'app', 'src', 'main', 'assets', 'www', 'manual-data.js')

bad = 0


def check(label, got, expect):
    global bad
    ok = got == expect
    if not ok:
        bad += 1
    print("[%s] %s: got=%r expect=%r" % ('OK ' if ok else 'FAIL', label, got, expect))


def main():
    global bad
    # ---- 1. 生成物与 manual.json 一致 ----
    raw = json.load(open(MANUAL, encoding='utf-8-sig'))
    for p in (STATIC_JS, APK_JS):
        check('存在 %s' % os.path.relpath(p, ROOT), os.path.exists(p), True)
        text = open(p, encoding='utf-8').read()
        m = re.search(r'window\.YCAL_MANUAL=(.*?);\r?\n', text, re.S)
        check('%s 含 window.YCAL_MANUAL' % os.path.basename(p), bool(m), True)
        if m:
            arr = json.loads(m.group(1))
            check('%s 条目数与 manual.json 一致' % os.path.basename(p), len(arr), len(raw))
    if os.path.exists(STATIC_JS) and os.path.exists(APK_JS):
        check('两份 bundle 内容一致',
              open(STATIC_JS, 'rb').read() == open(APK_JS, 'rb').read(), True)

    # ---- 2. 前端回退逻辑 ----
    node = shutil.which('node')
    if not node:
        print('SKIP: 未找到 node,跳过离线回退测试')
    else:
        js = os.path.join(ROOT, 'static', 'scraper.js')
        fixture = [{'title': '星河共我签到（7日）', 'game_id': 'endfield',
                    'start': '2026-11-05T12:00', 'category': '签到'}]
        script = (
            "const fs=require('fs');"
            "const src=fs.readFileSync(%s,'utf8');"
            "globalThis.localStorage={getItem:()=> '[]'};"
            "globalThis.window={YCAL_MANUAL:%s};"
            "const S=new Function(src+'\\nreturn Scraper;')();"
            "const m=S.manualEvents();"
            "globalThis.window={YCAL_MANUAL:%s};"
            "globalThis.localStorage={getItem:()=> JSON.stringify([{title:'本地优先',start:'2026-11-06T12:00'}])};"
            "const m2=S.manualEvents();"
            "console.log(JSON.stringify({m:m.map(x=>[x.title,x.end]),m2:m2.map(x=>x.title)}));"
            % (json.dumps(js), json.dumps(fixture, ensure_ascii=False),
               json.dumps(fixture, ensure_ascii=False)))
        r = subprocess.run([node, '-e', script], capture_output=True, text=True,
                           encoding='utf-8', timeout=60)
        if r.returncode != 0:
            print('FAIL: JS 执行失败\n' + r.stderr[:600])
            bad += 1
        else:
            got = json.loads(r.stdout.strip().splitlines()[-1])
            check('离线回退读取 window.YCAL_MANUAL', got['m'],
                  [['星河共我签到（7日）', '2026-11-12T12:00:00']])
            check('localStorage 有数据时优先用它', got['m2'], ['本地优先'])

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
