# -*- coding: utf-8 -*-
"""推送测试接口 /api/notify-test 测试。

设置面板的「发送测试消息」要能当场告诉用户 webhook 通不通,而不仅是 HTTP 200:
飞书 token 失效会返回 200 + 业务 code 非 0,必须识别为失败。

运行:python3 tests/test_notify_test_api.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app  # noqa: E402

bad = 0


def check(label, got, expect):
    global bad
    ok = got == expect
    if not ok:
        bad += 1
    print("[%s] %s: got=%r expect=%r" % ('OK ' if ok else 'FAIL', label, got, expect))


class Resp:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError('not json')
        return self._payload


def main():
    sent = []
    orig_cfg, orig_post = app._notify_config, app.requests.post

    def fake_post(url, json=None, data=None, timeout=None):
        sent.append({'url': url, 'json': json, 'data': data})
        return fake_post.resp

    app.requests.post = fake_post
    try:
        client = app.app.test_client()
        hdr = {'X-Requested-With': 'ycal'}

        # 1. 缺少防伪造头
        app._notify_config = lambda: {'webhook': 'https://open.feishu.cn/open-apis/bot/v2/hook/x'}
        r = client.post('/api/notify-test')
        check("缺少 X-Requested-With → 403", r.status_code, 403)

        # 2. 未配置 webhook
        app._notify_config = lambda: {'webhook': ''}
        r = client.post('/api/notify-test', headers=hdr)
        d = r.get_json()
        check("未配置 webhook → 400", r.status_code, 400)
        check("未配置 webhook 给出可读错误", d['error'], '还没有填写推送地址')
        check("未配置时不发请求", len(sent), 0)

        # 3. 飞书成功:返回体 code=0
        app._notify_config = lambda: {'webhook': 'https://open.feishu.cn/open-apis/bot/v2/hook/x'}
        fake_post.resp = Resp(200, {'code': 0, 'msg': 'success'})
        r = client.post('/api/notify-test', headers=hdr)
        d = r.get_json()
        check("飞书成功 → ok", d['ok'], True)
        check("飞书成功 → 说明含 HTTP 200", d['detail'], 'HTTP 200')
        check("飞书 payload 用 msg_type=text", sent[-1]['json']['msg_type'], 'text')
        check("测试消息含『测试消息』字样", '测试消息' in sent[-1]['json']['content']['text'], True)

        # 4. 飞书 200 但 token 失效(code≠0)必须判失败
        fake_post.resp = Resp(200, {'code': 19001, 'msg': 'invalid token'})
        d = client.post('/api/notify-test', headers=hdr).get_json()
        check("飞书业务错误 → ok=false", d['ok'], False)
        check("飞书业务错误 → 说明含错误码", '19001' in d['detail'], True)

        # 5. Bark 的 code=200 视为成功
        app._notify_config = lambda: {'webhook': 'https://api.day.app/key'}
        fake_post.resp = Resp(200, {'code': 200, 'message': 'success'})
        d = client.post('/api/notify-test', headers=hdr).get_json()
        check("Bark code=200 → ok", d['ok'], True)
        check("非飞书 payload 为 {title,body}", sorted(sent[-1]['json'].keys()), ['body', 'title'])

        # 5b. Server酱:表单 title/desp
        app._notify_config = lambda: {'webhook': 'https://sctapi.ftqq.com/KEY.send'}
        fake_post.resp = Resp(200, {'code': 0, 'message': 'ok'})
        d = client.post('/api/notify-test', headers=hdr).get_json()
        check("Server酱 → ok", d['ok'], True)
        check("Server酱 用表单提交", sorted(sent[-1]['data'].keys()), ['desp', 'title'])
        check("Server酱 不再发 JSON", sent[-1]['json'], None)
        check("Server酱 正文含测试消息", '测试消息' in sent[-1]['data']['desp'], True)

        # 5c. PushPlus:/send/<token> 形式
        app._notify_config = lambda: {'webhook': 'https://www.pushplus.plus/send/abc123'}
        fake_post.resp = Resp(200, {'code': 200, 'msg': 'success'})
        d = client.post('/api/notify-test', headers=hdr).get_json()
        check("PushPlus → ok", d['ok'], True)
        check("PushPlus 统一发到 /send", sent[-1]['url'], 'https://www.pushplus.plus/send')
        check("PushPlus 取出路径 token", sent[-1]['json']['token'], 'abc123')
        check("PushPlus payload 字段", sorted(sent[-1]['json'].keys()), ['content', 'title', 'token'])

        # 5d. PushPlus 缺 token:给出可读错误且不发请求
        app._notify_config = lambda: {'webhook': 'https://www.pushplus.plus/send'}
        n_before = len(sent)
        d = client.post('/api/notify-test', headers=hdr).get_json()
        check("PushPlus 缺 token → ok=false", d['ok'], False)
        check("PushPlus 缺 token → 说明提示 token", 'token' in d['detail'], True)
        check("PushPlus 缺 token 不发请求", len(sent), n_before)

        # 6. HTTP 500(换成通用地址,避免命中 PushPlus 的 token 分支)
        app._notify_config = lambda: {'webhook': 'https://example.com/hook'}
        fake_post.resp = Resp(500, None)
        d = client.post('/api/notify-test', headers=hdr).get_json()
        check("HTTP 500 → ok=false", d['ok'], False)
        check("HTTP 500 → 说明含状态码", d['detail'], 'HTTP 500')

        # 7. 网络异常
        def boom(url, json=None, timeout=None):
            raise OSError('connection refused')
        app.requests.post = boom
        d = client.post('/api/notify-test', headers=hdr).get_json()
        check("网络异常 → ok=false", d['ok'], False)
        check("网络异常 → 说明以『网络错误』开头", d['detail'].startswith('网络错误'), True)
    finally:
        app._notify_config, app.requests.post = orig_cfg, orig_post

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
