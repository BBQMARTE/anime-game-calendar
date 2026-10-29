# -*- coding: utf-8 -*-
"""打钩/收藏跨设备同步(/api/userstate)的合并语义测试。

离线跑:临时文件替换真实 data/userstate.json,不产生副作用。
覆盖:CSRF 头、last-writer-wins、取消(墓碑 0)、非法时间戳过滤、上限截断。

运行:python3 tests/test_userstate.py
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app  # noqa: E402

bad = 0


def check(label, got, expect):
    global bad
    ok = got == expect
    if not ok:
        bad += 1
    print("[%s] %s: got=%r expect=%r" % ('OK ' if ok else 'FAIL', label, got, expect))


def main():
    tmp = tempfile.mkdtemp(prefix='ycal_us_')
    app.USERSTATE_FILE = os.path.join(tmp, 'userstate.json')
    c = app.app.test_client()
    H = {'X-Requested-With': 'ycal'}

    # 1) 首次读取:空状态
    check("空文件返回空集合", c.get('/api/userstate').get_json(), {'done': {}, 'fav': {}})

    # 2) CSRF:没有 X-Requested-With 不允许写
    r = c.post('/api/userstate', json={'done': {'zzz|活动A': 111}})
    check("无 CSRF 头返回 403", r.status_code, 403)

    # 3) 正常写入 + 读回
    r = c.post('/api/userstate', json={'done': {'zzz|活动A': 111}}, headers=H)
    check("写入 ok", r.get_json().get('ok'), True)
    check("读回 done", c.get('/api/userstate').get_json()['done'], {'zzz|活动A': 111})

    # 4) last-writer-wins:较早的时间戳不覆盖新值
    c.post('/api/userstate', json={'done': {'zzz|活动A': 100}}, headers=H)
    check("旧时间戳不覆盖", c.get('/api/userstate').get_json()['done'], {'zzz|活动A': 111})

    # 5) 取消:负时间戳(绝对值=取消时间)覆盖更早的标记,并能读回
    c.post('/api/userstate', json={'done': {'zzz|活动A': 222}}, headers=H)
    c.post('/api/userstate', json={'done': {'zzz|活动A': -333}}, headers=H)
    check("取消(负时间戳)生效", c.get('/api/userstate').get_json()['done'], {'zzz|活动A': -333})
    c.post('/api/userstate', json={'done': {'zzz|活动A': 250}}, headers=H)
    check("更早的标记不能撤销较新的取消", c.get('/api/userstate').get_json()['done'],
          {'zzz|活动A': -333})

    # 6) 非法时间戳被丢弃(负数=取消是合法的;字符串/0/超出上限丢弃)
    c.post('/api/userstate', json={'done': {'bad1': 0, 'bad2': 'abc',
                                            'bad3': 10 ** 15, 'good': 333}}, headers=H)
    check("非法值被过滤", sorted(c.get('/api/userstate').get_json()['done']),
          sorted(['zzz|活动A', 'good']))

    # 7) fav 与 done 相互独立
    c.post('/api/userstate', json={'fav': {'zzz|活动B': 444}}, headers=H)
    st = c.get('/api/userstate').get_json()
    check("fav 独立写入", st['fav'], {'zzz|活动B': 444})
    check("done 不受影响", st['done'], {'zzz|活动A': -333, 'good': 333})

    # 8) 上限截断:一次写 700 条,保留最新 600 条
    big = {'k%03d' % i: 1000 + i for i in range(700)}
    c.post('/api/userstate', json={'done': big}, headers=H)
    st = c.get('/api/userstate').get_json()
    keys = [k for k in st['done'] if k.startswith('k')]
    check("上限截断为 600", len(keys), 600)
    check("保留时间戳最新的(含 k699)", 'k699' in st['done'], True)
    check("丢弃时间戳最旧的(不含 k000)", 'k000' in st['done'], False)

    # 9) 落盘文件可被 _load_userstate 正常读回(utf-8-sig 容忍 BOM)
    with open(app.USERSTATE_FILE, 'w', encoding='utf-8-sig') as f:
        json.dump({'done': {'x': 12345}}, f, ensure_ascii=False)
    check("带 BOM 的文件也能读", app._load_userstate()['done'], {'x': 12345})

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
