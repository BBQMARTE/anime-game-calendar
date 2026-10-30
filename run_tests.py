# -*- coding: utf-8 -*-
"""一键跑 tests/ 下全部 test_*.py,汇总失败项。

用法:
    python run_tests.py            # 全部
    python run_tests.py notify     # 只跑文件名含 notify 的

退出码 0 = 全过;1 = 有失败。CI 与本地通用(不依赖 pytest)。
"""
import glob
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))


def main():
    keyword = sys.argv[1] if len(sys.argv) > 1 else ''
    files = sorted(glob.glob(os.path.join(ROOT, 'tests', 'test_*.py')))
    if keyword:
        files = [f for f in files if keyword in os.path.basename(f)]
    if not files:
        print('没有匹配的测试文件')
        return 1
    failed = []
    for path in files:
        name = os.path.basename(path)
        print(f'>>> {name}')
        r = subprocess.run([sys.executable, path], cwd=ROOT)
        if r.returncode != 0:
            failed.append(name)
    print(f'\n共 {len(files)} 个测试文件,失败 {len(failed)} 个')
    for name in failed:
        print(f'  FAIL {name}')
    return 0 if not failed else 1


if __name__ == '__main__':
    sys.exit(main())
