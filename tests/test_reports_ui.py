# -*- coding: utf-8 -*-
"""「我的反馈」入口测试(设置 → 我的反馈 → 清单,待核查可撤回 / 只看待核查 / 清除已处理)。

用户点过「缺图 / 缺结束时间 / 时间不对」后,只弹一句「已反馈」就没有下文了。
现在设置里能打开反馈清单:显示提交了什么、什么时候、以及是「待核查」还是「已处理」
(done 由每日核查 Agent 回写)。离线 APK 连不到服务端,要给明确提示而不是空面板。

运行:python tests/test_reports_ui.py(node 缺失则 SKIP)
"""
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, 'static', 'index.html')

LOADER = r"""
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
const captured = [], alerts = [];
const documentStub = {
  createElement: () => ({ className: '', innerHTML: '', addEventListener(){}, querySelector(){ return null; } }),
  body: { appendChild(o) { captured.push(o); } },
};
const REPORT_LABEL = {'missing-image':'缺图','wrong-time':'时间不对','other':'其他','no-end':'缺结束时间'};
const gameName = id => ({hsr:'崩坏：星穹铁道', zzz:'绝区零'})[id] || '自定义';
const esc = s => String(s == null ? '' : s);
const items = [
  {game_id:'hsr', title:'画外遗光', kind:'no-end', at:'2026-10-31T09:20:00', done:false, note:''},
  {game_id:'zzz', title:'限定角色活动', kind:'missing-image', at:'2026-10-30T18:00:00', done:true, note:'已补图'},
];
const fetchStub = () => Promise.resolve({ json: () => Promise.resolve({ items }) });
const mk = (origin) => new Function('fetch','document','apiOrigin','esc','gameName','REPORT_LABEL',
  'attachSwipeClose','alert','_repPending', grab('openReports') + '\nreturn openReports;')(
    fetchStub, documentStub, () => origin, esc, gameName, REPORT_LABEL, () => {},
    (m) => alerts.push(m), false);
mk('http://127.0.0.1:5000')();
mk('')();   // 离线:apiOrigin 为空
// 清除已处理:DElETE {done:true}
const clearReq = [], clearFlash = [];
const clearFetch = (u, opt) => { clearReq.push({method: opt.method, body: JSON.parse(opt.body),
  csrf: opt.headers['X-Requested-With']}); return Promise.resolve({json: () => Promise.resolve({ok: true, removed: 1})}); };
const clearFn = new Function('fetch','flash','refreshReports','confirm',
  grab('clearReportsDone') + '\nreturn clearReportsDone;')(
    clearFetch, m => clearFlash.push(m), () => {}, () => true);
clearFn(1);
setTimeout(() => {
  console.log(JSON.stringify({
    html: captured.length ? captured[0].innerHTML : '',
    alerts,
    hasEntry: src.includes('onclick="openReports()"'),
    hasFn: src.includes('function openReports('),
    hasToggle: src.includes('function toggleRepPending(') && src.includes("_repPending?'显示全部':'只看待核查'"),
    hasClear: src.includes('function clearReportsDone('),
    clearReq: clearReq[0], clearFlash: clearFlash[0],
  }));
}, 20);
"""

bad = 0


def check(label, got, expect):
    global bad
    ok = got == expect
    if not ok:
        bad += 1
    print("[%s] %s: got=%r expect=%r" % ('OK ' if ok else 'FAIL', label, got, expect))


def main():
    node = shutil.which('node')
    if not node:
        print('SKIP: 未找到 node')
        return 0
    r = subprocess.run([node, '-e', LOADER], input=open(HTML, encoding='utf-8').read(),
                       capture_output=True, text=True, encoding='utf-8', timeout=60)
    if r.returncode != 0:
        print('FAIL: node 执行失败\n' + r.stderr[:800])
        return 1
    d = json.loads(r.stdout.strip().splitlines()[-1])
    out = d['html']

    check("设置里有「我的反馈」入口", d['hasEntry'], True)
    check("openReports 已实现", d['hasFn'], True)
    check("面板标题正确", '我的反馈' in out, True)
    check("统计待核查条数", '待核查 1 条' in out, True)
    check("缺结束时间标签", '缺结束时间' in out, True)
    check("缺图标签", '缺图' in out, True)
    check("已处理状态", '已处理' in out, True)
    check("待核查状态", '待核查' in out, True)
    check("显示补图备注", '已补图' in out, True)
    check("显示游戏名与时间", '崩坏：星穹铁道' in out and '10-31 09:20' in out, True)
    check("离线模式有明确提示", any('离线模式看不到反馈清单' in a for a in d['alerts']), True)
    check("待核查反馈有撤回按钮(已处理没有)", d['html'].count('>撤回</span>'), 1)
    check("有「只看待核查」入口", ('只看待核查' in out), True)
    check("有「清除已处理」入口并带条数", '清除已处理 · 1' in out, True)
    check("toggleRepPending 已实现", d['hasToggle'], True)
    check("clearReportsDone 已实现", d['hasClear'], True)
    check("清除请求用 DELETE + CSRF + done:true",
          (d['clearReq']['method'], d['clearReq']['body'], d['clearReq']['csrf']),
          ('DELETE', {'done': True}, 'ycal'))
    check("清除成功有提示", '已清除' in (d['clearFlash'] or ''), True)

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
