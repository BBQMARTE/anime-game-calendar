# -*- coding: utf-8 -*-
"""用户报错/缺图反馈(/api/report)测试。
离线跑:临时文件替换真实 data/reports.json,不产生副作用。
运行:python3 tests/test_report.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, 'static', 'index.html')
bad = 0


def check(label, got, expect):
    global bad
    ok = got == expect
    if not ok:
        bad += 1
    print("[%s] %s: got=%r expect=%r" % ('OK ' if ok else 'FAIL', label, got, expect))


def main():
    tmp = tempfile.mkdtemp(prefix='ycal_rp_')
    app.REPORT_FILE = os.path.join(tmp, 'reports.json')
    app._state['events'] = []          # 自动处理逻辑依赖当前事件,先用空集合保证可重复
    c = app.app.test_client()
    H = {'X-Requested-With': 'ycal'}

    check("初始为空", c.get('/api/report').get_json()['items'], [])

    # CSRF
    r = c.post('/api/report', json={'title': '活动A', 'game_id': 'zzz', 'kind': 'missing-image'})
    check("无 CSRF 头被拒", r.status_code, 403)

    # 缺标题
    r = c.post('/api/report', json={'game_id': 'zzz'}, headers=H)
    check("缺标题返回 400", r.status_code, 400)

    # 正常写入
    r = c.post('/api/report', json={'title': '活动A', 'game_id': 'zzz',
                                    'kind': 'missing-image', 'note': '封面没有'}, headers=H)
    j = r.get_json()
    check("写入 ok", j.get('ok'), True)
    items = c.get('/api/report').get_json()['items']
    check("记录条数", len(items), 1)
    check("字段落盘", (items[0]['game_id'], items[0]['title'], items[0]['kind'], items[0]['done']),
          ('zzz', '活动A', 'missing-image', False))

    # 10 分钟内同类型重复 → 去重,不重复计数
    c.post('/api/report', json={'title': '活动A', 'game_id': 'zzz', 'kind': 'missing-image'}, headers=H)
    check("重复反馈被去重", len(c.get('/api/report').get_json()['items']), 1)

    # 不同类型允许并存
    c.post('/api/report', json={'title': '活动A', 'game_id': 'zzz', 'kind': 'wrong-time'}, headers=H)
    check("不同类型单独记", len(c.get('/api/report').get_json()['items']), 2)

    # 缺结束时间:独立类型(前端只对无 end 的条目显示该按钮)
    c.post('/api/report', json={'title': '活动A', 'game_id': 'zzz', 'kind': 'no-end'}, headers=H)
    items = c.get('/api/report').get_json()['items']
    check("缺结束时间不再回落 other", items[-1]['kind'], 'no-end')

    # 非法 kind 回落 other
    c.post('/api/report', json={'title': '活动B', 'game_id': 'hsr', 'kind': 'boom'}, headers=H)
    items = c.get('/api/report').get_json()['items']
    check("非法 kind 回落 other", items[-1]['kind'], 'other')

    # 标题超长截断
    c.post('/api/report', json={'title': 'x' * 300, 'game_id': 'wuwa'}, headers=H)
    items = c.get('/api/report').get_json()['items']
    check("标题截断到 120", len(items[-1]['title']), 120)

    # ---- 撤回:待核查可删,已处理不可删 ----
    items = c.get('/api/report').get_json()['items']
    target = items[0]
    r = c.delete('/api/report', json={'at': target['at'], 'title': target['title'],
                                      'game_id': target['game_id'], 'kind': target['kind']})
    check("无 CSRF 头撤回被拒", r.status_code, 403)

    r = c.delete('/api/report', json={'title': target['title']}, headers=H)
    check("缺 at 撤回返回 400", r.status_code, 400)

    before = len(items)
    r = c.delete('/api/report', json={'at': target['at'], 'title': target['title'],
                                      'game_id': target['game_id'],
                                      'kind': target['kind']}, headers=H)
    j = r.get_json()
    check("撤回待核查反馈", (j.get('ok'), j.get('removed')), (True, 1))
    check("撤回后条数 -1", len(c.get('/api/report').get_json()['items']), before - 1)

    # 已经处理过的不能撤回
    items = c.get('/api/report').get_json()['items']
    done_item = items[-1]
    done_item['done'] = True
    with open(app.REPORT_FILE, 'w', encoding='utf-8') as f:
        json.dump({'items': items}, f, ensure_ascii=False)
    r = c.delete('/api/report', json={'at': done_item['at'], 'title': done_item['title'],
                                      'game_id': done_item.get('game_id'),
                                      'kind': done_item['kind']}, headers=H)
    check("已处理反馈不能撤回", r.get_json()['removed'], 0)
    done_item['done'] = False
    with open(app.REPORT_FILE, 'w', encoding='utf-8') as f:
        json.dump({'items': items}, f, ensure_ascii=False)

    # 清除已处理:只删 done,待核查保留
    items = c.get('/api/report').get_json()['items']
    items[0]['done'] = True
    items[-1]['done'] = True
    with open(app.REPORT_FILE, 'w', encoding='utf-8') as f:
        json.dump({'items': items}, f, ensure_ascii=False)
    before = len(items)
    r = c.delete('/api/report', json={'done': True}, headers=H)
    j = r.get_json()
    check("清除已处理反馈", (j.get('ok'), j.get('removed')), (True, 2))
    left = c.get('/api/report').get_json()['items']
    check("清除后只剩待核查", (len(left), any(x.get('done') for x in left)), (before - 2, False))

    # 数据补全后 GET 自动把待核查标成已处理(no-end / missing-image)
    c.post('/api/report', json={'title': '自动A', 'game_id': 'hsr', 'kind': 'no-end',
                                'start': '2026-11-01T10:00'}, headers=H)
    c.post('/api/report', json={'title': '自动B', 'game_id': 'hsr', 'kind': 'missing-image'}, headers=H)
    c.post('/api/report', json={'title': '自动C', 'game_id': 'hsr', 'kind': 'no-end',
                                'start': '2026-11-01T10:00'}, headers=H)
    app._state['events'] = [
        {'game_id': 'hsr', 'title': '自动A', 'start': '2026-11-01T10:00', 'end': '2026-11-10T03:59'},
        {'game_id': 'hsr', 'title': '自动B', 'start': '2026-11-02T10:00', 'image': 'https://x/b.jpg'},
        {'game_id': 'hsr', 'title': '自动C', 'start': '2026-11-05T10:00', 'end': '2026-11-10T03:59'},
    ]
    items = c.get('/api/report').get_json()['items']
    auto_a = next(i for i in items if i['title'] == '自动A')
    auto_b = next(i for i in items if i['title'] == '自动B')
    auto_c = next(i for i in items if i['title'] == '自动C')
    check("有结束时间 → 自动标记已处理", auto_a['done'], True)
    check("自动备注写明原因", '结束时间' in auto_a['note'], True)
    check("有封面 → 自动标记已处理", auto_b['done'], True)
    check("封面原因写进备注", '封面' in auto_b['note'], True)
    check("同名但开始日期不符不误关", auto_c['done'], False)

    # 时间不对:数据里的开始/结束已和反馈时不同 → 自动关单;完全一致则保持待核查
    c.post('/api/report', json={'title': '自动D', 'game_id': 'hsr', 'kind': 'wrong-time',
                                'start': '2026-11-01T10:00', 'end': '2026-11-10T03:59'}, headers=H)
    c.post('/api/report', json={'title': '自动E', 'game_id': 'hsr', 'kind': 'wrong-time',
                                'start': '2026-11-01T10:00', 'end': '2026-11-10T03:59'}, headers=H)
    c.post('/api/report', json={'title': '自动F', 'game_id': 'hsr', 'kind': 'wrong-time',
                                'start': '2026-11-01T10:00', 'end': '2026-11-10T03:59'}, headers=H)
    app._state['events'] = [
        {'game_id': 'hsr', 'title': '自动D', 'start': '2026-11-02T10:00', 'end': '2026-11-10T03:59'},
        {'game_id': 'hsr', 'title': '自动E', 'start': '2026-11-01T10:00', 'end': '2026-11-10T03:59'},
        # 同名两期:原快照仍在,不能因为另一期改了时间就误关
        {'game_id': 'hsr', 'title': '自动F', 'start': '2026-11-01T10:00', 'end': '2026-11-10T03:59'},
        {'game_id': 'hsr', 'title': '自动F', 'start': '2026-11-05T10:00', 'end': '2026-11-12T03:59'},
    ]
    items = c.get('/api/report').get_json()['items']
    auto_d = next(i for i in items if i['title'] == '自动D')
    auto_e = next(i for i in items if i['title'] == '自动E')
    auto_f = next(i for i in items if i['title'] == '自动F')
    check("时间已更正 → 自动标记已处理", auto_d['done'], True)
    check("更正原因写进备注", '时间已更正' in auto_d['note'], True)
    check("时间未变 → 保持待核查", auto_e['done'], False)
    check("同名多期仍有一期未变 → 不误关", auto_f['done'], False)
    app._state['events'] = []          # 重置,避免影响后续用例

    # 超长标题:反馈侧被截断到 120 字,自动关单仍能按前缀匹配;短标题不做前缀误匹配
    long_title = '超长标题' * 30
    c.post('/api/report', json={'title': long_title, 'game_id': 'wuwa', 'kind': 'no-end',
                                'start': '2026-11-02T10:00'}, headers=H)
    app._state['events'] = [{'game_id': 'wuwa', 'title': long_title + '尾巴',
                             'start': '2026-11-02T10:00', 'end': '2026-11-12T03:59'}]
    items = c.get('/api/report').get_json()['items']
    t_long = next(i for i in items if i['title'] == long_title)
    check("超长标题按截断前缀自动关单", t_long['done'], True)

    c.post('/api/report', json={'title': '短标题', 'game_id': 'wuwa', 'kind': 'no-end',
                                'start': '2026-11-02T10:00'}, headers=H)
    app._state['events'] = [{'game_id': 'wuwa', 'title': '短标题plus',
                             'start': '2026-11-02T10:00', 'end': '2026-11-12T03:59'}]
    items = c.get('/api/report').get_json()['items']
    t_short = next(i for i in items if i['title'] == '短标题')
    check("短标题不做前缀误关", t_short['done'], False)
    app._state['events'] = []

    # 单点里程碑(版本上线)本来就没有结束时间:反馈自动收尾,不再无限挂起
    point_title = '4.7版本「此刻将群星付之一笑」上线'
    c.post('/api/report', json={'title': point_title, 'game_id': 'hsr', 'kind': 'no-end',
                                'start': '2026-11-05T10:00'}, headers=H)
    c.post('/api/report', json={'title': '普通无结束活动', 'game_id': 'hsr', 'kind': 'no-end',
                                'start': '2026-11-06T10:00'}, headers=H)
    app._state['events'] = [
        {'game_id': 'hsr', 'kind': 'event', 'title': point_title, 'start': '2026-11-05T10:00'},
        {'game_id': 'hsr', 'kind': 'event', 'title': '普通无结束活动', 'start': '2026-11-06T10:00'},
    ]
    items = c.get('/api/report').get_json()['items']
    t_point = next(i for i in items if i['title'] == point_title)
    t_plain = next(i for i in items if i['title'] == '普通无结束活动')
    check("单点里程碑缺结束 → 自动标记已处理", t_point['done'], True)
    check("备注说明是单点里程碑", '单点里程碑' in t_point['note'], True)
    check("普通活动缺结束 → 仍待核查", t_plain['done'], False)
    app._state['events'] = []

    # 上限:写入 400 条,只保留最近 300
    for i in range(400):
        c.post('/api/report', json={'title': '批量%d' % i, 'game_id': 'hsr', 'kind': 'other'}, headers=H)
    items = c.get('/api/report').get_json()['items']
    check("上限截断 300", len(items), 300)
    check("保留最新的一条", items[-1]['title'], '批量399')

    # ---- 前端:「缺结束时间」只在无 end 的条目出现,点击上报 kind=no-end ----
    src = open(HTML, encoding='utf-8').read()
    check("详情页有「缺结束时间」入口", "reportEv('${e.id}','no-end')" in src, True)
    check("入口受 e.end 控制", "e.end?'':" in src, True)
    check("反馈按钮带 data-rk 便于标记", 'data-rk="missing-image"' in src, True)
    check("详情打开后标记待核查", 'markReported(overlay,e)' in src, True)

    node = shutil.which('node')
    if not node:
        print('SKIP: 未找到 node,跳过前端反馈测试')
    else:
        loader = r"""
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
const posted = [], alerts = [], flashes = [];
const DATA = {events:[{id:'x',game_id:'endfield',title:'画外遗光',
  start:'2026-11-12T12:00',end:null,link:'https://example.com/e'}]};
