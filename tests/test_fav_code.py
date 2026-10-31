# -*- coding: utf-8 -*-
"""状态同步码(网页 ↔ 离线 APK 互导收藏与打钩)测试。

收藏/打钩平时靠服务端 userstate 跨设备合并,但离线 APK 走 file:// 连不到服务端,
状态只存在本机。状态码把「正向收藏 + 正向打钩」编码成:
  YCALSYNC1:<base64(JSON {fav, done})>
  - 只带正向状态,取消(负值)不进码,导入不会把别人的记录弄丢;
  - 导入走 mergeTS(按时间戳绝对值合并),本机更新的操作优先;
  - 兼容 v1.9.10 的 YCALFAV1(仅收藏)旧码;
  - 非法前缀 / 截断 base64 / 普通文本一律判无效。

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
const api = new Function(['posOnly','stateCodeOf','decodeStateCode','mergeTS'].map(grab).join('\n') +
  '\nreturn {posOnly, stateCodeOf, decodeStateCode, mergeTS};')();
const unicode = {fav:{'hsr|活动·限定': 1700000000000}, done:{'zzz|签到活动': 1700000001000}};
const mixed = api.stateCodeOf({'a|活动A': 111, 'b|活动B': -222}, {'c|已做完': 333, 'd|取消': -444});
const code = api.stateCodeOf(unicode.fav, unicode.done);
const legacy = 'YCALFAV1:' + btoa(unescape(encodeURIComponent(JSON.stringify({'x|旧收藏': 555}))));
console.log(JSON.stringify({
  code: code,
  round: api.decodeStateCode(code),
  mixed: api.decodeStateCode(mixed),
  empty: api.stateCodeOf({}, {}),
  onlyNeg: api.stateCodeOf({'x|X': -1}, {'y|Y': -2}),
  legacy: api.decodeStateCode(legacy),
  badPrefix: api.decodeStateCode('YCALSYNC2:AAAA'),
  badBase64: api.decodeStateCode('YCALSYNC1:!!!!'),
  truncated: api.decodeStateCode('YCALSYNC1:eyJh'),
  otherText: api.decodeStateCode('hello'),
  newerWins: api.mergeTS({'k|K': 1000}, {'k|K': 2000}, ),
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

    check("状态码带固定前缀", d['code'].startswith('YCALSYNC1:'), True)
    check("中文键值往返一致", d['round'],
          {'fav': {'hsr|活动·限定': 1700000000000}, 'done': {'zzz|签到活动': 1700000001000}})
    check("取消(负值)不写进码", d['mixed'],
          {'fav': {'a|活动A': 111}, 'done': {'c|已做完': 333}})
    check("两手空空返回空串", d['empty'], '')
    check("全是负值时生成空码(判无效)", d['onlyNeg'], '')
    check("旧版收藏码仍可导入", d['legacy'], {'fav': {'x|旧收藏': 555}, 'done': {}})
    check("错误前缀判无效", d['badPrefix'], None)
    check("非法 base64 判无效", d['badBase64'], None)
    check("截断的状态码判无效", d['truncated'], None)
    check("普通文本判无效", d['otherText'], None)
    check("较新的操作时间胜出", d['newerWins'], {'k|K': 2000})
    check("较旧的导入不覆盖本机", d['olderIgnored'], {'k|K': 2000})
    check("缺失的记录会被补上", d['added'], {'a|A': 1000, 'b|B': 500})

    src = open(HTML, encoding='utf-8').read()
    check("设置里有状态同步码入口", '状态同步码' in src, True)
    check("有复制状态码按钮", 'onclick="copyStateCode()"' in src, True)
    check("有导入状态码按钮", 'onclick="importStateCode()"' in src, True)
    check("导入框 id 固定", 'id="stateCodeIn"' in src, True)

    assets = open(HTML_ANDROID, encoding='utf-8').read() if os.path.exists(HTML_ANDROID) else ''
    check("APK assets 已同步状态码", '状态同步码' in assets, True)

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
