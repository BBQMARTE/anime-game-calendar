# -*- coding: utf-8 -*-
"""B站链路「接口挂掉」的状态上报（Issue #24）。

背景：接口全挂（风控 -352 / 网络异常）曾被上报为 ok:true / count:0 / error:''，
前端 renderMeta() 据此渲染绿色徽标，故障与「官号今天没发动态」不可区分。

本测试离线（不联网），只替换网络层：

  Python: `bilibili._Client._get`（与线上失败分支同一入口）
  JS    : 全局 `fetch`（biliJson 的 catch 分支）

三条场景断言两端 status 的 ok/count/error 逐字段一致：
  fail_all 接口全挂        → ok=false、error 非空
  fail_two 2/7 官号无响应  → ok=false、error 列出账号
  ok_empty 全部正常无动态  → ok=true、count=0、error=''（不得误判成失败）

运行：python3 tests/test_bili_status.py
      （需要 node；node 缺失则 SKIP 并退出码 0）
"""
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bilibili
from bilibili import BiliUnavailable, NO_RESPONSE

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRAPERS = [os.path.join(ROOT, 'static', 'scraper.js'),
            os.path.join(ROOT, 'android', 'app', 'src', 'main', 'assets', 'www', 'scraper.js')]

# 场景名 → Python 侧「哪些 uid 无响应」
SCENARIOS = {
    'fail_all': 'all',
    'fail_two': 'two',
    'ok_empty': 'none',
}

NODE_LOADER = r"""
const fs = require('fs');
let src = fs.readFileSync(process.argv[2], 'utf8');
const anchor = 'return { GAMES, fetchAll,';
if (!src.includes(anchor)) throw new Error('scraper.js 导出锚点未找到: ' + anchor);
src = src.replace(anchor, 'return { bilibiliAll, BILI_UIDS, GAMES, fetchAll,');
const S = new Function(src + '\nreturn Scraper;')();
const mode = process.argv[3];
const bad = mode === 'all'
  ? new Set(S.BILI_UIDS.map((u) => String(u[2])))
  : (mode === 'two' ? new Set([String(S.BILI_UIDS[0][2]), String(S.BILI_UIDS[2][2])]) : new Set());
// 与 bilibili.py 的 mock 同构：按 host_mid 判定，失败即 reject（biliJson 重试耗尽后抛出）
globalThis.fetch = async (u) => {
  const m = /host_mid=(\d+)/.exec(u);
  if (m && bad.has(m[1])) throw new Error('network down');
  return { ok: true, text: async () => '{"data":{"items":[]}}' };
};
(async () => {
  const r = await S.bilibiliAll(6);
  process.stdout.write(JSON.stringify({ status: r.status, count: r.events.length }));
})().catch((e) => { console.error(String(e)); process.exit(1); });
"""


def py_side(mode):
    """跑真实的 bilibili.fetch_all()，网络层换成按 host_mid 判定的 mock"""
    fails = {u[2] for u in bilibili.GAME_UIDS}
    if mode == 'two':
        fails = {bilibili.GAME_UIDS[0][2], bilibili.GAME_UIDS[2][2]}
    elif mode == 'none':
        fails = set()

    def _get(self, url, **kw):
        uids = [u for u in bilibili.GAME_UIDS
                if f'host_mid={u[2]}' in str(url) or str(u[2]) in str(kw)]
        uid = uids[0][2] if uids else None
        if uid in fails:
            raise BiliUnavailable(NO_RESPONSE)
        return {'data': {'items': []}}

    saved = (bilibili._Client._get, bilibili.time.sleep)
    bilibili._Client._get = _get
    bilibili.time.sleep = lambda *_a: None
    try:
        evs, status = bilibili.fetch_all()
    finally:
        bilibili._Client._get, bilibili.time.sleep = saved
    return {'status': status, 'count': len(evs)}


def main():
    if not shutil.which('node'):
        print('SKIP: 未找到 node，跳过 B站状态双端测试')
        return 0

    bad = 0
    # 硬约束：错误文案必须与 JS 逐字一致（两边都不得夹带异常原文）
    for script in SCRAPERS:
        src = open(script, encoding='utf8').read()
        if NO_RESPONSE not in src:
            bad += 1
            print('FAIL NO_RESPONSE 文案未同步到 %s' % os.path.relpath(script, ROOT))

    for name, mode in SCENARIOS.items():
        mine = py_side(mode)
        exp_ok = mode == 'none'
        if mine['status']['ok'] != exp_ok or mine['status']['count'] != 0:
            bad += 1
            print('FAIL py[%s] status = %s，期望 ok=%s / count=0' % (name, mine['status'], exp_ok))
        if exp_ok and mine['status']['error']:
            bad += 1
            print('FAIL py[%s] 正常空结果被误判为失败: %r' % (name, mine['status']['error']))
        if not exp_ok and not mine['status']['error']:
            bad += 1
            print('FAIL py[%s] 接口失败但 error 为空（Issue #24 原缺陷）' % name)

        for script in SCRAPERS:
            rel = os.path.relpath(script, ROOT)
            p = subprocess.run(['node', '-e', NODE_LOADER, 'node', script, mode],
                               capture_output=True, text=True)
            if p.returncode != 0:
                bad += 1
                print('FAIL js 侧无法加载 %s: %s'
                      % (rel, (p.stderr.strip().splitlines() or [''])[-1]))
                continue
            theirs = json.loads(p.stdout.strip(), strict=False)
            if mine['status'] != theirs['status'] or mine['count'] != theirs['count']:
                bad += 1
                print('MISMATCH[%s] %s\n  py = %s\n  js = %s'
                      % (name, rel, mine['status'], theirs['status']))
        print('[%s] py status = %s' % (name, mine['status']))

    print('场景 %d 个，mismatch %d' % (len(SCENARIOS), bad))
    print('ALL PASS' if bad == 0 else 'SOME FAILED')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
