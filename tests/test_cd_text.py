# -*- coding: utf-8 -*-
"""倒计时口径测试:没有真实结束时间时不得伪造「剩 N 天」。

后端/前端 evEnd 会为无结束时间的条目补 2 天默认窗口(日历展示用),
但列表倒计时若直接用它,会把「结束时间待定」的活动显示成 2 天后结束。

运行:python3 tests/test_cd_text.py(node 缺失则 SKIP)
"""
import json, os, shutil, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, 'static', 'index.html')

LOADER = r"""
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
function FakeDate(...a) {
  return a.length ? new Date(...a) : new Date('2026-10-31T12:00:00+08:00');
}
const fn = new Function('evStart','evEnd','Date',
  grab('cdText') + '\nreturn cdText;');
const cd = fn(e => new Date(e.start), e => (e.end ? new Date(e.end) : null), FakeDate);
console.log(JSON.stringify({
  futureNoEnd: cd({start:'2026-11-05T10:00'}),
  startedNoEnd: cd({start:'2026-10-30T10:00'}),
  ongoing: cd({start:'2026-10-25T10:00', end:'2026-11-05T03:59'}),
  ended: cd({start:'2026-10-01T10:00', end:'2026-10-05T23:59'}),
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
        print('SKIP: 未找到 node，跳过倒计时测试')
        return 0
    r = subprocess.run([node, '-e', LOADER], input=open(HTML, encoding='utf-8').read(),
                       capture_output=True, text=True, encoding='utf-8', timeout=60)
    if r.returncode != 0:
        print('FAIL: node 执行失败\n' + r.stderr[:700])
        return 1
    d = json.loads(r.stdout.strip().splitlines()[-1])
    check("未开始(无结束时间)仍显示『还有』",
          bool(d['futureNoEnd']) and d['futureNoEnd']['txt'].startswith('还有'), True)
    check("已开始但无结束时间不显示『剩』", d['startedNoEnd'], None)
    check("有真实结束时间才显示剩余",
          bool(d['ongoing']) and d['ongoing']['txt'].startswith('剩'), True)
    check("有真实结束时间时给出进度百分比",
          isinstance(d['ongoing'] and d['ongoing'].get('prog'), (int, float)), True)
    check("已结束不显示倒计时", d['ended'], None)

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
