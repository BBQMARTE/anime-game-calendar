# -*- coding: utf-8 -*-
"""键盘可达性测试。

页面里大量筛选 chip / 日历格 / 列表行是「只有 onclick 的 span/div」,
鼠标能点但键盘无法聚焦。渲染后统一补 role=button + tabindex,
并让 Enter / 空格直接触发点击;按钮元素本身可聚焦,不重复处理。

运行:python tests/test_a11y_click.py(node 缺失则 SKIP)
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
const fn = new Function(grab('a11yScan') + '\nreturn a11yScan;')();
const mk = (tag, attrs) => {
  const a = Object.assign({}, attrs || {});
  return { tagName: tag, getAttribute: k => (k in a ? a[k] : null),
           setAttribute: (k, v) => { a[k] = v; }, _attrs: a };
};
const span = mk('SPAN');
const div = mk('DIV');
const btn = mk('BUTTON');
const kept = mk('SPAN', {tabindex: '-1', role: 'link'});
fn({querySelectorAll: () => [span, div, btn, kept]});
// 弹窗挂载:appendChild 后自动扫描,弹窗里的重排/关闭等 div 才能键盘操作
const appended = [];
const mount = new Function('document', 'a11yScan', grab('mountOverlay') + '\nreturn mountOverlay;')(
  {body: {appendChild: x => appended.push(x)}}, fn);
const closeBtn = mk('DIV');
const title = {textContent: '数据统计'};
let focused = 0;
const fakeClose = {focus: () => { focused++; }};
const fakeOverlay = mk('DIV');
fakeOverlay.querySelectorAll = () => [closeBtn];
fakeOverlay.querySelector = (s) => (s === '.dtitle' ? title : s === '.detail-close' ? fakeClose : null);
const ret = mount(fakeOverlay);
console.log(JSON.stringify({
  span: span._attrs,
  div: div._attrs,
  btn: btn._attrs,
  kept: kept._attrs,
  hasFn: src.includes('function a11yScan('),
  scansList: src.includes("a11yScan($('#list'))"),
  scansFilters: src.includes("a11yScan($('#filters'))"),
  keyCase: src.includes("e.key!=='Enter'&&e.key!==' '"),
  focusCss: src.includes('[role="button"]:focus-visible'),
  hasMount: src.includes('function mountOverlay('),
  mountCalls: src.split('mountOverlay(').length - 1,
  mountedSpan: closeBtn._attrs,
  overlayAttrs: fakeOverlay._attrs,
  focused: focused,
  appendedOnce: appended.length,
  returned: ret === fakeOverlay,
  closeAria: (src.match(/class="detail-close" role="button" tabindex="0" aria-label="关闭"/g) || []).length,
  notifyScan: src.includes('a11yScan(box)'),
  calAria: (src.match(/class="cal-cell[^>]*aria-label="\$\{[^}]*\}月\$\{[^}]*\}日/g) || []).length,
  calAriaCount: src.includes("'，'+cntDay+' 个活动'"),
}));
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

    check('a11yScan 已实现', d['hasFn'], True)
    check('span 补上 tabindex 与 role',
          (d['span'].get('tabindex'), d['span'].get('role')), ('0', 'button'))
    check('div 同样可聚焦', (d['div'].get('tabindex'), d['div'].get('role')), ('0', 'button'))
    check('按钮元素不重复处理', d['btn'], {})
    check('已有的 tabindex / role 不被覆盖',
          (d['kept'].get('tabindex'), d['kept'].get('role')), ('-1', 'link'))
    check('列表渲染后扫描', d['scansList'], True)
    check('筛选 chip 渲染后扫描', d['scansFilters'], True)
    check('Enter / 空格触发点击', d['keyCase'], True)
    check('有可见焦点环样式', d['focusCss'], True)
    check('弹窗挂载统一扫描键盘可达', d['hasMount'], True)
    check('7 个弹窗都走 mountOverlay', d['mountCalls'], 8)
    check('挂载后弹窗内 div 补上 role/tabindex',
          (d['mountedSpan'].get('tabindex'), d['mountedSpan'].get('role')), ('0', 'button'))
    check('弹窗本身有 dialog 语义并用标题作 aria-label',
          (d['overlayAttrs'].get('role'), d['overlayAttrs'].get('aria-modal'),
           d['overlayAttrs'].get('aria-label')), ('dialog', 'true', '数据统计'))
    check('打开弹窗后焦点落在关闭按钮', d['focused'], 1)
    check('挂载时追加到 body 一次', d['appendedOnce'], 1)
    check('mountOverlay 返回弹窗本身', d['returned'], True)
    check('7 个弹窗关闭按钮都有语义', d['closeAria'], 7)
    check('异步渲染的提醒配置也扫描', d['notifyScan'], True)
    check('日历格有「月日 + 活动数」的 aria-label', d['calAria'] >= 1, True)
    check('日历格 aria-label 带活动条数', d['calAriaCount'], True)

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
