# -*- coding: utf-8 -*-
"""图片代理安全回归测试（覆盖 Issue #15）。

/api/img 是无鉴权接口且服务绑 0.0.0.0，此前只校验「首跳 URL」的 host：
302 可跳到内网任意主机（SSRF）、`image/svg+xml` 原样回传且无 nosniff（同源脚本执行）、
响应无体积上限。本脚本用假 `requests.get` 离线断言修复后的行为。

运行：python3 tests/test_img_proxy.py
      （需要 flask；缺依赖则 SKIP 并退出码 0）
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import app
except ImportError as e:  # pragma: no cover - 缺依赖时不算失败
    print('SKIP: 无法导入 app（%s）' % e)
    sys.exit(0)

bad = 0


def check(label, got, expect):
    global bad
    ok = got == expect
    bad += 0 if ok else 1
    print("[%s] %s: got=%r expect=%r" % ('OK ' if ok else 'FAIL', label, got, expect))
    return ok


def check_true(label, cond):
    return check(label, bool(cond), True)


# ---- 假响应与假 requests.get（离线，不联网）----
class FakeResp:
    def __init__(self, status=200, headers=None, body=b'', chunks=None):
        self.status_code = status
        self.headers = headers or {}
        self._body = body
        self._chunks = chunks

    def iter_content(self, n):
        for c in (self._chunks if self._chunks is not None else [self._body]):
            yield c

    def close(self):
        pass


_fake = None  # 最近一次安装的 FakeRequests，供断言调用记录


def set_fake(routes):
    """安装假 GET：按 URL 返回预置响应，并记录实际请求顺序。"""
    global _fake

    class FakeRequests:
        def __init__(self, routes):
            self.routes = routes
            self.calls = []

        def get(self, url, **kw):
            self.calls.append(url)
            r = self.routes.get(url)
            if r is None:
                raise AssertionError('unexpected fetch: %s' % url)
            return r

    _fake = FakeRequests(routes)
    app.requests.get = _fake.get
    return _fake


_real_get = app.requests.get
_real_resolve = app._resolves_to_private
# DNS 解析会引入环境差异，用例内统一按「可解析」处理；内网判定单独测纯函数
app._resolves_to_private = lambda host: False

PNG = b'\x89PNG\r\n\x1a\n' + b'x' * 64

try:
    client = app.app.test_client()

    def get_img(url):
        return client.get('/api/img?url=' + url)

    # ---- 1. 纯函数：内网/本机 host 判定 ----
    for h in ('127.0.0.1', '10.0.0.9', '192.168.1.5', '172.16.3.4',
              '169.254.169.254', '::1', '[::1]', 'localhost', 'foo.localhost', ''):
        check_true('_is_private_host(%r)' % h, app._is_private_host(h))
    for h in ('i0.hdslb.com', '8.8.8.8', '1.1.1.1', 'gamecms-res.sl916.com'):
        check('_is_private_host 放行公网 %r' % h, app._is_private_host(h), False)

    # ---- 2. 白名单匹配（子域放行、后缀伪造拒绝）----
    check_true('白名单命中 i0.hdslb.com', app._img_host_allowed('i0.hdslb.com'))
    check_true('白名单命中根域 hdslb.com', app._img_host_allowed('hdslb.com'))
    check('后缀伪造拒绝', app._img_host_allowed('i0.hdslb.com.evil.example'), False)

    # ---- 3. 直连非白名单 / 内网 host → 403，且不发起请求 ----
    set_fake({})
    check('非白名单 host → 403', get_img('http://evil.example.com/x.png').status_code, 403)
    check('非白名单 host 未发起请求', _fake.calls, [])
    check('后缀伪造 → 403',
          get_img('http://i0.hdslb.com.evil.example/x.png').status_code, 403)
    check('内网直链 → 403', get_img('http://127.0.0.1:8890/pic.png').status_code, 403)
    check('localhost 直链 → 403', get_img('http://localhost/pic.png').status_code, 403)

    # ---- 4. 302 跳转逐跳校验 ----
    # ① 跳到内网：拒绝，且不泄露内网内容
    set_fake({'http://i0.hdslb.com/redir.png':
              FakeResp(302, {'Location': 'http://10.0.0.9:8890/pic.png'})})
    r = get_img('http://i0.hdslb.com/redir.png')
    check('302 → 内网 返回 502', r.status_code, 502)
    check_true('302 → 内网 响应体不含内网内容', b'INTERNAL-ONLY' not in r.data)

    # ② 跳到非白名单公网域名：拒绝，不跟到底
    set_fake({'http://i0.hdslb.com/r2.png':
              FakeResp(302, {'Location': 'http://evil.example.com/pic.png'})})
    r = get_img('http://i0.hdslb.com/r2.png')
    check('302 → 非白名单 返回 502', r.status_code, 502)
    check('302 → 非白名单 未请求跳转目标', _fake.calls, ['http://i0.hdslb.com/r2.png'])

    # ③ 相对 Location 解析后仍在白名单内 → 正常取图
    set_fake({'http://i0.hdslb.com/r3.png': FakeResp(302, {'Location': '/real.png'}),
              'http://i0.hdslb.com/real.png':
                  FakeResp(200, {'Content-Type': 'image/png'}, PNG)})
    r = get_img('http://i0.hdslb.com/r3.png')
    check('相对跳转仍在白名单 → 200', r.status_code, 200)
    check('相对跳转后取到图片', r.data, PNG)

    # ④ 跳转次数超限 → 502
    routes = {}
    for i in range(app.IMG_MAX_REDIRECTS + 2):
        routes['http://i0.hdslb.com/loop%d.png' % i] = FakeResp(
            302, {'Location': 'http://i0.hdslb.com/loop%d.png' % (i + 1)})
    set_fake(routes)
    check('跳转次数超限 → 502', get_img('http://i0.hdslb.com/loop0.png').status_code, 502)

    # ---- 5. SVG 不放行 + nosniff + 缓存头 ----
    set_fake({'http://i0.hdslb.com/a.svg': FakeResp(
        200, {'Content-Type': 'image/svg+xml; charset=utf-8'},
        b'<svg xmlns="http://www.w3.org/2000/svg"><script>pwned=1</script></svg>')})
    r = get_img('http://i0.hdslb.com/a.svg')
    check('image/svg+xml → 502', r.status_code, 502)
    check_true('SVG 内容不外泄', b'<script>' not in r.data)

    set_fake({'http://i0.hdslb.com/b.png':
              FakeResp(200, {'Content-Type': 'image/png'}, PNG)})
    r = get_img('http://i0.hdslb.com/b.png')
    check('正常图片 → 200', r.status_code, 200)
    check('X-Content-Type-Options: nosniff', r.headers.get('X-Content-Type-Options'), 'nosniff')
    check('保留 Cache-Control', r.headers.get('Cache-Control'), 'public, max-age=86400')

    # ---- 6. hdslb 图床仍带防盗链 Referer ----
    set_fake({'http://i0.hdslb.com/c.png':
              FakeResp(200, {'Content-Type': 'image/png'}, PNG)})
    seen = {}
    inner_get = _fake.get

    def spy(url, **kw):
        seen['referer'] = (kw.get('headers') or {}).get('Referer')
        return inner_get(url, **kw)

    app.requests.get = spy
    get_img('http://i0.hdslb.com/c.png')
    check('hdslb 仍带 B站 Referer', seen.get('referer'), 'https://www.bilibili.com/')

    # ---- 7. 体积上限 ----
    set_fake({'http://i0.hdslb.com/huge.png': FakeResp(
        200, {'Content-Type': 'image/png',
              'Content-Length': str(app.IMG_MAX_BYTES + 1)}, b'')})
    check('Content-Length 超限 → 502', get_img('http://i0.hdslb.com/huge.png').status_code, 502)

    chunk = b'x' * (1024 * 1024)
    set_fake({'http://i0.hdslb.com/stream.png': FakeResp(
        200, {'Content-Type': 'image/png'},
        chunks=[chunk] * (app.IMG_MAX_BYTES // len(chunk) + 2))})
    check('流式累计超限 → 502', get_img('http://i0.hdslb.com/stream.png').status_code, 502)

    # 边界内（恰好等于上限）应放行
    set_fake({'http://i0.hdslb.com/edge.png': FakeResp(
        200, {'Content-Type': 'image/png'},
        chunks=[b'x' * 1024] * (app.IMG_MAX_BYTES // 1024))})
    check('恰好等于上限 → 200', get_img('http://i0.hdslb.com/edge.png').status_code, 200)

    # ---- 8. 非图片 / 上游失败 → 502 ----
    set_fake({'http://i0.hdslb.com/txt':
              FakeResp(200, {'Content-Type': 'text/html'}, b'<html>')})
    check('非 image/* → 502', get_img('http://i0.hdslb.com/txt').status_code, 502)
    set_fake({'http://i0.hdslb.com/404.png':
              FakeResp(404, {'Content-Type': 'image/png'}, b'')})
    check('上游 404 → 502', get_img('http://i0.hdslb.com/404.png').status_code, 502)

    # ---- 9. sl916 的 http 直出分支保持可用 ----
    set_fake({'http://gamecms-res.sl916.com/x.png':
              FakeResp(200, {'Content-Type': 'image/png'}, PNG)})
    r = get_img('https://gamecms-res.sl916.com/x.png')
    check('sl916 https → http 直出仍可用', r.status_code, 200)
    check('sl916 实际请求为 http', _fake.calls, ['http://gamecms-res.sl916.com/x.png'])

    # ---- 10. 现有真实配图形态不被误伤（白名单域 + 本地路径）----
    set_fake({})
    for u in ('http://i0.hdslb.com/bfs/new_dyn/x.jpg',
              'https://gamecms-res.sl916.com/obj/x.png',
              'https://webstatic.mihoyo.com/x.png',
              'https://ak.hycdn.cn/x.png'):
        check_true('真实图床放行 %s' % u, not app._img_host_blocked(
            __import__('urllib.parse', fromlist=['urlparse']).urlparse(u).hostname))
finally:
    app.requests.get = _real_get
    app._resolves_to_private = _real_resolve

print('\nALL PASS' if bad == 0 else '\n%d FAILED' % bad)
sys.exit(0 if bad == 0 else 1)
