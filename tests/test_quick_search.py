# -*- coding: utf-8 -*-
"""搜索快捷词测试:今天 / 明天 / 本周 / 周末 / 未开始 / 今天开始 / 今天结束 / 进行中。

从 index.html 提取 isQuickWord / quickMatch / filtered,注入固定时间与依赖桩验证口径。
运行:python3 tests/test_quick_search.py(node 缺失则 SKIP)
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
  return a.length ? new Date(...a) : new Date('2026-10-31T20:30:00+08:00');   // 周六
}
const EVENTS = {events: __EVENTS__, games: [
  {id:'hsr', name:'崩坏：星穹铁道'}, {id:'zzz', name:'绝区零'}, {id:'wuwa', name:'鸣潮'}]};
function makeFiltered(w) {
  return new Function('DATA','q','activeGames','activeCats','calVisible','settings','evStart','evEnd','Date',
    "const QUICK_WORDS=['今天','明天','本周','周末','未开始','下周','已结束','即将结束','本周开始','本月开始','今天开始','今天结束','进行中'];\nfunction isDone(){return false}\nlet dq='';\nfunction dqMatch(){return true}\n"
    + "function gameShort(id){return ({hsr:'崩铁',zzz:'绝区零',wuwa:'鸣潮'})[id]||''}\n"
    + grab('isQuickWord') + '\n' + grab('quickMatch') + '\n' + grab('gamePrefix') + '\n' + grab('filtered')
    + '\nreturn {isQuickWord, quickMatch, gamePrefix, filtered};')
    (EVENTS, w, new Set(['hsr','zzz','wuwa']),
     new Set(['活动','签到','角色与专武','公告','资讯']), () => true, {hideAuto:false},
     e => new Date(e.start), e => (e.end ? new Date(e.end) : null), FakeDate);
}
const run = (w) => makeFiltered(w).filtered().map(e => e.id);
console.log(JSON.stringify({
  today: run('今天'), tomorrow: run('明天'), week: run('本周'),
  weekend: run('周末'), notStarted: run('未开始'), plain: run('活动A'),
  prefixHsr: run('hsr:'), prefixHsrAbbr: run('hs:'),
  prefixZzzWord: run('zzz: 活动'), prefixHsrToday: run('hsr: 今天'),
  prefixUnknown: run('xxx:'),
  nextWeek: run('下周'), ended: run('已结束'), ending: run('即将结束'),
  weekStart: run('本周开始'), monthStart: run('本月开始'),
  todayStart: run('今天开始'), todayEnd: run('今天结束'), running: run('进行中'),
  prefixHsrEnding: run('hsr: 即将结束'),
  shortHsr: run('崩铁'), shortZzz: run('绝区零'),
}));
"""

