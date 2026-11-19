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
import re
import subprocess
import sys
import time

REPO = 'elvincccc/mindmap-canvas'
BRANCH = 'main'
DEFAULT_MESSAGE = 'chore: atomic upload via gh_upload_atomic.py'

# 这些扩展名按二进制处理：blob 用 encoding=base64（content 单行、无换行）
BINARY_EXTS = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.ico', '.pdf'}


class ApiError(RuntimeError):
    """gh api 调用失败。"""


def is_binary(rel_path):
    """按扩展名判断文件是否二进制。"""
    return os.path.splitext(rel_path)[1].lower() in BINARY_EXTS


def _load_token():
    """从 gh 本地登录配置读取 oauth_token（部署脚本用 curl 直连 API 绕开 gh CLI 的 TLS 超时）。"""
    import re
    hosts = os.path.expanduser('~/.config/gh/hosts.yml')
    txt = open(hosts, encoding='utf-8').read()
    m = re.search(r'oauth_token:\s*(\S+)', txt)
    if not m:
        raise ApiError('未在 gh hosts.yml 找到 oauth_token')
    return m.group(1).strip()


def api(method, endpoint, payload=None, retries=3):
    """用 curl 调 GitHub API；大 payload 写临时文件避免 stdin 截断。检查 HTTP 状态码。"""
    import tempfile
    token = _load_token()
    url = 'https://api.github.com' + endpoint
    cmd = ['curl', '-sS', '-m', '60', '-X', method.upper(), url,
           '-H', 'Accept: application/vnd.github+json',
           '-H', 'Authorization: token ' + token,
           '-H', 'User-Agent: gh-upload-curl',
           '-w', '\n__HTTP_CODE__:%{http_code}']
    body = None
    if payload is not None:
        cmd += ['-H', 'Content-Type: application/json']
        body = json.dumps(payload, ensure_ascii=False)
        tmp = tempfile.NamedTemporaryFile('w', suffix='.json', delete=False, encoding='utf-8')
        tmp.write(body); tmp.close()
        cmd += ['--data-binary', '@' + tmp.name]
    last_err = None
    for attempt in range(1, max(1, retries) + 1):
        proc = subprocess.run(cmd, capture_output=True)
        out = proc.stdout.decode('utf-8', 'replace')
        code_match = re.search(r'__HTTP_CODE__:(\d+)', out)
        http_code = int(code_match.group(1)) if code_match else 0
        raw = out[:code_match.start()] if code_match else out
        if proc.returncode == 0 and 200 <= http_code < 300:
            try:
                return json.loads(raw) if raw.strip() else {}
            except json.JSONDecodeError:
                last_err = '非JSON响应: ' + raw[:200]
        else:
            last_err = 'HTTP %s / curl %d: %s' % (http_code, proc.returncode, raw[:300] or proc.stderr.decode('utf-8','replace').strip())
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

    # 读取本地文件：
    #  - 文本文件（.json/.js/...）优先用 encoding=utf-8 直传原文（大 JSON 用 base64 易被代理误判 400）
    #  - 二进制文件（图片等）用 encoding=base64，content 为单行无换行的 base64 字符串
    blobs_local = []
    for rel in rel_files:
        data = read_file(base_dir, rel)
        if is_binary(rel):
            content = base64.b64encode(data).decode('ascii')
            encoding = 'base64'
        else:
            content = data.decode('utf-8')
            encoding = 'utf-8'
        blobs_local.append({'rel': rel, 'content': content, 'encoding': encoding, 'size': len(data)})
        print(f'  [读取] {rel} ({len(data)} B, {encoding})')

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
        for item in blobs_local:
            print(f'  [3/6] POST /git/blobs  {item["rel"]} '
                  f'(原 {item["size"]} B, encoding={item["encoding"]})')
        tree_entries = [
            {'path': item['rel'], 'mode': '100644', 'type': 'blob', 'sha': f'<blob sha: {item["rel"]}>'}
            for item in blobs_local
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
    for item in blobs_local:
        rel, encoding = item['rel'], item['encoding']
        if encoding == 'base64':
            blob = api('POST', f'/repos/{REPO}/git/blobs',
                       {'content': item['content'], 'encoding': 'base64'}, retries=args.retries)
        else:
            # 文本优先 utf-8 直传；偶发失败时回退 base64
            try:
                blob = api('POST', f'/repos/{REPO}/git/blobs',
                           {'content': item['content'], 'encoding': 'utf-8'}, retries=args.retries)
            except ApiError as e:
                print(f'  [blob utf-8 失败, 回退 base64] {rel}: {str(e)[:120]}')
                blob = api('POST', f'/repos/{REPO}/git/blobs',
                           {'content': base64.b64encode(item['content'].encode('utf-8')).decode('ascii'),
                            'encoding': 'base64'}, retries=args.retries)
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
