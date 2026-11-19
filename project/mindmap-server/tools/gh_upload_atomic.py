#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用 GitHub Git Data API 一次 commit 上传多个文件到仓库（仅触发一次 Pages 部署）。

与逐文件 PUT /contents/:path 不同，本脚本在同一棵树、同一个 commit 中提交
所有文件变更，因此只需要一次 push 事件 → 只触发一次 deploy workflow，
彻底消除「N 个文件 = N 次部署」造成的冗余 / cancelled / failure。

流程（全部通过已登录的 gh CLI 调用 API，不硬编码 token）：
  1. GET  /repos/{repo}/git/ref/heads/main          -> 当前 commit sha
  2. GET  /repos/{repo}/git/commits/{sha}           -> 当前 tree sha
  3. POST /repos/{repo}/git/blobs  （每个文件一次）  -> blob sha
  4. POST /repos/{repo}/git/trees  （base_tree 复用原树，只覆盖给定文件）
  5. POST /repos/{repo}/git/commits （tree=新树, parents=[原 commit]）
  6. PATCH /repos/{repo}/git/refs/heads/main        -> 原子更新 main 指针

用法：
  python3 tools/gh_upload_atomic.py <目录> <相对文件列表...> [选项]
  python3 tools/gh_upload_atomic.py /workspace/mindmap-demo index.html data.json data.js \
      --message "update mindmap data"

选项：
  --dry-run            只打印执行计划，不实际写入仓库
  --message MSG        提交说明（默认 "chore: atomic upload via gh_upload_atomic.py"）
  --retries N          单个 API 调用的重试次数（默认 3）