const REPORT_LABEL = {'missing-image':'缺图','wrong-time':'时间不对','other':'其他','no-end':'缺结束时间'};
const fetchStub = (u, opt) => { posted.push(JSON.parse(opt.body));
  return Promise.resolve({json: () => Promise.resolve({ok:true})}); };
const pend = {};
const fn = new Function('DATA','REPORT_LABEL','fetch','alert','flash','prompt','REPORTS_PEND',
  grab('repKey') + '\n' + grab('reportEv') + '\nreturn reportEv;');
fn(DATA, REPORT_LABEL, fetchStub, m => alerts.push(m), m => flashes.push(m), () => '', pend)('x','no-end');

// 再次点击已提交的反馈:不再发 POST,提示处理中(轻提示,不弹窗)
const posted2 = [], flashes2 = [];
const pend2 = {'endfield|画外遗光|no-end':{kind:'no-end'}};
const fetchBlocked = () => { posted2.push(1); return Promise.resolve({json:()=>Promise.resolve({ok:true})}); };
new Function('DATA','REPORT_LABEL','fetch','alert','flash','prompt','REPORTS_PEND',
  grab('repKey') + '\n' + grab('reportEv') + '\nreturn reportEv;')(
  DATA, REPORT_LABEL, fetchBlocked, () => {}, m => flashes2.push(m), () => '', pend2)('x','no-end');

