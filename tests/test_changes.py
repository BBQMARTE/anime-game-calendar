# -*- coding: utf-8 -*-
"""活动变更追踪测试。

服务端每次抓取后对比上一轮,记录新增/改期/移除并挂 _change 角标;
前端列表显示「新增/改期」小标签,详情显示原时间。
运行:python tests/test_changes.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, 'static', 'index.html')
bad = 0


def check(label, got, expect):
    global bad
    ok = got == expect
    if not ok:
        bad += 1
    print("[%s] %s: got=%r expect=%r" % ('OK ' if ok else 'FAIL', label, got, expect))


def ev(gid, title, start, end=None, kind='event'):
    return {'id': '%s-%s' % (gid, title), 'game_id': gid, 'game': gid, 'title': title,
            'category': '活动', 'start': start, 'end': end, 'date': start,
            'link': '', 'image': '', 'src': 'manual', 'kind': kind}


def main():
    global bad
    tmp = tempfile.mkdtemp()
    real_file, real_state = app.CHANGES_FILE, app._state['events']
    real_changes = app._state['changes']
    app.CHANGES_FILE = os.path.join(tmp, 'changes.json')
    try:
        a = ev('hsr', '活动A', '2026-11-05T10:00', '2026-11-12T03:59')
        # ---- 首次基线:不把现有活动全标成新增 ----
        h = app._track_changes([], [a])
        check('首次基线不记新增', len(h), 0)
        check('基线落盘', os.path.exists(app.CHANGES_FILE), True)

        # ---- 新增 ----
        b = ev('hsr', '活动B', '2026-11-06T10:00', '2026-11-13T03:59')
        cur = [a, b]
        h = app._track_changes([a], cur)
        check('新增记为 new', h[app._change_key(b)]['type'], 'new')
        app._attach_changes(cur, h)
        check('新增条目挂角标', cur[1].get('_change', {}).get('type'), 'new')
        check('未变化条目不挂角标', '_change' in cur[0], False)

        # ---- 改期:id 因内容哈希变化也不影响识别 ----
        a2 = ev('hsr', '活动A', '2026-11-07T10:00', '2026-11-14T03:59')
        a2['id'] = 'hsr-活动A-moved'
        cur2 = [a2, b]
        h = app._track_changes(cur, cur2)
        rec = h[app._change_key(a2)]
        check('改期记为 moved', rec['type'], 'moved')
        check('保留原开始时间', rec['from']['start'], '2026-11-05T10:00')
        check('记录新开始时间', rec['to']['start'], '2026-11-07T10:00')
        app._attach_changes(cur2, h)
        check('改期条目挂角标', cur2[0]['_change']['type'], 'moved')
        check('角标带原时间', cur2[0]['_change']['from']['start'], '2026-11-05T10:00')

        # ---- 时间未变不重复记录 ----
        h = app._track_changes(cur2, cur2)
        check('未变化不重复记改期', h[app._change_key(a2)]['type'], 'moved')

        # ---- 移除:未来活动消失才记录 ----
        h = app._track_changes(cur2, [b])
        check('未来活动消失记为 removed', h[app._change_key(a2)]['type'], 'removed')
        dummy = ev('hsr', '活动A', '2026-11-07T10:00', '2026-11-14T03:59')
        app._attach_changes([dummy], {app._change_key(dummy):
                                      {'type': 'removed', 'at': app._bj_now().isoformat(timespec='seconds')}})
        check('removed 不挂角标', '_change' in dummy, False)

        expired = ev('hsr', '已结束活动', '2025-01-01T10:00', '2025-01-08T03:59')
        h = app._track_changes([expired], [])
        check('正常到期消失不记录', app._change_key(expired) in h, False)

        # ---- 旧记录裁剪:14 天前的角标不应继续出现 ----
        app._save_changes({'old|标题': {'type': 'new', 'at': '2026-01-01T00:00:00'}})
        h = app._track_changes([], [], now=datetime(2026, 10, 31, 9, 0))
        check('超过 14 天的变更被裁掉', len(h), 0)

        # ---- 摘要列表:按时间倒序、含 remov​ed、最多 20 条 ----
        hist = {
            'k1': {'type': 'moved', 'at': '2026-10-30T09:00:00',
                   'game_id': 'hsr', 'title': '活动A',
                   'from': {'start': '2026-11-01T10:00', 'end': ''},
                   'to': {'start': '2026-11-03T10:00', 'end': ''}},
            'k2': {'type': 'removed', 'at': '2026-10-31T09:00:00',
                   'game_id': 'wuwa', 'title': '活动B',
                   'from': {'start': '2026-11-02T10:00', 'end': ''}, 'to': None},
        }
        rows = app._changes_list(hist)
        check('摘要按时间倒序', rows[0]['key'], 'k2')
        check('摘要保留移除类型', rows[0]['type'], 'removed')
        check('摘要带上原时间', rows[1]['from']['start'], '2026-11-01T10:00')
        many = {str(i): {'type': 'new', 'at': '2026-10-31T00:00:%02d' % i} for i in range(30)}
        check('摘要最多 20 条', len(app._changes_list(many)), 20)

        # ---- 接口透出 ----
        client = app.app.test_client()
        app._state['events'] = [{'id': 'x', '_change': {'type': 'moved',
                                                       'from': {'start': '2026-11-01T10:00', 'end': ''}}}]
        app._state['changes'] = rows
        d = client.get('/api/events').get_json()
        check('/api/events 透出 _change', d['events'][0]['_change']['type'], 'moved')
        check('/api/events 带变更摘要', d['changes'][0]['type'], 'removed')
    finally:
        app.CHANGES_FILE = real_file
        app._state['events'] = real_state
        app._state['changes'] = real_changes
        shutil.rmtree(tmp, ignore_errors=True)

    # ---- 前端:标签与详情文案 ----
    node = shutil.which('node')
    if not node:
        print('SKIP: 未找到 node,跳过前端变更文案测试')
    else:
        loader = r"""