EV = [
    # 今天正在进行
    {'id': 'a', 'game_id': 'hsr', 'title': '活动A', 'category': '活动',
     'start': '2026-10-25T10:00', 'end': '2026-11-05T03:59'},
    # 今天结束
    {'id': 'b', 'game_id': 'zzz', 'title': '活动B', 'category': '活动',
     'start': '2026-10-20T10:00', 'end': '2026-10-31T23:59'},
    # 明天开始
    {'id': 'c', 'game_id': 'wuwa', 'title': '活动C', 'category': '活动',
     'start': '2026-11-01T10:00', 'end': '2026-11-10T03:59'},
    # 后天开始(本周内)
    {'id': 'd', 'game_id': 'hsr', 'title': '活动D', 'category': '活动',
     'start': '2026-11-02T10:00', 'end': '2026-11-12T03:59'},
    # 三周后(不在本周)
    {'id': 'e', 'game_id': 'zzz', 'title': '活动E', 'category': '活动',
     'start': '2026-11-20T10:00', 'end': '2026-11-30T03:59'},
    # 已结束(10/1–10/5)
    {'id': 'f', 'game_id': 'wuwa', 'title': '活动F', 'category': '活动',
     'start': '2026-10-01T10:00', 'end': '2026-10-05T23:59'},
    # 今天开始、未写结束时间(应算进行中,不算已结束)
    {'id': 'g', 'game_id': 'hsr', 'title': '活动G', 'category': '活动',
     'start': '2026-10-31T09:00'},
    # 很久以前开始、未写结束时间:日期筛选只认开始日,不能永远出现在今天/本周/下周
    {'id': 'h', 'game_id': 'zzz', 'title': '旧签到H', 'category': '签到',
     'start': '2026-10-05T10:00'},
    # 两天后结束(3 天内) → 命中「即将结束」
    {'id': 'i', 'game_id': 'hsr', 'title': '活动I', 'category': '活动',
     'start': '2026-10-29T10:00', 'end': '2026-11-02T23:59'},
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
        print('SKIP: 未找到 node，跳过快捷词测试')
        return 0
    loader = LOADER.replace('__EVENTS__', json.dumps(EV, ensure_ascii=False))
    r = subprocess.run([node, '-e', loader], input=open(HTML, encoding='utf-8').read(),
                       capture_output=True, text=True, encoding='utf-8', timeout=60)
    if r.returncode != 0:
        print('FAIL: node 执行失败\n' + r.stderr[:800])
        return 1
    d = json.loads(r.stdout.strip().splitlines()[-1])
    check("今天:含进行中+今天结束+无结束时间", d['today'], ['a', 'b', 'g', 'i'])
    check("明天:含明天开始", d['tomorrow'], ['c'])
    check("本周(周一起算):含进行中与本周开始", d['week'], ['a', 'b', 'c', 'g', 'i'])
    check("周末:11/1(周日)开始的活动", d['weekend'], ['a', 'b', 'c', 'g', 'i'])
    check("未开始:开始时间晚于此刻", d['notStarted'], ['c', 'd', 'e'])
    check("普通关键词仍按文本匹配", d['plain'], ['a'])
    check("游戏前缀 hsr: 只看该游戏", d['prefixHsr'], ['a', 'd', 'g', 'i'])
    check("游戏前缀允许缩写 hs:", d['prefixHsrAbbr'], ['a', 'd', 'g', 'i'])
    check("游戏前缀+关键词 zzz: 活动", d['prefixZzzWord'], ['b', 'e'])
    check("游戏前缀+快捷词 hsr: 今天", d['prefixHsrToday'], ['a', 'g', 'i'])
    check("不认识的游戏前缀按普通文本处理", d['prefixUnknown'], [])
    check("下周:跨到下周或下周内开始", d['nextWeek'], ['a', 'c', 'd', 'i'])
    check("本周开始(只算本周内开始的)", d['weekStart'], ['c', 'g', 'i'])
    check("本月开始(只算本月内开始的)", d['monthStart'], ['a', 'b', 'f', 'g', 'h', 'i'])
    check("无结束时间的老条目不进日期筛选", 'h' in (d['today'] + d['week'] + d['weekend'] + d['nextWeek']), False)
    check("已结束:必须真有结束时间", d['ended'], ['f'])
    check("即将结束:3 天内截止且未结束", d['ending'], ['b', 'i'])
    check("游戏前缀+即将结束", d['prefixHsrEnding'], ['i'])
    check("今天开始:只算今天起点的", d['todayStart'], ['g'])
    check("今天结束:只算真有结束时间且今天截止的", d['todayEnd'], ['b'])
    check("进行中:已开始且未结束(无结束时间也算)", d['running'], ['a', 'b', 'g', 'h', 'i'])
    check("搜索游戏短名「崩铁」命中星铁全部", d['shortHsr'], ['a', 'd', 'g', 'i'])
    check("搜索游戏全名「绝区零」命中绝区零全部", d['shortZzz'], ['b', 'e', 'h'])

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
