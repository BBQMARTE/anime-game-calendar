# -*- coding: utf-8 -*-
"""正文首图提取测试(鸣潮等没有独立封面的公告用第一张图兜底)。

运行:python3 tests/test_first_img.py(node 缺失则跳过 JS 部分)
"""
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scrapers  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
bad = 0


def check(label, got, expect):
    global bad
    ok = got == expect
    if not ok:
        bad += 1
    print("[%s] %s: got=%r expect=%r" % ('OK ' if ok else 'FAIL', label, got, expect))


def main():
    global bad
    check("双引号图片地址",
          scrapers._first_img('<p><img src="https://x/a.png" alt=""></p>'), 'https://x/a.png')
    check("单引号图片地址",
          scrapers._first_img("<img style='x' src='https://x/b.webp'>"), 'https://x/b.webp')
    check("取第一张图",
          scrapers._first_img('<img src="https://x/1.png"><img src="https://x/2.png">'), 'https://x/1.png')
    check("大写 IMG 标签",
          scrapers._first_img('<IMG SRC="https://x/c.jpg">'), 'https://x/c.jpg')
    check("无图返回空", scrapers._first_img('<p>纯文字</p>'), '')
    check("空串返回空", scrapers._first_img(''), '')

    node = shutil.which('node')
    if node:
        js_path = os.path.join(ROOT, 'static', 'scraper.js')
        script = ("const fs=require('fs');const src=fs.readFileSync(%s,'utf8');"
                  "const S=new Function(src+'\\nreturn Scraper;')();"
                  "const out=[S.firstImg('<p><img src=\"https://x/a.png\"></p>'),"
                  "S.firstImg(\"<img src='https://x/b.webp'>\"),S.firstImg('')];"
                  "console.log(JSON.stringify(out));" % json.dumps(js_path))
        r = subprocess.run([node, '-e', script], capture_output=True, text=True, encoding='utf-8', timeout=60)
        if r.returncode != 0:
            print('FAIL: JS 执行失败\n' + r.stderr[:500])
            bad += 1
        else:
            check("JS 端首图提取同口径", json.loads(r.stdout.strip().splitlines()[-1]),
                  ['https://x/a.png', 'https://x/b.webp', ''])
    else:
        print('SKIP: 未找到 node，跳过 JS 段')

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
