# -*- coding: utf-8 -*-
"""状态同步码(网页 ↔ 离线 APK 互导收藏 / 打钩 / 备忘 / 显示偏好)测试。

收藏/打钩平时靠服务端 userstate 跨设备合并,但离线 APK 走 file:// 连不到服务端,
状态只存在本机。状态码把「正向收藏 + 正向打钩 + 备忘清单 + 非默认显示偏好」编码成:
  YCALSYNC1:<base64(JSON {fav, done, n, s})>
  - 只带正向状态,取消(负值)不进码,导入不会把别人的记录弄丢;
  - 导入走 mergeTS(按时间戳绝对值合并),本机更新的操作优先;
  - 备忘按标题去重合并,同名保留本机条目;空标题剔除、标题截断 200、最多 100 条;
  - 显示偏好只在非默认值时写入;导入前白名单校验(四个布尔 + calGames 字符串数组);
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
const api = new Function(['posOnly','notesSync','settingsSync','stateCodeOf','decodeNotes',
  'decodeSettings','decodeStateCode','mergeTS'].map(grab).join('\n')
  + '\nreturn {posOnly, notesSync, settingsSync, stateCodeOf, decodeNotes, decodeSettings, decodeStateCode, mergeTS};')();
const unicode = {fav:{'hsr|活动·限定': 1700000000000}, done:{'zzz|签到活动': 1700000001000}};
const mixed = api.stateCodeOf({'a|活动A': 111, 'b|活动B': -222}, {'c|已做完': 333, 'd|取消': -444});
const code = api.stateCodeOf(unicode.fav, unicode.done);
const legacy = 'YCALFAV1:' + btoa(unescape(encodeURIComponent(JSON.stringify({'x|旧收藏': 555}))));
const noteItems = {items:[
  {id:'n1', title:'清体力', done:true, cycle:'weekly', done_week:'2026-W44'},
  {id:'n2', title:'领邮箱', done:false},
  {id:'n3', title:'', done:false},
]};
const noteCode = api.stateCodeOf({}, {}, noteItems);
const longNote = api.stateCodeOf({}, {}, {items:[{title:'x'.repeat(400), done:false}]});
const mem = {items:[{id:'a', title:'清体力', done:false}]};
const saved = [];
const mergeNotes = new Function('NOTES','notesReady','saveNotes',
  grab('mergeNotes') + '\nreturn mergeNotes;')(mem, true, () => saved.push(1));
const addedNotes = mergeNotes([{t:'清体力'}, {t:'领邮件', d:true}]);
const stDefault = {hideAuto:false, hideDone:false, icsFav:false, icsAlarm:false};
const stCustom = {hideAuto:true, hideDone:true, icsFav:true, icsAlarm:true, calGames:['hsr','zzz']};
const stCode = api.stateCodeOf({}, {}, {items:[]}, stCustom);
const stRound = api.decodeStateCode(stCode);
const stEmptyCode = api.stateCodeOf({}, {}, {items:[]}, stDefault);
const badSettings = 'YCALSYNC1:' + btoa(unescape(encodeURIComponent(
  JSON.stringify({fav:{}, done:{}, n:[], s:{hideAuto:'yes', calGames:[1, 2]}}))));
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
  noteCode: noteCode, noteRound: api.decodeStateCode(noteCode),
  longTitleLen: (api.decodeStateCode(longNote).notes[0] || {}).t.length,
  addedNotes: addedNotes, merged: mem.items, saveCalls: saved.length,
  stCode: stCode, stRound: stRound, stEmptyCode: stEmptyCode,
  badSettings: api.decodeStateCode(badSettings),
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
          {'fav': {'hsr|活动·限定': 1700000000000}, 'done': {'zzz|签到活动': 1700000001000},
           'notes': [], 'settings': None})
    check("取消(负值)不写进码", d['mixed'],
          {'fav': {'a|活动A': 111}, 'done': {'c|已做完': 333}, 'notes': [], 'settings': None})
    check("两手空空返回空串", d['empty'], '')
    check("全是负值时生成空码(判无效)", d['onlyNeg'], '')
    check("旧版收藏码仍可导入", d['legacy'],
          {'fav': {'x|旧收藏': 555}, 'done': {}, 'notes': [], 'settings': None})
    check("错误前缀判无效", d['badPrefix'], None)
    check("非法 base64 判无效", d['badBase64'], None)
    check("截断的状态码判无效", d['truncated'], None)
    check("普通文本判无效", d['otherText'], None)
    check("较新的操作时间胜出", d['newerWins'], {'k|K': 2000})
    check("较旧的导入不覆盖本机", d['olderIgnored'], {'k|K': 2000})
    check("缺失的记录会被补上", d['added'], {'a|A': 1000, 'b|B': 500})
    check("备忘也能单独生成状态码", d['noteCode'].startswith('YCALSYNC1:'), True)
    check("备忘往返:打钩/每周标记/空标题剔除", d['noteRound']['notes'],
          [{'t': '清体力', 'd': True, 'c': 'weekly', 'w': '2026-W44'},
           {'t': '领邮箱', 'd': False, 'c': '', 'w': ''}])
    check("备忘标题超长截断到 200", d['longTitleLen'], 200)
    check("导入备忘按标题去重,只加新的", d['addedNotes'], 1)
    check("同名备忘保留本机条目", (d['merged'][1]['title'], d['merged'][1]['done']), ('清体力', False))
    check("新备忘排在最前且保留打钩",
          (d['merged'][0]['title'], d['merged'][0]['done']), ('领邮件', True))
    check("非默认显示偏好也能单独生成状态码", d['stCode'].startswith('YCALSYNC1:'), True)
    check("显示偏好往返一致", d['stRound']['settings'],
          {'hideAuto': True, 'hideDone': True, 'icsFav': True, 'icsAlarm': True,
           'calGames': ['hsr', 'zzz']})
    check("全默认偏好不生成空码", d['stEmptyCode'], '')
    check("非法偏好字段被过滤(只留 calGames 字符串)",
          d['badSettings']['settings'], {'calGames': ['1', '2']})

    src = open(HTML, encoding='utf-8').read()
    check("设置里有状态同步码入口", '状态同步码' in src, True)
    check("同步码说明覆盖备忘", '备忘清单' in src, True)
    check("同步码说明覆盖显示偏好", '显示偏好' in src, True)
    check("有复制状态码按钮", 'onclick="copyStateCode()"' in src, True)
    check("有导入状态码按钮", 'onclick="importStateCode()"' in src, True)
    check("导入框 id 固定", 'id="stateCodeIn"' in src, True)

    assets = open(HTML_ANDROID, encoding='utf-8').read() if os.path.exists(HTML_ANDROID) else ''
    check("APK assets 已同步状态码", '状态同步码' in assets, True)

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
