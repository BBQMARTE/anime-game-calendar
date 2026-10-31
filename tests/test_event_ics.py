# -*- coding: utf-8 -*-
"""「添加到系统日历」单事件 .ics 生成测试。

从 index.html 提取 icsEsc / icsFold / buildEventIcs 等纯函数,用 node 断言:
- 定时活动输出正确的 UTC DTSTART/DTEND,并带提前 30 分钟 VALARM
- 纯日期活动输出全天事件(VALUE=DATE),DTEND 为次日且不带闹钟
- 逗号/分号/换行按 RFC5545 转义
- 中文长标题按 75 字节折行,续行以空格开头
- 没有开始时间返回空串
- 当天批量导出:多个 VEVENT、X-WR-CALNAME、UID 不重复,空列表返回空串
运行:python3 tests/test_event_ics.py(node 缺失则 SKIP)
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
const code = ['evStart','evEnd','icsEsc','icsUtc','icsDate','_u8len','icsFold',
  'icsCalendarHead','icsVevent','buildEventIcs','buildDayIcs']
  .map(grab).join('\n');
const api = new Function('Date', code + '\nreturn {buildEventIcs,buildDayIcs};')(Date);
const toUtc = s => new Date(s).toISOString().replace(/[-:]/g,'').replace(/\.\d{3}/,'');
const timed = {
  id:'ev1', game_id:'hsr', game:'崩坏：星穹铁道', category:'活动',
  title:'活动,测试;换行\n标题\\斜杠', start:'2026-11-01T10:00', end:'2026-11-10T03:59',
  link:'https://example.com/x?a=1,2',
};
const allDay = {id:'ev2', game_id:'zzz', game:'绝区零', category:'活动',
  title:'纯日期活动', start:'2026-11-01'};
const nodate = {id:'ev3', game_id:'hsr', title:'时间待定', _nodate:true, date:'2026-10-20T10:00'};
const longTitle = {id:'ev4', game_id:'hsr', title:'很长的活动标题'.repeat(20),
  start:'2026-11-01T10:00', end:'2026-11-02T10:00'};
const dayA = {id:'d1', game_id:'hsr', title:'当天开始', start:'2026-11-03T10:00'};
const dayB = {id:'d2', game_id:'zzz', title:'当天结束', start:'2026-11-01T10:00', end:'2026-11-03T03:59'};
const dayIcs = api.buildDayIcs([dayA, dayB], '11月3日 周一');
const dayUids = (dayIcs.match(/UID:(\S+)/g) || []);
const timedIcs = api.buildEventIcs(timed);
const lines = timedIcs.split('\r\n').filter(Boolean);
const maxBytes = Math.max(...lines.map(l => Buffer.byteLength(l, 'utf8')));
const contOk = lines.filter(l => l.startsWith(' ')).every(l => l.length > 1);
console.log(JSON.stringify({
  header: timedIcs.startsWith('BEGIN:VCALENDAR'),
  dtstart: (timedIcs.match(/DTSTART:(\S+)/) || [])[1] || '',
  dtstartExpect: toUtc('2026-11-01T10:00'),
  dtend: (timedIcs.match(/DTEND:(\S+)/) || [])[1] || '',
  dtendExpect: toUtc('2026-11-10T03:59'),
  valarms: (timedIcs.match(/BEGIN:VALARM/g) || []).length,
  trigger: timedIcs.includes('TRIGGER:-PT30M'),
  escaped: timedIcs.includes('SUMMARY:活动\\,测试\\;换行\\n标题\\\\斜杠'),
  descEsc: timedIcs.includes('DESCRIPTION:崩坏：星穹铁道\\n活动\\nhttps://example.com/x?a=1\\,2'),
  allDayStart: (api.buildEventIcs(allDay).match(/DTSTART;VALUE=DATE:(\S+)/) || [])[1] || '',
  allDayEnd: (api.buildEventIcs(allDay).match(/DTEND;VALUE=DATE:(\S+)/) || [])[1] || '',
  allDayAlarm: api.buildEventIcs(allDay).includes('VALARM'),
  nodate: api.buildEventIcs(nodate),
  longMaxBytes: maxBytes,
  longContOk: contOk,
  longLines: api.buildEventIcs(longTitle).split('\r\n').length,
  dayVevents: (dayIcs.match(/BEGIN:VEVENT/g) || []).length,
  dayCalname: dayIcs.includes('X-WR-CALNAME:11月3日 周一'),
  dayUidCount: dayUids.length,
  dayUidUnique: new Set(dayUids).size,
  dayEmpty: api.buildDayIcs([]),
  hasEntry: src.includes('onclick="exportDayIcs()"'),
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
        print('SKIP: 未找到 node，跳过单事件 ICS 测试')
        return 0
    r = subprocess.run([node, '-e', LOADER], input=open(HTML, encoding='utf-8').read(),
                       capture_output=True, text=True, encoding='utf-8', timeout=60)
    if r.returncode != 0:
        print('FAIL: node 执行失败\n' + r.stderr[:800])
        return 1
    d = json.loads(r.stdout.strip().splitlines()[-1])
    check("输出完整 VCALENDAR", d['header'], True)
    check("DTSTART 为开始时刻的 UTC", d['dtstart'], d['dtstartExpect'])
    check("DTEND 为结束时刻的 UTC", d['dtend'], d['dtendExpect'])
    check("定时活动带 1 个闹钟", d['valarms'], 1)
    check("闹钟提前 30 分钟", d['trigger'], True)
    check("SUMMARY 转义逗号/分号/换行/反斜杠", d['escaped'], True)
    check("DESCRIPTION 转义并含原文链接", d['descEsc'], True)
    check("纯日期活动 DTSTART 为全天日期", d['allDayStart'], '20261101')
    check("全天事件 DTEND 为次日(排他)", d['allDayEnd'], '20261102')
    check("全天事件不带闹钟", d['allDayAlarm'], False)
    check("无开始时间返回空串", d['nodate'], '')
    check("中文长标题每行不超过 75 字节", d['longMaxBytes'] <= 75, True)
    check("续行均以空格开头", d['longContOk'], True)
    check("当天导出含 2 个 VEVENT", d['dayVevents'], 2)
    check("当天导出带日历名", d['dayCalname'], True)
    check("同一天的 UID 不重复", (d['dayUidCount'], d['dayUidUnique']), (2, 2))
    check("空列表返回空串", d['dayEmpty'], '')
    check("日历当天有「导出 .ics」入口", d['hasEntry'], True)

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
