# -*- coding: utf-8 -*-
"""首页「今日摘要」计数口径测试。

从 index.html 提取 renderTodayBar(),注入固定时间与依赖桩,验证
「今天开始 / 今天结束 / 进行中」三个数字的口径(进行中包含跨天与当天起止的活动)。

运行:python3 tests/test_todaybar.py(node 缺失则 SKIP)
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
  return a.length ? new Date(...a) : new Date('2026-10-31T20:30:00+08:00');
}
const box = { innerHTML: '' };
const fn = new Function('$', 'filteredEvents', 'evStart', 'evEnd', 'jumpToday', 'Date',
  grab('renderTodayBar') + '\nreturn renderTodayBar;');
fn(() => box, () => EVENTS, e => new Date(e.start), e => (e.end ? new Date(e.end) : null),
   () => {}, FakeDate)();
const nums = [...box.innerHTML.matchAll(/<b>(\d+)<\/b>/g)].map(m => +m[1]);
console.log(JSON.stringify({ nums, html: box.innerHTML.length }));
"""

EV = [
    # 今天开始且仍在进行
    {'start': '2026-10-31T10:00', 'end': '2026-11-10T03:59'},
    # 今天结束且仍在进行
    {'start': '2026-10-20T10:00', 'end': '2026-10-31T23:59'},
    # 跨天进行中(今天既没开始也没结束)
    {'start': '2026-10-25T10:00', 'end': '2026-11-05T03:59'},
    # 明天才开始(三项都不计)
    {'start': '2026-11-01T10:00', 'end': '2026-11-10T03:59'},
    # 今天开始但未写结束时间:算今天开始与进行中,不算今天结束
    {'start': '2026-10-31T09:00'},
]

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
        print('SKIP: 未找到 node，跳过今日摘要测试')
        return 0
    html_in = open(HTML, encoding='utf-8').read()
    loader = LOADER.replace('EVENTS', json.dumps(EV, ensure_ascii=False))
    r = subprocess.run([node, '-e', loader], input=html_in,
                       capture_output=True, text=True, encoding='utf-8', timeout=60)
    if r.returncode != 0:
        print('FAIL: node 执行失败\n' + r.stderr[:600])
        return 1
    d = json.loads(r.stdout.strip().splitlines()[-1])
    check("渲染出三个计数", len(d['nums']), 3)
    check("今天开始 = 2(含未写结束时间的一条)", d['nums'][0], 2)
    check("今天结束 = 1", d['nums'][1], 1)
    check("进行中 = 4(含今天起止与未写结束时间)", d['nums'][2], 4)
    check("输出非空", d['html'] > 0, True)

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