const fs = require('fs');
const src = fs.readFileSync(0, 'utf8');
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
const fn = new Function("const pad=n=>String(n).padStart(2,'0');" + grab('evStart') + '\n'
  + grab('evEnd') + '\n' + grab('fmtRange') + '\n'
  + grab('chgLabel') + '\n' + grab('chgFromText') + '\n' + grab('chgMovedLine') + '\n'
  + grab('chgTypeLabel') + '\n' + grab('chgDesc')
  + '\nreturn {chgLabel, chgMovedLine, chgTypeLabel, chgDesc};');
const g = fn();
console.log(JSON.stringify({
  none: g.chgLabel({}),
  moved: g.chgLabel({_change:{type:'moved'}}),
  added: g.chgLabel({_change:{type:'new'}}),
  line: g.chgMovedLine({start:'2026-11-07T10:00', end:'2026-11-14T03:59',
    _change:{type:'moved', from:{start:'2026-11-05T10:00', end:'2026-11-12T03:59'}}}),
  movedDesc: g.chgDesc({type:'moved', from:{start:'2026-11-05T10:00', end:'2026-11-12T03:59'},
    to:{start:'2026-11-07T10:00', end:'2026-11-14T03:59'}}),
  removedDesc: g.chgDesc({type:'removed', from:{start:'2026-11-02T10:00', end:''}, to:null}),
  newDesc: g.chgDesc({type:'new', from:null, to:{start:'2026-11-09T10:00', end:''}}),
  removedLabel: g.chgTypeLabel('removed'),
}));
"""
        r = subprocess.run([node, '-e', loader], input=open(HTML, encoding='utf-8').read(),
                           capture_output=True, text=True, encoding='utf-8', timeout=60)
        if r.returncode != 0:
            print('FAIL: JS 执行失败\n' + r.stderr[:600])
            bad += 1
        else:
            d = json.loads(r.stdout.strip().splitlines()[-1])
            check('无变更不显示标签', d['none'], '')
            check('改期标签', d['moved'], '改期')
            check('新增标签', d['added'], '新增')
            check('详情展示原→现时间', d['line'],
                  '官方改期 · 原 11月5日 10:00 ~ 11月12日 03:59 → 现 11月7日 10:00 ~ 11月14日 03:59')
            check('统计页改期文案', d['movedDesc'],
                  '原 11月5日 10:00 ~ 11月12日 03:59 → 现 11月7日 10:00 ~ 11月14日 03:59')
            check('统计页移除文案', d['removedDesc'], '已从官方排期移除 · 原 11月2日 10:00 起')
            check('统计页新增文案', d['newDesc'], '新增 · 11月9日 10:00 起')
            check('移除类型标签', d['removedLabel'], '移除')

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
