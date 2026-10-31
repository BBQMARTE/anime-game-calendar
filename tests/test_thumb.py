# -*- coding: utf-8 -*-
"""列表缩略图测试。

static/img 原图平均 ~500KB,列表行只有 40px;服务端 /api/thumb 按需压到 200px 并缓存,
安卓离线模式改用构建时生成的 www/thumb 小图(约 1MB,不会把 99MB 原图打进 APK)。

运行:python3 tests/test_thumb.py(node 缺失则跳过前端映射测试)
"""
import json
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, 'static', 'index.html')
IMG_DIR = os.path.join(ROOT, 'static', 'img')
bad = 0


def check(label, got, expect):
    global bad
    ok = got == expect
    if not ok:
        bad += 1
    print("[%s] %s: got=%r expect=%r" % ('OK ' if ok else 'FAIL', label, got, expect))


def first_image():
    for base, _dirs, files in os.walk(IMG_DIR):
        for name in files:
            if os.path.splitext(name)[1].lower() in ('.jpg', '.jpeg', '.png', '.webp'):
                return os.path.join(base, name)
    return None


def main():
    global bad
    src = first_image()
    if not src:
        print('SKIP: static/img 为空(图片未随仓库分发),跳过服务端缩略图测试')
        return 0
    rel = os.path.relpath(src, os.path.join(ROOT, 'static'))
    path = '/static/' + rel.replace('\\', '/')
    client = app.app.test_client()

    r1 = client.get('/api/thumb?path=' + path)
    check('有效图片返回 200', r1.status_code, 200)
    check('返回 JPEG', r1.mimetype, 'image/jpeg')
    check('缩略图比原图小', len(r1.data) < os.path.getsize(src), True)
    rel_img = os.path.relpath(src, IMG_DIR)
    cache = os.path.join(ROOT, 'static', 'thumb', os.path.splitext(rel_img)[0] + '.jpg')
    check('缩略图落盘缓存', os.path.exists(cache), True)
    mtime = os.path.getmtime(cache)

    r2 = client.get('/api/thumb?path=' + path)
    check('第二次命中缓存,字节一致', r2.data == r1.data, True)
    check('缓存文件未被重写', os.path.getmtime(cache), mtime)

    big = client.get('/api/thumb?path=' + path + '&w=800')
    check('w=800 返回 200', big.status_code, 200)
    check('w=800 比 200px 更大(更清晰)', len(big.data) > len(r1.data), True)
    cache800 = os.path.join(ROOT, 'static', 'thumb',
                            os.path.splitext(rel_img)[0] + '@800.jpg')
    check('w=800 缓存文件名带宽度', os.path.exists(cache800), True)

    check('拒绝非 static/img 路径', client.get('/api/thumb?path=/app.py').status_code, 400)
    check('拒绝目录穿越',
          client.get('/api/thumb?path=/static/img/../../app.py').status_code, 400)
    check('不存在的图片返回 404',
          client.get('/api/thumb?path=/static/img/__nope__.jpg').status_code, 404)

    # ---- 远程图代理 ?w=200:用假响应,避免联网 ----
    from io import BytesIO
    from PIL import Image
    buf = BytesIO()
    Image.new('RGB', (800, 400), (220, 40, 40)).save(buf, 'PNG')
    png = buf.getvalue()
    real_fetch = app._fetch_image
    real_block = app._img_host_blocked
    app._fetch_image = lambda url, headers: (200, 'image/png', png)
    app._img_host_blocked = lambda host: False   # 测试用 example.com,跳过白名单/DNS
    try:
        big = client.get('/api/img?url=https://example.com/a.png')
        small = client.get('/api/img?url=https://example.com/a.png&w=200')
        check('不带 w 返回原图', big.mimetype, 'image/png')
        check('w=200 返回 JPEG', small.mimetype, 'image/jpeg')
        check('w=200 体积更小', len(small.data) < len(big.data), True)
        bad_w = client.get('/api/img?url=https://example.com/a.png&w=abc')
        check('非法 w 回退原图', bad_w.mimetype, 'image/png')
        tiny = client.get('/api/img?url=https://example.com/a.png&w=20')
        check('w 低于下限回退原图', tiny.mimetype, 'image/png')
    finally:
        app._fetch_image = real_fetch
        app._img_host_blocked = real_block

    node = shutil.which('node')
    if not node:
        print('SKIP: 未找到 node,跳过前端 thumbUrl 映射测试')
    else:
        loader = r"""
const fs = require('fs');
const src = (fs.readFileSync(0, 'utf8').match(/<script>[\s\S]*?<\/script>/g) || [])
  .map(b => b.replace(/<\/?script>/g, '')).join('\n');
function grab(name) {
  const i = src.indexOf('function ' + name + '(');
  if (i < 0) throw new Error('not found: ' + name);
  let d = 0, go = false;
  for (let k = src.indexOf('{', i); k < src.length; k++) {
    if (src[k] === '{') { d++; go = true; }
    else if (src[k] === '}') { d--; if (go && !d) return src.slice(i, k + 1); }
  }
  throw new Error('unbalanced: ' + name);
}
function build(proto) {
  const fn = new Function('location', grab('imgUrl') + '\n' + grab('imgAt') + '\n' + grab('thumbUrl')
    + '\nreturn {imgUrl, thumbUrl, imgAt};');
  return fn({protocol: proto});
}
const http = build('http:');
const file = build('file:');
console.log(JSON.stringify({
  localHttp: http.thumbUrl('/static/img/hsr/a.jpg'),
  localHttp800: http.imgAt('/static/img/hsr/a.jpg', 800),
  localFile: file.thumbUrl('/static/img/hsr/a.jpg'),
  localFile800: file.imgAt('/static/img/hsr/a.jpg', 800),
  localFilePng: file.thumbUrl('/static/img/hsr/b.png'),
  localFilePng800: file.imgAt('/static/img/hsr/b.png', 800),
  remoteHttp: http.thumbUrl('https://example.com/a.jpg'),
  empty: http.thumbUrl(''),
}));
"""
        r = subprocess.run([node, '-e', loader], input=open(HTML, encoding='utf-8').read(),
                           capture_output=True, text=True, encoding='utf-8', timeout=60)
        if r.returncode != 0:
            print('FAIL: JS 执行失败\n' + r.stderr[:600])
            bad += 1
        else:
            d = json.loads(r.stdout.strip().splitlines()[-1])
            check('列表本地图走 200px',
                  d['localHttp'], '/api/thumb?path=%2Fstatic%2Fimg%2Fhsr%2Fa.jpg&w=200')
            check('详情本地图走 800px',
                  d['localHttp800'], '/api/thumb?path=%2Fstatic%2Fimg%2Fhsr%2Fa.jpg&w=800')
            check('离线列表走相对 thumb/img', d['localFile'], 'thumb/img/hsr/a.jpg')
            check('离线详情走随包 800px', d['localFile800'], 'thumb/img/hsr/a@800.jpg')
            check('离线 png 也映射到生成的 jpg', d['localFilePng'], 'thumb/img/hsr/b.jpg')
            check('离线 png 详情也映射 jpg', d['localFilePng800'], 'thumb/img/hsr/b@800.jpg')
            check('远程图走代理并缩到 200px',
                  d['remoteHttp'], '/api/img?url=https%3A%2F%2Fexample.com%2Fa.jpg&w=200')
            check('空图片返回空串', d['empty'], '')

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
