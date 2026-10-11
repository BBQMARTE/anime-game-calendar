# -*- coding: utf-8 -*-
"""data/notify.json 去跟踪测试（覆盖 Issue #19）。

该文件是运行时用户配置（webhook 凭据），此前被纳入版本控制，用户按 README 填好 webhook 后
`git status` 即出现已修改状态，任何 `git add -A && commit`（含 NPC 流水线）都会把私密 webhook
推进仓库。本测试断言它已被忽略、不再被跟踪，并保留示例文件与自动生成逻辑。

运行：python3 tests/test_notify_ignore.py
"""
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLE = os.path.join(ROOT, 'data', 'notify.example.json')

bad = 0

if subprocess.run(['git', 'rev-parse', '--git-dir'], cwd=ROOT,
                  capture_output=True).returncode != 0:
    print('SKIP: 非 git 工作区（或缺少 git），本测试跳过')
    sys.exit(0)


def check(label, got, expect):
    global bad
    ok = got == expect
    bad += 0 if ok else 1
    print("[%s] %s: got=%r expect=%r" % ('OK ' if ok else 'FAIL', label, got, expect))


def git(*args):
    return subprocess.run(['git'] + list(args), cwd=ROOT, capture_output=True, text=True)


# 1. data/notify.json 已被 .gitignore 忽略
r = git('check-ignore', '-v', 'data/notify.json')
check('check-ignore 有输出', r.returncode, 0)
check('命中 .gitignore 规则', 'data/notify.json' in r.stdout, True)

# 2. 该文件不再被跟踪（.gitignore 对已跟踪文件无效，必须 git rm --cached）
r = git('ls-files', 'data/notify.json')
check('不再被跟踪', r.stdout.strip(), '')

# 3. 用户填写 webhook 后不出现在 git status（模拟：写临时内容再还原）
notify = os.path.join(ROOT, 'data', 'notify.json')
existed = os.path.exists(notify)
backup = open(notify, encoding='utf-8').read() if existed else None
try:
    with open(notify, 'w', encoding='utf-8') as f:
        json.dump({'webhook': 'https://open.feishu.cn/open-apis/bot/v2/hook/FAKE-SECRET',
                   'time': '08:30'}, f, ensure_ascii=False)
    r = git('status', '--porcelain')
    check('填写 webhook 后 status 无该文件', 'data/notify.json' in r.stdout, False)
finally:
    if backup is not None:
        with open(notify, 'w', encoding='utf-8') as f:
            f.write(backup)
    elif os.path.exists(notify):
        os.remove(notify)

# 4. 示例文件随仓库分发且不含真实凭据
check('data/notify.example.json 存在', os.path.exists(EXAMPLE), True)
if os.path.exists(EXAMPLE):
    cfg = json.load(open(EXAMPLE, encoding='utf-8'))
    hook = cfg.get('webhook') or ''
    # 允许留空或占位符（xxxxxxxx），但不得含看起来像真实凭据的长 token
    check('示例 webhook 为空或占位符', hook == '' or 'xxxxxxxx' in hook, True)
    check('示例不含真实凭据', bool(re.search(r'[A-Za-z0-9_-]{24,}', hook)), False)
    check('示例含 time 字段', bool(cfg.get('time')), True)
    check('示例文件被跟踪', git('ls-files', 'data/notify.example.json').stdout.strip(),
          'data/notify.example.json')

print('\nALL PASS' if bad == 0 else '\n%d FAILED' % bad)
sys.exit(0 if bad == 0 else 1)
