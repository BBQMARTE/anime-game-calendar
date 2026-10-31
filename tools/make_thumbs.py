# -*- coding: utf-8 -*-
"""生成安卓离线模式用的封面图(列表 200px JPEG / 详情 800px WebP)。

static/img 里是人工核实活动的原图(共 ~99MB),不可能打进 APK;
离线模式(file://)没有服务端 /api/thumb 可用,只能随包带压缩图:
列表行只有 40px,用 200px JPEG;详情弹窗正文要看清小字,用 800px。
800px 改用 WebP(q75):同画质下比 JPEG 小约 35%(实测 20 张样本省 35.7%),
APK 因此从 13.2MB 降到约 9MB。Android 8+ 的 WebView 原生支持 WebP。
服务端网页不需要这批文件:/api/thumb 会按需生成并缓存 JPEG。

输出:android/app/src/main/assets/www/thumb/img/<原相对路径>.jpg       (200px)
      android/app/src/main/assets/www/thumb/img/<原相对路径>@800.webp  (800px)
(该目录已 gitignore,由构建脚本随包生成;旧的 @800.jpg 会被清理)

运行:python tools/make_thumbs.py
"""
import os
import sys

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'static', 'img')
DST = os.path.join(ROOT, 'android', 'app', 'src', 'main', 'assets', 'www', 'thumb', 'img')
# (最长边, 编码格式, 质量, 文件名后缀)
VARIANTS = ((200, 'JPEG', 78, '.jpg'), (800, 'WEBP', 75, '@800.webp'))
EXTS = {'.jpg', '.jpeg', '.png', '.webp'}
STALE = ('@800.jpg',)   # 旧版 800px JPEG,换成 WebP 后清掉,避免两种格式都进 APK


def _render(src, dst, side, fmt, quality):
    im = Image.open(src)
    im = im.convert('RGB')
    im.thumbnail((side, side))
    kw = {'quality': quality}
    if fmt == 'WEBP':
        kw['method'] = 4
    else:
        kw['optimize'] = True
    im.save(dst, fmt, **kw)


def main():
    if not os.path.isdir(SRC):
        raise SystemExit('缺少 static/img')
    made = skipped = failed = cleaned = 0
    total = 0
    for base, _dirs, files in os.walk(SRC):
        for name in files:
            if os.path.splitext(name)[1].lower() not in EXTS:
                continue
            src = os.path.join(base, name)
            rel = os.path.splitext(os.path.relpath(src, SRC))[0]
            for side, fmt, quality, suffix in VARIANTS:
                dst = os.path.join(DST, rel + suffix)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                if os.path.exists(dst) and os.path.getmtime(dst) >= os.path.getmtime(src):
                    skipped += 1
                    total += os.path.getsize(dst)
                    continue
                try:
                    _render(src, dst, side, fmt, quality)
                    made += 1
                    total += os.path.getsize(dst)
                except Exception as e:  # noqa: BLE001
                    failed += 1
                    print('  跳过(无法读取):', rel, e)
            for old in STALE:
                p = os.path.join(DST, rel + old)
                if os.path.exists(p):
                    os.remove(p)
                    cleaned += 1
    print('生成 %d 张、跳过 %d 张、失败 %d 张;清理旧格式 %d 张;合计 %.1f MB'
          % (made, skipped, failed, cleaned, total / 1048576))
    if failed:
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