// 详情按钮标记:待核查的 kind 加「· 待核查」,已处理/无记录的不动
const chips = [
  {dataset:{rk:'no-end'}, textContent:'缺结束时间', style:{}, title:''},
  {dataset:{rk:'missing-image'}, textContent:'缺图', style:{}, title:''},
  {dataset:{rk:'wrong-time'}, textContent:'时间不对', style:{}, title:''},
];
const over = {querySelectorAll: () => chips};
const markFetch = () => Promise.resolve({json:()=>Promise.resolve({items:[
  {game_id:'endfield', title:'画外遗光', kind:'no-end', done:false},
  {game_id:'endfield', title:'画外遗光', kind:'missing-image', done:true},
]})});
new Function('fetch','apiOrigin','REPORTS_PEND', grab('repKey') + '\n' + grab('markReported') + '\nreturn markReported;')(
  markFetch, () => 'http://127.0.0.1:5000', {})(over, DATA.events[0]);

// 撤回:构造一行待核查反馈,校验 DELETE 方法与请求体
const wposted = [], wflashes = [], removed = [];
const row = {dataset:{at:'2026-10-31T10:00:00', game:'zzz', title:'活动A', kind:'missing-image'},
  closest: sel => (sel === '.detail-overlay' ? {remove:() => removed.push(1)} : row)};
