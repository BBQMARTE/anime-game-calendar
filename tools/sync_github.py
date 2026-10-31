# -*- coding: utf-8 -*-
"""把 GitHub 镜像仓库的 main 对齐到本地 HEAD(CNB 主库)。

背景:本地 -> CNB 走 git push,CNB -> GitHub 走 GitHub API。历史上一直是
「只补改动文件」的增量同步,几轮下来 GitHub 树里留下了 CNB 已删除的旧文件,
部分文本又因换行差异与主库不一致。本脚本改为按本地 HEAD 的完整树重建:

  1) 本地 blob sha 与 GitHub 现有 blob sha 相同 -> 复用,不新建对象
  2) 不同 -> 用本地 git 对象内容建新 blob
  3) GitHub 有、本地没有的文件 -> sha=null 删除
最后建树、建 commit、移动 main,并逐文件校验 sha 与模式。

用法:
    python tools/sync_github.py                 # 用最近一次提交信息
    python tools/sync_github.py "自定义说明"     # 指定镜像 commit 信息
"""
import base64
import json
import subprocess
import sys

REPO = 'BBQMARTE/anime-game-calendar'
HEAD = 'HEAD'


def git(*args):
    r = subprocess.run(['git', '-c', 'core.quotepath=false', *args],
                       capture_output=True, cwd='.')
    if r.returncode != 0:
        raise RuntimeError('git %s failed: %s' % (args, r.stderr.decode('utf-8', 'replace')))
    return r.stdout


def gh(method, path, payload=None):
    args = ['gh', 'api', '-X', method, path]
    if payload is not None:
        args += ['--input', '-']
    r = subprocess.run(args,
                       input=json.dumps(payload).encode('utf-8') if payload is not None else None,
                       capture_output=True)
    if r.returncode != 0:
        raise RuntimeError('gh %s %s failed: %s' % (method, path, r.stderr.decode('utf-8', 'replace')))
    return json.loads(r.stdout.decode('utf-8')) if r.stdout.strip() else {}


def main():
    msg = sys.argv[1] if len(sys.argv) > 1 else git('log', '-1', '--pretty=%s').decode('utf-8').strip()
    ref = gh('GET', 'repos/%s/git/ref/heads/main' % REPO)
    parent = ref['object']['sha']
    parent_tree = gh('GET', 'repos/%s/git/commits/%s' % (REPO, parent))['tree']['sha']
    old = gh('GET', 'repos/%s/git/trees/%s?recursive=1' % (REPO, parent_tree))
    gh_blobs = {x['path']: x['sha'] for x in old['tree'] if x['type'] == 'blob'}

    local = []
    for line in git('ls-tree', '-r', '--full-tree', HEAD).decode('utf-8').splitlines():
        meta, path = line.split('\t', 1)
        mode, _typ, sha = meta.split()
        local.append((mode, path, sha))
    local_paths = {p for _, p, _ in local}

    entries = []
    created = reused = 0
    for mode, path, sha in local:
        if gh_blobs.get(path) == sha:
            reused += 1
            continue
        content = git('cat-file', '-p', '%s:%s' % (HEAD, path))
        blob = gh('POST', 'repos/%s/git/blobs' % REPO,
                  {'content': base64.b64encode(content).decode('ascii'), 'encoding': 'base64'})
        entries.append({'path': path, 'mode': mode, 'type': 'blob', 'sha': blob['sha']})
        created += 1
    for path in gh_blobs:
        if path not in local_paths:
            entries.append({'path': path, 'mode': '100644', 'type': 'blob', 'sha': None})

    tree = gh('POST', 'repos/%s/git/trees' % REPO, {'base_tree': parent_tree, 'tree': entries})
    commit = gh('POST', 'repos/%s/git/commits' % REPO,
                {'message': msg, 'tree': tree['sha'], 'parents': [parent]})
    gh('PATCH', 'repos/%s/git/refs/heads/main' % REPO, {'sha': commit['sha'], 'force': False})
    print('本地 %d 个文件:复用 %d,新建 blob %d,删除 %d' %
          (len(local), reused, created, sum(1 for e in entries if e['sha'] is None)))
    print('GitHub main: %s -> %s (tree %s)' % (parent[:8], commit['sha'][:8], tree['sha'][:8]))

    new = gh('GET', 'repos/%s/git/trees/%s?recursive=1' % (REPO, tree['sha']))
    got = {x['path']: (x['mode'], x['sha']) for x in new['tree'] if x['type'] == 'blob'}
    bad = [(path, got.get(path), (mode, sha)) for mode, path, sha in local
           if got.get(path) != (mode, sha)]
    extra = [p for p in got if p not in local_paths]
    print('校验:一致 %d / %d,不一致 %d,多余 %d' %
          (len(local) - len(bad), len(local), len(bad), len(extra)))
    for b in bad[:5]:
        print('  DIFF', b)
    for e in extra[:5]:
        print('  EXTRA', e)
    return 0 if not bad and not extra else 1


if __name__ == '__main__':
    sys.exit(main())
