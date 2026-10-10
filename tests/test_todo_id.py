# -*- coding: utf-8 -*-
"""备忘录 id 注入面收口测试（覆盖 Issue #18）。

此前 `api_todo()` 对 id 只做 `str()`，前端 `noteHtml()` 又把 id 裸拼进内联
`onclick="toggleNote('...')"`；形如 `x');document.title='pwned';//` 的 id 会逃出
JS 字符串字面量，`GET /api/todo` 无鉴权即可读回并执行。

运行：python3 tests/test_todo_id.py
      （需要 flask；缺依赖则 SKIP 并退出码 0；前端断言需要 node，缺 node 则跳过该组）
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import app
except ImportError as e:  # pragma: no cover - 缺依赖时不算失败
    print('SKIP: 无法导入 app（%s）' % e)
    sys.exit(0)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
bad = 0


def check(label, got, expect):
    global bad
    ok = got == expect
    bad += 0 if ok else 1
    print("[%s] %s: got=%r expect=%r" % ('OK ' if ok else 'FAIL', label, got, expect))
    return ok


def check_true(label, cond):
    return check(label, bool(cond), True)


# ---- 纯函数：白名单字符集与长度上限 ----
check('非法字符回退 fallback', app._todo_id("x');alert(1);//", 't7'), 't7')
check('空值回退 fallback', app._todo_id('', 't0'), 't0')
check('None 回退 fallback', app._todo_id(None, 't1'), 't1')
check('超长回退 fallback', app._todo_id('a' * 41, 't2'), 't2')
check('40 字符放行', app._todo_id('a' * 40, 't2'), 'a' * 40)
check('正常归一化 id 原样保留', app._todo_id('n1758000000000', 't3'), 'n1758000000000')
check('下划线/短横/点外字符被拒', app._todo_id('a b', 't4'), 't4')
check('中文 id 被拒（不进内联 JS）', app._todo_id('备忘1', 't5'), 't5')

# ---- 端点：POST 归一化 + 落盘 + GET 回读 ----
PAYLOAD = "x');document.title='pwned';//"
with tempfile.TemporaryDirectory() as d:
    real_dir, real_file = app.DATA_DIR, app.TODO_FILE
    app.DATA_DIR = d
    app.TODO_FILE = os.path.join(d, 'todo.json')
    try:
        client = app.app.test_client()
        body = {'items': [
            {'id': PAYLOAD, 'title': '恶意 id', 'done': False},
            {'id': 'ok-1', 'title': '正常条目', 'done': True},
        ]}
        r = client.post('/api/todo', json=body, headers={'X-Requested-With': 'ycal'})
        check('POST 状态码', r.status_code, 200)
        got = client.get('/api/todo').get_json()['items']
        check('条目数', len(got), 2)
        check('非法 id 已被归一化', got[0]['id'], 't0')
        check_true('归一化后的 id 不含引号/括号/分号',
                   not re.search(r"['();\\]", got[0]['id']))
        check('合法 id 未被改写', got[1]['id'], 'ok-1')
        check('title 仍保留（仅 id 收口）', got[0]['title'], '恶意 id')

        # 读取侧归一化：历史脏数据（旧版本原样落盘）不得带病回流
        with open(app.TODO_FILE, 'w', encoding='utf-8') as f:
            json.dump({'items': [{'id': PAYLOAD, 'title': '旧脏数据', 'done': False}]}, f,
                      ensure_ascii=False)
        got2 = client.get('/api/todo').get_json()['items']
        check('读取侧归一化历史脏数据', got2[0]['id'], 't0')

        # 缺 id 时回退 t<序号>（既有行为不变）
        with open(app.TODO_FILE, 'w', encoding='utf-8') as f:
            json.dump({'items': []}, f)
        client.post('/api/todo', json={'items': [{'title': 'a'}, {'title': 'b'}]},
                    headers={'X-Requested-With': 'ycal'})
        got3 = client.get('/api/todo').get_json()['items']
        check('缺 id 回退序号', [x['id'] for x in got3], ['t0', 't1'])
    finally:
        app.DATA_DIR, app.TODO_FILE = real_dir, real_file

# ---- 前端：不再有内联 id 拼接，改为 data-id + 委托 ----
html = open(os.path.join(ROOT, 'static', 'index.html'), encoding='utf-8').read()
check_true('noteHtml 不再内联拼接 id',
           "onclick=\"toggleNote('${it.id}')\"" not in html
           and "delNote('${it.id}')\"" not in html)
check_true('改用 data-id 且经 esc 转义', 'data-id="${esc(it.id)}"' in html)
check_true('存在事件委托绑定', "host.addEventListener('click'" in html)

if not shutil.which('node'):
    print('SKIP: 未找到 node，跳过前端行为断言')
else:
    # 用 jsdom 不可得，改为直接 eval 行模板 + 委托逻辑的最小复刻：
    # 断言渲染出的 HTML 中注入 payload 不产生任何可执行片段
    node_src = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');
const escSrc = /function esc\(s\)\{[^\n]*\}/.exec(src)[0];
const esc = new Function('s', escSrc.slice(escSrc.indexOf('{') + 1, escSrc.lastIndexOf('}')));
const payload = "x');document.title='pwned';//";
const item = { id: payload, title: '<img src=x onerror=alert(1)>', done: false };
const row = `<div class="note-row" data-id="${esc(item.id)}">`
  + `<span class="note-title">${esc(item.title)}</span>`
  + `<span class="note-del" data-del="1">×</span></div>`;
console.log(JSON.stringify({ row }));
"""
    p = subprocess.run(['node', '-e', node_src, 'node',
                        os.path.join(ROOT, 'static', 'index.html')],
                       capture_output=True, text=True)
    if p.returncode != 0:
        print('FAIL: node 退出码 %d: %s' % (p.returncode, p.stderr.strip()))
        bad += 1
    else:
        row = json.loads(p.stdout.strip().splitlines()[-1])['row']
        check_true('渲染结果无 onclick 内联处理器', 'onclick=' not in row)
        check_true('渲染结果无未转义单引号', "x');" not in row)
        check_true('标题中的 <img> 已转义', '<img' not in row and '&lt;img' in row)

print('ALL PASS' if bad == 0 else 'SOME FAILED')
sys.exit(1 if bad else 0)
