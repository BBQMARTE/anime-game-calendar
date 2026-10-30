# -*- coding: utf-8 -*-
"""离线模式导出口测试。

APK 本地模式(run 在 file:// 下)没有 Flask 服务端:此时拼 127.0.0.1:5000
会得到一个打不开的链接。apiOrigin() 在非 http(s) 时返回空串,调用方给出
「请先连接服务端」的提示。

运行:python3 tests/test_offline_guard.py(node 缺失则 SKIP)
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
const code = [grab('apiOrigin'), grab('icsUrl')].join('\n');
const make = (origin, query) => new Function('location','filterQuery',
  code + '\nreturn {apiOrigin,icsUrl};')({origin}, () => query);
const web = make('http://127.0.0.1:5000', '?games=hsr');
const online = make('https://example.com', '');
const offline = make('file:///android_asset/www/index.html', '');
console.log(JSON.stringify({
  webOrigin: web.apiOrigin(),
  webIcs: web.icsUrl(),
  httpsIcs: online.icsUrl(),
  offlineOrigin: offline.apiOrigin(),
  offlineIcs: offline.icsUrl(),
  guardCsv: html.includes('离线模式无法导出 CSV'),
  guardIcs: html.includes('离线模式无法生成订阅链接'),
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
        print('SKIP: 未找到 node，跳过离线导出测试')
        return 0
    r = subprocess.run([node, '-e', LOADER], input=open(HTML, encoding='utf-8').read(),
                       capture_output=True, text=True, encoding='utf-8', timeout=60)
    if r.returncode != 0:
        print('FAIL: node 执行失败\n' + r.stderr[:800])
        return 1
    d = json.loads(r.stdout.strip().splitlines()[-1])
    check("http 首页返回自身 origin", d['webOrigin'], 'http://127.0.0.1:5000')
    check("http 下 ICS 链接带筛选", d['webIcs'], 'http://127.0.0.1:5000/api/calendar.ics?games=hsr')
    check("https 下 ICS 链接可用", d['httpsIcs'], 'https://example.com/api/calendar.ics')
    check("file:// 下无服务端 origin", d['offlineOrigin'], '')
    check("file:// 下不拼 ICS 链接", d['offlineIcs'], '')
    check("CSV 导出有离线提示", d['guardCsv'], True)
    check("ICS 订阅有离线提示", d['guardIcs'], True)

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
