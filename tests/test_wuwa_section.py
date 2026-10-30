# -*- coding: utf-8 -*-
"""鸣潮版本说明「全新活动以及玩法」章节解析测试。

通用提取会把正文里任意 [] / 「」 引用(角色/武器/区域/任务/道具)当活动名,
只要附近有日期就上月历,于是「情匣」「探历札记」「梦枢心相由心生」这类
非活动条目混进列表。专属解析只认章节内 [活动名] + ✦活动时间。

运行:python3 tests/test_wuwa_section.py(node 缺失则跳过 JS 段)
"""
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scrapers  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
bad = 0

TEXT = (
    '3.7版本内容说明 前置章节: [情匣]区域任务 2026年10月8日04:00 ~ 2026年10月26日03:59 '
    '✦全新活动以及玩法✦ 【版本活动】： '
    '[团团勇者大乱斗]休闲活动 在安可的帮助下展开乱斗！ '
    '✦活动时间：3.7版本更新后 ~ 2026年11月11日11:59（服务器时间） '
    '[无音消除]休闲活动 指尖点点消除声骸棋子。 '
    '✦活动时间：2026年10月22日10:00 ~ 2026年11月9日03:59（服务器时间） '
    '[凭栏听雨之礼]限时签到活动 每日登录累计奖励。 '
    '✦活动时间：2026年10月22日10:00 ~ 2026年11月11日03:59（服务器时间） '
    '【版本调整优化】 ✦系统✦ [终焉矩阵]活动 修复若干问题。 '
)


def check(label, got, expect):
    global bad
    ok = got == expect
    if not ok:
        bad += 1
    print("[%s] %s: got=%r expect=%r" % ('OK ' if ok else 'FAIL', label, got, expect))


def main():
    global bad
    ver_start = datetime(2026, 10, 22, 10, 0)
    items = scrapers._wuwa_extract_events(TEXT, ver_start)
    names = [x[0] for x in items]
    check("只保留章节内 [活动名] 条目", names, ['团团勇者大乱斗', '无音消除', '凭栏听雨之礼'])
    check("不含正文任务/道具名", '情匣' in names, False)
    check("不含修复章节的活动名", '终焉矩阵' in names, False)
    by = {x[0]: x for x in items}
    check("版本更新后 ~ 单日期 → 起点为版本开服、终点为该日期",
          (by['团团勇者大乱斗'][1], by['团团勇者大乱斗'][2]),
          (ver_start, datetime(2026, 11, 11, 11, 59)))
    check("显式双日期区间",
          (by['无音消除'][1], by['无音消除'][2]),
          (datetime(2026, 10, 22, 10, 0), datetime(2026, 11, 9, 3, 59)))
    check("空文本返回空", scrapers._wuwa_extract_events('', ver_start), [])

    node = shutil.which('node')
    if node:
        js_path = os.path.join(ROOT, 'static', 'scraper.js')
        script = ("const fs=require('fs');const src=fs.readFileSync(%s,'utf8');"
                  "const S=new Function(src+'\\nreturn Scraper;')();"
                  "const items=S.wuwaExtractEvents(%s,new Date(2026,9,22,10,0));"
                  "console.log(JSON.stringify(items.map(([n,s,e])=>[n,s?s.getTime():null,e?e.getTime():null])));"
                  % (json.dumps(js_path), json.dumps(TEXT, ensure_ascii=False)))
        r = subprocess.run([node, '-e', script], capture_output=True, text=True, encoding='utf-8', timeout=60)
        if r.returncode != 0:
            print('FAIL: JS 执行失败\n' + r.stderr[:600])
            bad += 1
        else:
            got = json.loads(r.stdout.strip().splitlines()[-1])
            want = [[n, int(s.timestamp() * 1000) if s else None, int(e.timestamp() * 1000) if e else None]
                    for n, s, e in items]
            check("JS 端解析结果与 Python 一致", got, want)
    else:
        print('SKIP: 未找到 node，跳过 JS 双端比对')

    print('\n%s' % ('ALL PASS' if bad == 0 else 'SOME FAILED'))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
