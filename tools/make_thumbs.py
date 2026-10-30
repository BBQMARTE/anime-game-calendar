# -*- coding: utf-8 -*-
"""生成安卓离线模式用的封面缩略图(200px)。

static/img 里是人工核实活动的原图(共 ~99MB),不可能打进 APK;
离线模式(file://)的列表行只有 40px,用 200px 小图足够。
服务端网页不需要这批文件:/api/thumb 会按需生成并缓存。

输出:android/app/src/main/assets/www/thumb/img/<原相对路径>.jpg
(该目录已 gitignore,由构建脚本随包生成)

运行:python tools/make_thumbs.py
"""
import os
import sys

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'static', 'img')
DST = os.path.join(ROOT, 'android', 'app', 'src', 'main', 'assets', 'www', 'thumb', 'img')
MAX_SIDE = 200
QUALITY = 78
EXTS = {'.jpg', '.jpeg', '.png', '.webp'}


def main():
    if not os.path.isdir(SRC):
        raise SystemExit('缺少 static/img')
    made = skipped = failed = 0
    total = 0
    for base, _dirs, files in os.walk(SRC):
        for name in files:
            if os.path.splitext(name)[1].lower() not in EXTS:
                continue
            src = os.path.join(base, name)
            rel = os.path.relpath(src, SRC)
            dst = os.path.join(DST, os.path.splitext(rel)[0] + '.jpg')
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if os.path.exists(dst) and os.path.getmtime(dst) >= os.path.getmtime(src):
                skipped += 1
                total += os.path.getsize(dst)
                continue
            try:
                im = Image.open(src)
                im = im.convert('RGB')
                im.thumbnail((MAX_SIDE, MAX_SIDE))
                im.save(dst, 'JPEG', quality=QUALITY, optimize=True)
                made += 1
                total += os.path.getsize(dst)
            except Exception as e:  # noqa: BLE001
                failed += 1
                print('  跳过(无法读取):', rel, e)
    print('生成 %d 张、跳过 %d 张、失败 %d 张;合计 %.1f MB' % (made, skipped, failed, total / 1048576))
    if failed:
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
