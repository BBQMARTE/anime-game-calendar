# -*- coding: utf-8 -*-
"""用户报错/缺图反馈(/api/report)测试。

离线跑:临时文件替换真实 data/reports.json,不产生副作用。
运行:python3 tests/test_report.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

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


def main():
    tmp = tempfile.mkdtemp(prefix='ycal_rp_')
    app.REPORT_FILE = os.path.join(tmp, 'reports.json')
    c = app.app.test_client()
    H = {'X-Requested-With': 'ycal'}

    check("初始为空", c.get('/api/report').get_json()['items'], [])

    # CSRF
    r = c.post('/api/report', json={'title': '活动A', 'game_id': 'zzz', 'kind': 'missing-image'})
    check("无 CSRF 头被拒", r.status_code, 403)

    # 缺标题
    r = c.post('/api/report', json={'game_id': 'zzz'}, headers=H)
    check("缺标题返回 400", r.status_code, 400)

    # 正常写入
    r = c.post('/api/report', json={'title': '活动A', 'game_id': 'zzz',
                                    'kind': 'missing-image', 'note': '封面没有'}, headers=H)
    j = r.get_json()
    check("写入 ok", j.get('ok'), True)
    items = c.get('/api/report').get_json()['items']
    check("记录条数", len(items), 1)
    check("字段落盘", (items[0]['game_id'], items[0]['title'], items[0]['kind'], items[0]['done']),
          ('zzz', '活动A', 'missing-image', False))

    # 10 分钟内同类型重复 → 去重,不重复计数
    c.post('/api/report', json={'title': '活动A', 'game_id': 'zzz', 'kind': 'missing-image'}, headers=H)
    check("重复反馈被去重", len(c.get('/api/report').get_json()['items']), 1)

    # 不同类型允许并存
    c.post('/api/report', json={'title': '活动A', 'game_id': 'zzz', 'kind': 'wrong-time'}, headers=H)
    check("不同类型单独记", len(c.get('/api/report').get_json()['items']), 2)

    # 缺结束时间:独立类型(前端只对无 end 的条目显示该按钮)
    c.post('/api/report', json={'title': '活动A', 'game_id': 'zzz', 'kind': 'no-end'}, headers=H)
    items = c.get('/api/report').get_json()['items']
    check("缺结束时间不再回落 other", items[-1]['kind'], 'no-end')

    # 非法 kind 回落 other
    c.post('/api/report', json={'title': '活动B', 'game_id': 'hsr', 'kind': 'boom'}, headers=H)
    items = c.get('/api/report').get_json()['items']
    check("非法 kind 回落 other", items[-1]['kind'], 'other')

    # 标题超长截断
    c.post('/api/report', json={'title': 'x' * 300, 'game_id': 'wuwa'}, headers=H)
    items = c.get('/api/report').get_json()['items']
    check("标题截断到 120", len(items[-1]['title']), 120)

    # 上限:写入 400 条,只保留最近 300
    for i in range(400):
        c.post('/api/report', json={'title': '批量%d' % i, 'game_id': 'hsr', 'kind': 'other'}, headers=H)
    items = c.get('/api/report').get_json()['items']
    check("上限截断 300", len(items), 300)
    check("保留最新的一条", items[-1]['title'], '批量399')

    # ---- 前端:「缺结束时间」只在无 end 的条目出现,点击上报 kind=no-end ----
    src = open(HTML, encoding='utf-8').read()
    check("详情页有「缺结束时间」入口", "reportEv('${e.id}','no-end')" in src, True)
    check("入口受 e.end 控制", "e.end?'':" in src, True)

    node = shutil.which('node')
    if not node:
        print('SKIP: 未找到 node,跳过前端反馈测试')
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
const posted = [], alerts = [];
const DATA = {events:[{id:'x',game_id:'endfield',title:'画外遗光',
  start:'2026-11-12T12:00',end:null,link:'https://example.com/e'}]};
const REPORT_LABEL = {'missing-image':'缺图','wrong-time':'时间不对','other':'其他','no-end':'缺结束时间'};
const fetchStub = (u, opt) => { posted.push(JSON.parse(opt.body));
  return Promise.resolve({json: () => Promise.resolve({ok:true})}); };
const fn = new Function('DATA','REPORT_LABEL','fetch','alert','prompt',
  grab('reportEv') + '\nreturn reportEv;');
fn(DATA, REPORT_LABEL, fetchStub, m => alerts.push(m), () => '')('x','no-end');
setTimeout(() => console.log(JSON.stringify({payload:posted[0], alert:alerts[0]})) , 0);
"""
        r = subprocess.run([node, '-e', loader], input=src,
                           capture_output=True, text=True, encoding='utf-8', timeout=60)
        if r.returncode != 0:
            print('FAIL: JS 执行失败\n' + r.stderr[:600])
            globals()['bad'] = 1
        else:
            d = json.loads(r.stdout.strip().splitlines()[-1])
            check("前端上报 kind=no-end", d['payload']['kind'], 'no-end')
            check("前端带上结束时间为空", d['payload']['end'], None)
            check("反馈成功提示含类型名", '缺结束时间' in (d['alert'] or ''), True)

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
