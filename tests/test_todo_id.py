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

        # 同批 id 必须唯一：归一化会把「唯一但脏」的历史 id 折成同一个兜底值
        with open(app.TODO_FILE, 'w', encoding='utf-8') as f:
            json.dump({'items': [{'id': 't1', 'title': '重要备忘A'},
                                 {'id': PAYLOAD, 'title': '备忘B'}]}, f,
                      ensure_ascii=False)
        got4 = [x['id'] for x in client.get('/api/todo').get_json()['items']]
        check('读取侧两条不同条目不共用 id', len(set(got4)), 2)
        check('合法 id 优先保留', got4[0], 't1')

        client.post('/api/todo', json={'items': [{'title': 'A'}, {'id': 't0', 'title': 'B'}]},
                    headers={'X-Requested-With': 'ycal'})
        got5 = [x['id'] for x in client.get('/api/todo').get_json()['items']]
        check('写入侧缺 id 条目不与显式 t0 撞车', got5, ['t0', 't1'])
        client.post('/api/todo', json={'items': [{'id': 't0', 'title': 'A'},
                                                 {'id': 't0', 'title': 'B'}]},
                    headers={'X-Requested-With': 'ycal'})
        got6 = [x['id'] for x in client.get('/api/todo').get_json()['items']]
        check('重复 id 被补号', len(set(got6)), 2)
    finally:
        app.DATA_DIR, app.TODO_FILE = real_dir, real_file

# ---- 前端：不再有内联 id 拼接，改为 data-id + 委托 ----
html = open(os.path.join(ROOT, 'static', 'index.html'), encoding='utf-8').read()
check_true('noteHtml 不再内联拼接 id',
           "onclick=\"toggleNote('${it.id}')\"" not in html
           and "delNote('${it.id}')\"" not in html)
check_true('改用 data-id 且经 esc 转义', 'data-id="${esc(it.id)}"' in html)
check_true('存在事件委托绑定', "host.addEventListener('click'" in html)
check_true('备忘行有修改入口', '<span class="note-edit" data-edit="1"' in html)
check_true('委托优先处理修改', "closest('.note-edit')" in html and 'editNote(id)' in html)

if not shutil.which('node'):
    print('SKIP: 未找到 node，跳过前端行为断言')
else:
    # 用 jsdom 不可得，改为从 index.html 抽出真实 esc()/noteHtml() 源码求值，
    # 断言渲染结果本身（此前断言的是脚本里另写的一份模板，不随被测文件变化）
    node_src = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');
