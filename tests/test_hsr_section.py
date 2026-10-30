# -*- coding: utf-8 -*-
"""星铁版本说明「全新活动」章节解析测试。

通用 extract_events 会把正文里任意「」引用(角色/光锥/时装/场景/道具)当活动名,
只要附近有日期就上月历,导致「贪饕」「潮玩礼券」「知识、沉默、擦肩而过」等
非活动条目混入列表且没有配图。专属解析只认「全新活动」章节里的 ■ 条目。

运行:python3 tests/test_hsr_section.py
"""
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scrapers  # noqa: E402

bad = 0

TEXT = (
    '4.6版本更新说明 版本持续时间 4.6版本更新后 - 2026/11/11 06:00:00 '
    '※建议开拓者完成开拓任务「千星城」-「知识、沉默、擦肩而过」后体验本内容。 '
    '3、全新光锥 ■5星「献给明日的色彩（欢愉）」 可通过光锥活动跃迁「流光定影•献给明日的色彩」获取。 '
    '6、全新活动 '
    '■爱，幽灵与机器人 一条废弃机铠管线经由幽灵斯科特改造，竟变成了可为幽灵赋予肉身的「林登™具身机铠」生产线！ '
    '活动时间：4.6版本更新后 - 2026/11/11 03:59:00 参与条件：开拓等级≥21级 '
    '■「星际幻宠」乐园 活动期间，开拓者可使用「潮玩礼券」在「星际潮玩」中抽取多款星际幻宠。 '
    '开放时间：2026/10/21 12:00:00 - 2026/11/11 06:00:00 参与条件：开拓等级≥21级 '
    '■巡星之礼 活动期间，每日登录游戏即可获得签到奖励。完成7日签到累计可领取星轨专票*10！ '
    '7、其他内容 ■敌方 「堕神之血•亚婆离」「狂兽的胚芽」 ■玩法 「异相仲裁」 更新时间：4.6版本更新后 '
)


def check(label, got, expect):
    global bad
    ok = got == expect
    if not ok:
        bad += 1
    print("[%s] %s: got=%r expect=%r" % ('OK ' if ok else 'FAIL', label, got, expect))


def main():
    global bad
    ver_start = datetime(2026, 10, 28, 6, 0)
    ver_end = datetime(2026, 11, 11, 6, 0)
    items = scrapers._hsr_extract_events(TEXT, ver_start, ver_end)
    names = [x[0] for x in items]
    check("只保留章节内 ■ 条目", names, ['爱，幽灵与机器人', '星际幻宠乐园', '巡星之礼'])
    check("不含正文引用的任务名", '知识、沉默、擦肩而过' in names, False)
    check("不含光锥章节条目", '献给明日的色彩' in names, False)
    by = {x[0]: x for x in items}
    check("版本更新后 ~ 单日期 → 起点为版本开服、终点为该日期",
          (by['爱，幽灵与机器人'][1], by['爱，幽灵与机器人'][2]), (ver_start, datetime(2026, 11, 11, 3, 59)))
    check("显式双日期区间照常解析",
          (by['星际幻宠乐园'][1], by['星际幻宠乐园'][2]), (datetime(2026, 10, 21, 12, 0), ver_end))
    check("未写具体日期的活动用版本窗口兜底",
          (by['巡星之礼'][1], by['巡星之礼'][2]), (ver_start, ver_end))
    check("空文本返回空列表", scrapers._hsr_extract_events('', ver_start, ver_end), [])
    check("没有全新活动章节时退回通用提取(无名字则空)",
          scrapers._hsr_extract_events('活动时间：2026/10/21 12:00:00 - 2026/11/11 06:00:00', ver_start, ver_end), [])

    # ---- JS 端同口径(APK 本地模式也走这份解析)----
    node = shutil.which('node')
    if node:
        js_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               'static', 'scraper.js')
        script = ("const fs=require('fs');"
                  "const src=fs.readFileSync(%s,'utf8');"
                  "const S=new Function(src+'\\nreturn Scraper;')();"
                  "const items=S.hsrExtractEvents(%s,new Date(2026,9,28,6,0),new Date(2026,10,11,6,0));"
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