"""
import argparse
import base64
import json
import os
import subprocess
import sys
import time

REPO = 'elvincccc/mindmap-canvas'
BRANCH = 'main'
DEFAULT_MESSAGE = 'chore: atomic upload via gh_upload_atomic.py'


class ApiError(RuntimeError):
    """gh api 调用失败。"""


def api(method, endpoint, payload=None, retries=3):
    """调用 gh api；payload 为 dict 时以 JSON 走 --input，凭证取自 gh 本地登录态。"""
    cmd = ['gh', 'api', endpoint]
    if method.upper() != 'GET':
        cmd += ['-X', method.upper()]
    cmd += ['-H', 'Accept: application/vnd.github+json']

    body = None
    if payload is not None:
        cmd += ['-H', 'Content-Type: application/json', '--input', '-']
        body = json.dumps(payload, ensure_ascii=False)

    last_err = None
    for attempt in range(1, max(1, retries) + 1):
        proc = subprocess.run(cmd, input=(body or ''), capture_output=True, text=True)
        if proc.returncode == 0:
            out = proc.stdout.strip()
            return json.loads(out) if out else {}
        last_err = f"exit {proc.returncode}: {proc.stderr.strip() or proc.stdout.strip()}"
        if attempt < max(1, retries):
            print(f'    [重试 {attempt}/{retries}] {last_err}', flush=True)
            time.sleep(2 * attempt)
    raise ApiError(f'{method} {endpoint} 失败 -> {last_err}')


def read_file(base_dir, rel_path):
    full = os.path.join(base_dir, rel_path)
    if not os.path.isfile(full):
        raise FileNotFoundError(f'找不到文件: {full}')
    with open(full, 'rb') as f:
        return f.read()


def main():
    parser = argparse.ArgumentParser(
        description='用 Git Data API 一次 commit 原子上传多个文件（只触发一次部署）')
    parser.add_argument('base_dir', help='要上传文件所在的本地目录')
    parser.add_argument('files', nargs='+', help='要上传的相对文件路径（可多个）')
    parser.add_argument('--dry-run', action='store_true', help='只打印计划，不实际写入仓库')
    parser.add_argument('--message', default=DEFAULT_MESSAGE, help='提交说明')
    parser.add_argument('--retries', type=int, default=3, help='单个 API 调用的重试次数')
    args = parser.parse_args()

    base_dir = os.path.abspath(args.base_dir)
    rel_files = list(dict.fromkeys(args.files))  # 去重且保序

    print(f'仓库      : {REPO} ({BRANCH})')
    print(f'本地目录  : {base_dir}')
    print(f'待传文件  : {", ".join(rel_files)}')
    print(f'提交说明  : {args.message}')
    print(f'模式      : {"DRY-RUN（不写入）" if args.dry_run else "实际上传"}')

    # 读取本地文件并做 base64 编码（dry-run 同样执行，便于核对内容大小）
    blobs_local = []
    for rel in rel_files:
        data = read_file(base_dir, rel)
        blobs_local.append((rel, base64.b64encode(data).decode('ascii'), len(data)))
        print(f'  [读取] {rel} ({len(data)} B)')

    # 1) 当前 commit sha / 2) 当前 tree sha（只读，dry-run 也执行以获得具体计划）
    print('\n[1/6] 获取 main 当前 commit ...')
    ref = api('GET', f'/repos/{REPO}/git/ref/heads/main', retries=args.retries)
    base_commit_sha = ref['object']['sha']
    print(f'  base commit = {base_commit_sha}')

    print('[2/6] 获取当前 commit 的 tree ...')
    commit = api('GET', f'/repos/{REPO}/git/commits/{base_commit_sha}', retries=args.retries)
    base_tree_sha = commit['tree']['sha']
    print(f'  base tree   = {base_tree_sha}')

    if args.dry_run:
        print('\n===== DRY-RUN 执行计划（不实际调用写接口）=====')
        for rel, b64, size in blobs_local:
            print(f'  [3/6] POST /git/blobs  {rel} (b64 {len(b64)} 字符, 原 {size} B, encoding=base64)')
        tree_entries = [
            {'path': rel, 'mode': '100644', 'type': 'blob', 'sha': f'<blob sha: {rel}>'}
            for rel, _, _ in blobs_local
        ]
        print(f'  [4/6] POST /git/trees  base_tree={base_tree_sha}')
        print(f'         tree = {json.dumps(tree_entries, ensure_ascii=False)}')
        print(f'  [5/6] POST /git/commits message="{args.message}" tree=<新 tree sha> '
              f'parents=["{base_commit_sha}"]')
        print(f'  [6/6] PATCH /git/refs/heads/main sha=<新 commit sha>  -> 原子更新 main')
        print('\n[DRY-RUN 完成] 未创建任何 blob/tree/commit，未修改仓库 ref。')
        return

    # 3) 逐文件创建 blob
    print('\n[3/6] 创建 blobs ...')
    tree_entries = []
    for rel, b64, size in blobs_local:
        blob = api('POST', f'/repos/{REPO}/git/blobs',
                   {'content': b64, 'encoding': 'base64'}, retries=args.retries)
        blob_sha = blob['sha']
        print(f'  [blob] {rel} -> {blob_sha}')
        tree_entries.append({'path': rel, 'mode': '100644', 'type': 'blob', 'sha': blob_sha})

    # 4) 基于原树创建新树：base_tree 保留未改动文件，tree 只覆盖本次给定文件
    print('[4/6] 创建新 tree（base_tree 复用原树）...')
    new_tree = api('POST', f'/repos/{REPO}/git/trees',
                   {'base_tree': base_tree_sha, 'tree': tree_entries}, retries=args.retries)
    new_tree_sha = new_tree['sha']
    print(f'  new tree   = {new_tree_sha}')

    # 5) 创建 commit，父提交指向原 commit
    print('[5/6] 创建 commit ...')
    new_commit = api('POST', f'/repos/{REPO}/git/commits',
                     {'message': args.message, 'tree': new_tree_sha,
                      'parents': [base_commit_sha]}, retries=args.retries)
    new_commit_sha = new_commit['sha']
    print(f'  new commit = {new_commit_sha}')

    # 6) 原子更新 main 引用（一次 PATCH = 一次 push 事件 = 一次部署）
    print('[6/6] 更新 refs/heads/main ...')
    api('PATCH', f'/repos/{REPO}/git/refs/heads/main',
        {'sha': new_commit_sha, 'force': False}, retries=args.retries)
    print('  main 已更新')

    print('\n========== 完成 ==========')
    print(f'本次原子提交包含 {len(rel_files)} 个文件: {", ".join(rel_files)}')
    print(f'最终 commit sha: {new_commit_sha}')
    print(f'查看: https://github.com/{REPO}/commit/{new_commit_sha}')


if __name__ == '__main__':
    try:
        main()
    except (ApiError, FileNotFoundError) as e:
        print(f'\n[错误] {e}', file=sys.stderr)
        sys.exit(1)
