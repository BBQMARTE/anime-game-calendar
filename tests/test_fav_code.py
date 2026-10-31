# -*- coding: utf-8 -*-
"""收藏同步码(网页 ↔ 离线 APK 互导收藏)测试。

收藏平时靠服务端 userstate 跨设备合并,但离线 APK 走 file:// 连不到服务端,
收藏只存在本机。同步码把「正向收藏」编码成 YCALFAV1:<base64(JSON)>:
  - 只带收藏,不带取消(负值),导入不会把别人的收藏弄丢;
  - 导入走 mergeTS(按时间戳绝对值合并),本机更新的状态优先;
  - 非法前缀 / 截断的 base64 一律判无效,不会写坏本地状态。

运行:python tests/test_fav_code.py(node 缺失则 SKIP)
"""
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, 'static', 'index.html')
HTML_ANDROID = os.path.join(ROOT, 'android', 'app', 'src', 'main', 'assets', 'www', 'index.html')

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
const api = new Function(grab('favCodeOf') + '\n' + grab('decodeFavCode') + '\n' + grab('mergeTS') +
  '\nreturn {favCodeOf, decodeFavCode, mergeTS};')();
const unicode = {'hsr|活动·限定': 1700000000000};
const mixed = api.favCodeOf({'a|活动A': 111, 'b|活动B': -222});
console.log(JSON.stringify({
  code: mixed,
  mixedKeys: Object.keys(api.decodeFavCode(mixed) || {}),
  round: api.decodeFavCode(api.favCodeOf(unicode)),
  empty: api.favCodeOf({}),
  negOnly: api.decodeFavCode(api.favCodeOf({'x|X': -1})),
  badPrefix: api.decodeFavCode('YCALFAV2:AAAA'),
  badBase64: api.decodeFavCode('YCALFAV1:!!!!'),
  truncated: api.decodeFavCode('YCALFAV1:eyJh'),
  otherText: api.decodeFavCode('hello'),
  newerWins: api.mergeTS({'k|K': 1000}, {'k|K': 2000}),
  olderIgnored: api.mergeTS({'k|K': 2000}, {'k|K': 1000}),
  added: api.mergeTS({'a|A': 1000}, {'b|B': 500}),
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

    check("编码带固定前缀", d['code'].startswith('YCALFAV1:'), True)
    check("负值(已取消)不写进收藏码", d['mixedKeys'], ['a|活动A'])
    check("中文键值往返一致", d['round'], {'hsr|活动·限定': 1700000000000})
    check("没有收藏时返回空串", d['empty'], '')
    check("全是负值时生成空码(判无效)", d['negOnly'], None)
    check("错误前缀判无效", d['badPrefix'], None)
    check("非法 base64 判无效", d['badBase64'], None)
    check("截断的收藏码判无效", d['truncated'], None)
    check("普通文本判无效", d['otherText'], None)
    check("较新的收藏时间胜出", d['newerWins'], {'k|K': 2000})
    check("较旧的导入不覆盖本机", d['olderIgnored'], {'k|K': 2000})
    check("缺失的收藏会被补上", d['added'], {'a|A': 1000, 'b|B': 500})

    src = open(HTML, encoding='utf-8').read()
    check("设置里有收藏同步码入口", '收藏同步码' in src, True)
    check("有复制收藏码按钮", 'onclick="copyFavCode()"' in src, True)
    check("有导入收藏码按钮", 'onclick="importFavCode()"' in src, True)
    check("导入框 id 固定", 'id="favCodeIn"' in src, True)

    assets = open(HTML_ANDROID, encoding='utf-8').read() if os.path.exists(HTML_ANDROID) else ''
    check("APK assets 已同步同步码", '收藏同步码' in assets, True)

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
