# -*- coding: utf-8 -*-
"""数据质量筛选(?dq=noimg/noend/stale)测试。

统计面板里的「缺少封面图 / 缺结束时间 / 更早开始·结束未知」原先只是数字,
看到也定位不到具体条目。现在点一下即切到「全部资讯」并只显示这些条目,
顶部出现可一键退出的筛选条,同时写进分享链接(?dq=)。

口径必须与统计面板的计数完全一致,否则用户点进去看到的数量对不上。

运行:python tests/test_quality_filter.py(node 缺失则 SKIP)
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
const fn = new Function(grab('evStart') + '\n' + grab('isPointItem') + '\n' + grab('isStaleUnknown')
  + '\n' + grab('dqMatch') + '\nreturn {dqMatch};');
const f = fn();
const NOW = new Date(2026, 9, 31, 12, 0, 0);   // 2026-10-31,与测试注释同口径
const ev = (o) => Object.assign({kind: 'event'}, o);
console.log(JSON.stringify({
  imgEmpty: f.dqMatch(ev({image: ''}), 'noimg', NOW),
  imgBlank: f.dqMatch(ev({image: '   '}), 'noimg', NOW),
  imgOk: f.dqMatch(ev({image: 'https://x/y.png'}), 'noimg', NOW),
  endEmpty: f.dqMatch(ev({start: '2026-11-01T10:00'}), 'noend', NOW),
  endOk: f.dqMatch(ev({start: '2026-11-01T10:00', end: '2026-11-10T03:59'}), 'noend', NOW),
  staleYes: f.dqMatch(ev({start: '2026-09-01T10:00'}), 'stale', NOW),
  staleNo: f.dqMatch(ev({start: '2026-10-20T10:00'}), 'stale', NOW),
  staleHasEnd: f.dqMatch(ev({start: '2026-09-01T10:00', end: '2026-10-05T03:59'}), 'stale', NOW),
  pointNoend: f.dqMatch(ev({title: '4.7版本「此刻将群星付之一笑」上线', start: '2026-11-05T10:00'}), 'noend', NOW),
  pointStale: f.dqMatch(ev({title: '3.7版本前瞻通讯（直播）', start: '2026-09-01T10:00'}), 'stale', NOW),
  none: f.dqMatch(ev({image: ''}), '', NOW),
  noEndCount: [
    ev({title: '签到活动', start: '2026-11-01T10:00'}),
    ev({title: '4.7版本上线', start: '2026-11-05T10:00'}),
    ev({title: '有结束', start: '2026-11-01T10:00', end: '2026-11-10T03:59'}),
  ].filter(e => f.dqMatch(e, 'noend', NOW)).length,
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

    check("缺图:空字符串命中", d['imgEmpty'], True)
    check("缺图:纯空白命中", d['imgBlank'], True)
    check("缺图:有图片地址不命中", d['imgOk'], False)
    check("缺结束:无 end 命中", d['endEmpty'], True)
    check("缺结束:有 end 不命中", d['endOk'], False)
    check("更早开始未知:40 天前无结束命中", d['staleYes'], True)
    check("更早开始未知:11 天前不命中", d['staleNo'], False)
    check("更早开始未知:有结束不命中", d['staleHasEnd'], False)
    check("单点里程碑(版本上线)不算缺结束", d['pointNoend'], False)
    check("单点里程碑(前瞻通讯)不算更早未知", d['pointStale'], False)
    check("无质量筛选时全部通过", d['none'], True)
    check("缺结束计数与筛选同口径(里程碑不计)", d['noEndCount'], 1)
    check("统计面板缺结束条数也排除里程碑",
          "evs.filter(e=>!e.end&&!isPointItem(e)).length" in open(HTML, encoding='utf-8').read(), True)

    src = open(HTML, encoding='utf-8').read()
    check("统计行可点进缺图", 'statQuality(\'noimg\',this)' in src, True)
    check("统计行可点进缺结束", 'statQuality(\'noend\',this)' in src, True)
    check("统计行可点进结束未知", 'statQuality(\'stale\',this)' in src, True)
    check("列表顶部有质量筛选条", 'class="dq-bar"' in src, True)
    check("质量筛选条可一键退出", "setQuality('')" in src, True)
    check("筛选结果写进地址栏", 'buildFilterQuery(activeGames,activeCats,tab,ids,Object.keys(CAT_COLOR),q,dq' in src, True)
    check("质量筛选只针对真活动", 'isEv(e)&&dqMatch(e,dq,now)' in src, True)

    assets = open(HTML_ANDROID, encoding='utf-8').read() if os.path.exists(HTML_ANDROID) else ''
    check("APK assets 已同步质量筛选", 'statQuality(\'noend\',this)' in assets, True)

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
