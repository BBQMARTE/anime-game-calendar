# -*- coding: utf-8 -*-
"""B站动态标题清洗测试。

动态正文里常夹带视频/专栏链接,此前首行若是链接就会产出
「互动抽奖 https://www.bilibili.com/video/BV…」这类无效标题。
现在标题生成先去掉 URL,再按原有「首行太短补第二行 / 38 码元截断」规则。
Python bilibili._title_of 与 APK 端 scraper.js::biliTitle 同口径。

运行:python3 tests/test_bili_title.py(node 缺失则跳过 JS 比对)
"""
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bilibili  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
bad = 0

CASES = [
    ('互动抽奖 https://www.bilibili.com/video/BV1abc\n全新角色PV', '互动抽奖 全新角色PV'),
    ('活动预告 https://example.com/x', '活动预告'),
    ('这是一条很长的动态标题没有链接', '这是一条很长的动态标题没有链接'),
    ('', ''),
    ('https://example.com/x\n活动开启', '活动开启'),
    ('   ,,https://example.com/x ,,  ', ''),
]


def check(label, got, expect):
    global bad
    ok = got == expect
    if not ok:
        bad += 1
    print("[%s] %s: got=%r expect=%r" % ('OK ' if ok else 'FAIL', label, got, expect))


def main():
    global bad
    for i, (src, want) in enumerate(CASES):
        check('Python 用例 %d' % i, bilibili._title_of(src), want)

    node = shutil.which('node')
    if not node:
        print('SKIP: 未找到 node,跳过 JS 双端比对')
    else:
        js = os.path.join(ROOT, 'static', 'scraper.js')
        script = (
            "const fs=require('fs');"
            "const src=fs.readFileSync(%s,'utf8');"
            "const S=new Function(src+'\\nreturn Scraper;')();"
            "const cases=%s;"
            "console.log(JSON.stringify(cases.map(c=>S.biliTitle(c[0]))));"
            % (json.dumps(js), json.dumps(CASES, ensure_ascii=False)))
        r = subprocess.run([node, '-e', script], capture_output=True, text=True,
                           encoding='utf-8', timeout=60)
        if r.returncode != 0:
            print('FAIL: JS 执行失败\n' + r.stderr[:600])
            bad += 1
        else:
            got = json.loads(r.stdout.strip().splitlines()[-1])
            check('JS biliTitle 与 Python 一致', got, [c[1] for c in CASES])

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
