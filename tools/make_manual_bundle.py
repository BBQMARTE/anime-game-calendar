# -*- coding: utf-8 -*-
"""把 data/manual.json 打包成 manual-data.js,供安卓离线模式使用。

服务端网页直接走 /api/events,不需要这个文件;APK 在连不上服务器时会退回
file:// 离线模式,此时没有服务端,manual.json 里人工核实的活动只能随包携带。

生成两份(内容一致):
  static/manual-data.js                       (服务端也可访问,便于本地调试)
  android/app/src/main/assets/www/manual-data.js  (打进 APK)

运行:python tools/make_manual_bundle.py
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANUAL = os.path.join(ROOT, 'data', 'manual.json')
TARGETS = [
    os.path.join(ROOT, 'static', 'manual-data.js'),
    os.path.join(ROOT, 'android', 'app', 'src', 'main', 'assets', 'www', 'manual-data.js'),
]

HEADER = ('/* 自动生成,勿手改:data/manual.json → window.YCAL_MANUAL(安卓离线模式用)。\n'
          '   重新生成:python tools/make_manual_bundle.py */\n')


def main():
    with open(MANUAL, 'r', encoding='utf-8-sig') as f:
        arr = json.load(f)
    if not isinstance(arr, list):
        raise SystemExit('manual.json 不是数组')
    body = HEADER + 'window.YCAL_MANUAL=' + json.dumps(arr, ensure_ascii=False, separators=(',', ':')) + ';\n'
    for p in TARGETS:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'w', encoding='utf-8', newline='\n') as f:
            f.write(body)
        print('写入', os.path.relpath(p, ROOT), len(body), '字节')
    print('共', len(arr), '条手动活动')


if __name__ == '__main__':
    main()