const take = (name) => {
  const m = new RegExp('function ' + name + '\\(').exec(src);
  if (!m) throw new Error('not found: ' + name);
  let i = src.indexOf('{', m.index), depth = 0;
  for (let j = i; j < src.length; j++) {
    if (src[j] === '{') depth++;
    else if (src[j] === '}') { depth--; if (!depth) return src.slice(i + 1, j); }
  }
  throw new Error('unbalanced: ' + name);
};
const esc = new Function('s', take('esc'));
// noteHtml 正文引用了 memoTpl/tagText 等模块级函数，这里以 stub 形参补上
// (payload 非 weekly 条目，tagText 不会被实际调用)
const noteHtml = new Function('NOTES', 'notesReady', 'esc', 'memoTpl', 'tagText', take('noteHtml'));
const payload = "x');document.title='pwned';//";
const NOTES = { items: [{ id: payload, title: '<img src=x onerror=alert(1)>', done: false }] };
console.log(JSON.stringify({ html: noteHtml(NOTES, true, esc, () => [], () => '#fff') }));
"""
    p = subprocess.run(['node', '-e', node_src, 'node',
                        os.path.join(ROOT, 'static', 'index.html')],
                       capture_output=True, text=True)
    if p.returncode != 0:
        print('FAIL: node 退出码 %d: %s' % (p.returncode, p.stderr.strip()))
        bad += 1
    else:
        row = json.loads(p.stdout.strip().splitlines()[-1])['html']
        check_true('渲染结果无 toggleNote 内联处理器', 'onclick="toggleNote' not in row)
        check_true('id 经 HTML 实体化后落在 data-id', 'data-id="x&#39;);document.title=&#39;pwned&#39;;//"' in row)
        check_true('渲染结果无未转义单引号', "x');" not in row)
        check_true('标题中的 <img> 已转义', '<img' not in row and '&lt;img' in row)

    # 修改备忘:只改标题,保留 id / 打钩 / 每周标记;空值与未改动不保存
    edit_src = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');
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
const NOTES = { items: [{ id: 'n1', title: '清体力', done: true, cycle: 'weekly', done_week: '2026-W44' }] };
const saved = [], mounted = [], flashed = [];
let answer = '  领邮件  ';
const fn = new Function('NOTES','prompt','saveNotes','mountNotes','flash',
  grab('editNote') + '\nreturn editNote;')(
  NOTES, () => answer, () => saved.push(1), () => mounted.push(1), m => flashed.push(m));
fn('n1');
const after = NOTES.items[0];
answer = '领邮件'; fn('n1');   // 内容未变:不保存
answer = '   ';   fn('n1');   // 空白:不保存
fn('nope');                   // 未知 id:不保存
console.log(JSON.stringify({ title: after.title, done: after.done, cycle: after.cycle,
  week: after.done_week, saves: saved.length, mounts: mounted.length,
  flash: flashed[flashed.length - 1] }));
"""
    q = subprocess.run(['node', '-e', edit_src, 'node',
                        os.path.join(ROOT, 'static', 'index.html')],
                       capture_output=True, text=True)
    if q.returncode != 0:
        print('FAIL: 备修改 node 执行失败: %s' % q.stderr.strip())
        bad += 1
    else:
        d = json.loads(q.stdout.strip().splitlines()[-1])
        check('修改后备忘标题(去空格)', d['title'], '领邮件')
        check('修改保留打钩状态', d['done'], True)
        check('修改保留每周标记', (d['cycle'], d['week']), ('weekly', '2026-W44'))
        check('只保存一次(空值/未改/未知 id 不写)', d['saves'], 1)
        check('修改后重渲染', d['mounts'], 1)
        check('修改成功有提示', '修改' in (d['flash'] or ''), True)

    # 每周模板修改:同名拒绝、空值不改、改名后保存并重开面板
    tpl_src = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');
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
let cur = ['清体力', '打周本'];
let answer = '  清理体力  ';
const saved = [], alerts = [], reopened = [];
const fn = new Function('memoTpl','saveMemoTpl','prompt','alert','closeTopOverlay','openMemoTpl',
  grab('editMemoTplRow') + '\nreturn editMemoTplRow;')(
  () => cur.slice(), a => { cur = a.slice(); saved.push(cur); },
  () => answer, m => alerts.push(m), () => {}, () => reopened.push(1));
fn(0);                 // 改名成功
answer = '打周本'; fn(0);   // 与另一条重名 → 拒绝
answer = '   ';   fn(0);   // 空白 → 不保存
answer = '打周本'; fn(1);   // 内容未变 → 不保存
console.log(JSON.stringify({cur: cur, saves: saved.length, reopened: reopened.length,
  alerts: alerts}));
"""
    t = subprocess.run(['node', '-e', tpl_src, 'node',
                        os.path.join(ROOT, 'static', 'index.html')],
                       capture_output=True, text=True)
    if t.returncode != 0:
        print('FAIL: 模板修改 node 执行失败: %s' % t.stderr.strip())
        bad += 1
    else:
        d = json.loads(t.stdout.strip().splitlines()[-1])
        check('模板改名生效', d['cur'], ['清理体力', '打周本'])
        check('模板只保存一次(重名/空白/未改不写)', d['saves'], 1)
        check('模板改名后重开面板', d['reopened'], 1)
        check('重名有提示', any('同名' in a for a in d['alerts']), True)

check_true('模板行有修改入口', 'data-tedit="${i}"' in html)
check_true('模板操作走 editMemoTplRow', 'editMemoTplRow(+ed.dataset.tedit)' in html)

print('ALL PASS' if bad == 0 else 'SOME FAILED')
sys.exit(1 if bad else 0)