const wbtn = {closest: sel => (sel === '.chg-row' ? row : null)};
const wfetch = (u, opt) => { wposted.push({method:opt.method, csrf:opt.headers['X-Requested-With'],
  body:JSON.parse(opt.body)}); return Promise.resolve({json:()=>Promise.resolve({ok:true,removed:1})}); };
const wfn = new Function('fetch','flash','openReports', grab('withdrawReport') + '\nreturn withdrawReport;');
wfn(wfetch, m => wflashes.push(m), () => {}) (wbtn);

setTimeout(() => console.log(JSON.stringify({payload:posted[0], flash:flashes[0],
  cacheKeys:Object.keys(pend).length, blockedFlash:flashes2[0], blockedPosts:posted2.length,
  chipTexts:chips.map(c => c.textContent),
  wreq:wposted[0], wflash:wflashes[0], wremoved:removed.length})) , 0);
"""
        r = subprocess.run([node, '-e', loader], input=src,
                           capture_output=True, text=True, encoding='utf-8', timeout=60)
        if r.returncode != 0:
            print('FAIL: JS 执行失败\n' + r.stderr[:600])
            globals()['bad'] = 1
        else:
            d = json.loads(r.stdout.strip().splitlines()[-1])
            check("前端上报 kind=no-end", d['payload']['kind'], 'no-end')
            check("前端带上结束时间为空", d['payload']['end'], None)
            check("反馈成功提示含类型名", '缺结束时间' in (d['flash'] or ''), True)
            check("提交成功后记入会话缓存", d['cacheKeys'], 1)
            check("重复点已提交反馈有提示", '已反馈过' in (d['blockedFlash'] or ''), True)
            check("重复点不再发 POST", d['blockedPosts'], 0)
            check("待核查按钮标「· 待核查」", d['chipTexts'][0], '缺结束时间 · 待核查')
            check("已处理/未提交的按钮不动",
                  (d['chipTexts'][1], d['chipTexts'][2]), ('缺图', '时间不对'))
            check("撤回用 DELETE 方法", d['wreq']['method'], 'DELETE')
            check("撤回带 CSRF 头", d['wreq']['csrf'], 'ycal')
            check("撤回请求体带定位字段",
                  (d['wreq']['body']['at'], d['wreq']['body']['game_id'],
                   d['wreq']['body']['title'], d['wreq']['body']['kind']),
                  ('2026-10-31T10:00:00', 'zzz', '活动A', 'missing-image'))
            check("撤回成功关闭面板并提示", (d['wremoved'], '已撤回' in (d['wflash'] or '')),
                  (1, True))

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
