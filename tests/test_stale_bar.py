# -*- coding: utf-8 -*-
"""数据陈旧提示测试。

抓取连续失败时列表看起来正常,但其实数据没更新。超过 24 小时应显示
「数据已 N 小时/天未更新」的橙色提示条,点击立即刷新;24 小时内不打扰。

运行:python3 tests/test_stale_bar.py(node 缺失则 SKIP)
"""
import json, os, shutil, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, 'static', 'index.html')

LOADER = r"""
const fs = require('fs');
const html = fs.readFileSync(0, 'utf8');
const src = (html.match(/<script>[\s\S]*?<\/script>/g) || [])
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
const staleText = new Function(grab('staleText') + '\nreturn staleText;')();
const now = Date.parse('2026-10-31T12:00:00');   // 本地时区
console.log(JSON.stringify({
  fresh: staleText('2026-10-31T04:00:00', now),     // 8 小时
  h23: staleText('2026-10-30T13:00:00', now),       // 23 小时
  h24: staleText('2026-10-30T12:00:00', now),       // 24 小时
  h25: staleText('2026-10-30T11:00:00', now),       // 25 小时
  h46: staleText('2026-10-29T14:00:00', now),       // 46 小时
  d3: staleText('2026-10-28T12:00:00', now),        // 72 小时
  empty: staleText('', now),
  invalid: staleText('not-a-date', now),
  hasElement: html.includes('id="staleBar"'),
  hasCall: html.includes('renderStale()'),
  hasCss: html.includes('.stale-bar.show{display:block}'),
  hasClick: html.includes('onclick="doRefresh()" role="button" aria-label="数据陈旧,立即刷新"'),
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
        print('SKIP: 未找到 node，跳过数据陈旧提示测试')
        return 0
    r = subprocess.run([node, '-e', LOADER], input=open(HTML, encoding='utf-8').read(),
                       capture_output=True, text=True, encoding='utf-8', timeout=60)
    if r.returncode != 0:
        print('FAIL: node 执行失败\n' + r.stderr[:800])
        return 1
    d = json.loads(r.stdout.strip().splitlines()[-1])
    check("8 小时内不提示", d['fresh'], '')
    check("23 小时内不提示", d['h23'], '')
    check("正好 24 小时开始提示", d['h24'], '数据已 24 小时未更新,自动抓取可能异常 · 点此立即刷新')
    check("25 小时仍按小时显示", d['h25'], '数据已 25 小时未更新,自动抓取可能异常 · 点此立即刷新')
    check("46 小时仍按小时显示", d['h46'], '数据已 46 小时未更新,自动抓取可能异常 · 点此立即刷新')
    check("72 小时改为按天显示", d['d3'], '数据已 3 天未更新,自动抓取可能异常 · 点此立即刷新')
    check("无 updated 不提示", d['empty'], '')
    check("非法时间不提示", d['invalid'], '')
    check("页面含提示条元素", d['hasElement'], True)
    check("render() 会调用 renderStale", d['hasCall'], True)
    check("提示条显示样式已写入", d['hasCss'], True)
    check("点击提示条触发刷新", d['hasClick'], True)

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
