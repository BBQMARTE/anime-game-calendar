# -*- coding: utf-8 -*-
"""文本响应 gzip 测试。

SW 每次版本升级都会重新拉 index.html / manual-data.js / scraper.js(约 220KB),
远程访问时未压缩很浪费。after_request 按 Accept-Encoding 压缩文本响应,
浏览器透明解压;图片与已压缩响应不处理。

运行:python tests/test_gzip_static.py
"""
import gzip
import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
bad = 0


def check(label, got, expect):
    global bad
    ok = got == expect
    if not ok:
        bad += 1
    print("[%s] %s: got=%r expect=%r" % ('OK ' if ok else 'FAIL', label, got, expect))


def main():
    client = app.app.test_client()
    plain = client.get('/')
    zipped = client.get('/', headers={'Accept-Encoding': 'gzip'})
    check('首页 200', zipped.status_code, 200)
    check('首页返回 gzip', zipped.headers.get('Content-Encoding'), 'gzip')
    check('声明 Vary', zipped.headers.get('Vary'), 'Accept-Encoding')
    check('压缩后更小', len(zipped.data) < len(plain.data), True)
    unzipped = gzip.decompress(zipped.data)
    check('解压后与明文一致(md5)',
          hashlib.md5(unzipped).hexdigest(), hashlib.md5(plain.data).hexdigest())
    check('首页内容完整', b'<html' in unzipped.lower(), True)
    check('不支持 gzip 时不变', 'Content-Encoding' in plain.headers, False)

    js_plain = client.get('/scraper.js')
    js_z = client.get('/scraper.js', headers={'Accept-Encoding': 'gzip'})
    check('scraper.js 压缩', js_z.headers.get('Content-Encoding'), 'gzip')
    with open(os.path.join(ROOT, 'static', 'scraper.js'), 'rb') as f:
        raw = f.read()
    check('scraper.js 解压后与文件一致(md5)',
          hashlib.md5(gzip.decompress(js_z.data)).hexdigest(),
          hashlib.md5(raw).hexdigest())

    ico = client.get('/icon-192.png', headers={'Accept-Encoding': 'gzip'})
    check('图片不压缩', 'Content-Encoding' in ico.headers, False)

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
