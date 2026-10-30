# -*- coding: utf-8 -*-
"""详情页「同游戏其他活动」测试。

看一条活动时,弹窗底部顺带列出同游戏未结束的其它活动(最多 3 条,按开始时间排序),
点击可切换详情;已结束、其它游戏、公告资讯都不应出现。

运行:python3 tests/test_related_events.py(node 缺失则 SKIP)
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
const code = ['evStart', 'evEnd', 'relatedEvents'].map(grab).join('\n');
const ev = (id, gid, kind, s, e) => ({id, game_id: gid, kind, start: s, end: e, title: 'T' + id});
const DATA = {events: [
  ev('cur', 'hsr', 'event', '2026-10-30T10:00', '2026-11-20T03:59'),   // 当前详情
  ev('a',   'hsr', 'event', '2026-10-25T10:00', '2026-11-05T03:59'),   // 进行中 → 第 1 条
  ev('b',   'hsr', 'event', '2026-11-05T10:00', '2026-11-15T03:59'),   // 第 2 条
  ev('c',   'hsr', 'event', '2026-11-10T10:00', '2026-11-20T03:59'),   // 第 3 条
  ev('d',   'hsr', 'event', '2026-11-20T10:00', '2026-11-30T03:59'),   // 被 3 条上限截掉
  ev('old', 'hsr', 'event', '2026-10-01T10:00', '2026-10-05T23:59'),   // 已结束 → 排除
  ev('z',   'zzz', 'event', '2026-10-25T10:00', '2026-11-05T03:59'),   // 其它游戏 → 排除
  ev('inf', 'hsr', 'info',  '2026-11-01T10:00', '2026-11-10T03:59'),   // 资讯 → 排除
]};
const fn = new Function('DATA', code + '\nreturn relatedEvents;')(DATA);
const now = new Date(2026, 9, 31, 12, 0, 0);
const cur = DATA.events[0];
const rel = fn(cur, now);
console.log(JSON.stringify({
  ids: rel.map(x => x.id),
  count: rel.length,
  hasSelf: rel.some(x => x.id === 'cur'),
  unknownGame: fn({id: 'u', game_id: 'nope'}, now).map(x => x.id),
  hasSection: html.includes('同游戏其他活动'),
  hasFn: html.includes('function relatedEvents'),
  hasClickThrough: html.includes("this.closest('.detail-overlay').remove();openEv("),
  hasCss: html.includes('.rel-row{display:flex'),
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
        print('SKIP: 未找到 node，跳过同游戏活动测试')
        return 0
    r = subprocess.run([node, '-e', LOADER], input=open(HTML, encoding='utf-8').read(),
                       capture_output=True, text=True, encoding='utf-8', timeout=60)
    if r.returncode != 0:
        print('FAIL: node 执行失败\n' + r.stderr[:800])
        return 1
    d = json.loads(r.stdout.strip().splitlines()[-1])
    check("同游戏未结束活动按开始时间排序", d['ids'], ['a', 'b', 'c'])
    check("最多 3 条", d['count'], 3)
    check("排除当前活动自身", d['hasSelf'], False)
    check("没有同游戏活动时为空", d['unknownGame'], [])
    check("详情页含「同游戏其他活动」区块", d['hasSection'], True)
    check("relatedEvents 已实现", d['hasFn'], True)
    check("点击可切换到该活动详情", d['hasClickThrough'], True)
    check("样式已写入", d['hasCss'], True)

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
