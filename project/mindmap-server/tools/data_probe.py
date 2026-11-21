#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据勘察多用工具（只读、无副作用）——把开工勘察反复手写的 inline python 固化。

设计原则：
- 只读，绝不写数据文件（要写用 patch_solution / batch_inject / regroup_examples）。
- 结果只回摘要，不吐全量 JSON；全文只在 path 子命令按题抽取。
- 三轨：分科 subjects/p*.json 为首屏主源，server/data.json 为全量基准。默认读 server/data.json。

子命令：
  stats                      全库/分科统计：题数、例题节点、未展开examples、三轨MD5
  tree <分支名>               打印分支树结构 + 每节点例题数（如 tree 图形推理）
  scan --kw A,B [--subject X] 按 solution.insight.signal 关键词找同类题
  path "题目src"              查挂载路径 + 完整 solution（五块+insight）

用法示例：
  python3 tools/data_probe.py stats
  python3 tools/data_probe.py tree 逻辑判断
  python3 tools/data_probe.py scan --kw 反证,逆否 --subject 判断推理
  python3 tools/data_probe.py path "2025广东省考真题 第53题"
"""
import argparse, json, os, hashlib, sys

ROOT = '/workspace'
SERVER_DATA = os.path.join(ROOT, 'mindmap-server/data.json')
DEMO_DATA = os.path.join(ROOT, 'mindmap-demo/data.json')
SUBJ_DIR = os.path.join(ROOT, 'mindmap-demo/data/subjects')


def load(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def md5(path):
    h = hashlib.md5()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def iter_solution_nodes(obj):
    """遍历任意 dict/list，产出 (题目对象, 挂载路径list)。题目=含 src 且含 solution 的对象。"""
    def walk(o, path):
        if isinstance(o, dict):
            nm = o.get('name', '')
            cur = path + ([nm] if nm else [])
            if o.get('src') and isinstance(o.get('solution'), dict):
                yield o, cur
            for v in o.values():
                yield from walk(v, cur)
        elif isinstance(o, list):
            for v in o:
                yield from walk(v, path)
    yield from walk(obj, [])


def cmd_stats(args):
    d = load(SERVER_DATA)
    nodes = list(iter_solution_nodes(d))
    srcs = set(n.get('src') for n, _ in nodes)
    # 例题节点数 / 未展开 examples
    ex_node_cnt = 0
    unexpanded = 0

    def walk(o):
        nonlocal ex_node_cnt, unexpanded
        if isinstance(o, dict):
            if o.get('isExample'):
                ex_node_cnt += 1
            if o.get('examples') and not o.get('isExample'):
                # 非例题节点仍挂着未提升的 examples
                unexpanded += len(o['examples'])
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(d)
    print(f'[全库] 题目 {len(nodes)} 道 / 唯一src {len(srcs)} / 例题节点 {ex_node_cnt} / 未展开examples {unexpanded}')
    print('[三轨 MD5]')
    print(f'  server/data.json : {md5(SERVER_DATA)}')
    if os.path.exists(DEMO_DATA):
        same = md5(DEMO_DATA) == md5(SERVER_DATA)
        print(f'  demo/data.json   : {md5(DEMO_DATA)}  {"一致" if same else "⚠ 不一致"}')
    print('[分科首屏]')
    total = 0
    for p in sorted(f for f in os.listdir(SUBJ_DIR) if f.startswith('p') and f.endswith('.json')):
        sd = load(os.path.join(SUBJ_DIR, p))
        cnt = len(list(iter_solution_nodes(sd)))
        total += cnt
        print(f'  {p:<12}: {cnt} 题')
    print(f'  分科合计       : {total} 题')


def cmd_tree(args):
    d = load(SERVER_DATA)
    subjects = d.get('subjects', {})
    # 在指定科目里找名字匹配的分支根
    target = None
    for sname, sdata in subjects.items():
        if args.subject and sname != args.subject:
            continue
        def find(o):
            if isinstance(o, dict):
                if o.get('name') == args.branch:
                    return o
                for v in o.values():
                    r = find(v)
                    if r:
                        return r
            elif isinstance(o, list):
                for v in o:
                    r = find(v)
                    if r:
                        return r
            return None
        target = find(sdata)
        if target:
            break
    if not target:
        print(f'⚠ 未找到分支 {args.branch!r}' + (f'（科目 {args.subject}）' if args.subject else ''))
        sys.exit(1)

    def count_ex(node):
        n = 0
        def rec(x):
            nonlocal n
            n += len(x.get('examples') or [])
            for c in (x.get('children') or []):
                rec(c)
        rec(node)
        return n

    def print_tree(node, depth=0):
        nm = node.get('name', '')
        ex = count_ex(node)
        tag = f'  📄×{ex}' if ex else ''
        print('  ' * depth + f'[{depth}] {nm}{tag}')
        for c in (node.get('children') or []):
            print_tree(c, depth + 1)
    print_tree(target)


def cmd_scan(args):
    d = load(SERVER_DATA)
    kws = [k.strip() for k in args.kw.split(',') if k.strip()]
    hits = []
    # 先建 src→科目 映射（subject 路径首段粗判，供过滤）
    src_subject = {}
    for sname, sd in d.get('subjects', {}).items():
        for n, _ in iter_solution_nodes(sd):
            src_subject[n.get('src')] = sname
    for node, path in iter_solution_nodes(d):
        src = node.get('src', '')
        subj = src_subject.get(src, '?')
        if args.subject and subj != args.subject:
            continue
        sol = node['solution']
        ins = sol.get('insight') or {}
        blob = ' '.join([
            str(ins.get('signal', '') or ''),
            str(ins.get('essence', '') or ''),
            str(sol.get('oneLiner', '') or ''),
        ])
        if any(k in blob for k in kws):
            hits.append((src, subj, ' > '.join(path), ins.get('signal', '') or ''))
    scope = f'（科目 {args.subject}）' if args.subject else ''
    print(f'[scan] 关键词 {kws}{scope} → 命中 {len(hits)} 题')
    for src, subj, path, sig in hits:
        print(f'  [{subj}] {src}')
        print(f'  {src}')
        print(f'    路径: {path}')
        print(f'    signal: {sig[:78]}')


def _find_in(obj, src):
    if isinstance(obj, dict):
        if obj.get('src') == src:
            return obj
        for v in obj.values():
            r = _find_in(v, src)
            if r:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _find_in(v, src)
            if r:
                return r
    return None


def cmd_path(args):
    d = load(SERVER_DATA)
    node = _find_in(d, args.src)
    if not node:
        print(f'⚠ 未找到题目 src={args.src!r}')
        sys.exit(1)
    # 找挂载路径
    path = None
    for n, p in iter_solution_nodes(d):
        if n is node:
            path = p
            break
    print(f'题目: {node.get("src")}')
    print('挂载路径: ' + (' > '.join(path) if path else '(未定位)'))
    sol = node['solution']
    print('-' * 50)
    print(json.dumps(sol, ensure_ascii=False, indent=2))


def main():
    ap = argparse.ArgumentParser(description='数据勘察多用工具（只读无副作用）')
    sub = ap.add_subparsers(dest='cmd', required=True)

    sub.add_parser('stats', help='全库/分科统计 + 三轨MD5')

    p_tree = sub.add_parser('tree', help='打印分支树 + 例题数')
    p_tree.add_argument('branch', help='分支名，如 图形推理 / 逻辑判断')
    p_tree.add_argument('--subject', help='限定科目，如 判断推理')

    p_scan = sub.add_parser('scan', help='按signal关键词找同类题')
    p_scan.add_argument('--kw', required=True, help='关键词逗号分隔，如 反证,逆否')
    p_scan.add_argument('--subject', help='限定科目（预留）')

    p_path = sub.add_parser('path', help='查挂载路径 + 完整solution')
    p_path.add_argument('src', help='题目src或片段')

    args = ap.parse_args()
    {'stats': cmd_stats, 'tree': cmd_tree, 'scan': cmd_scan, 'path': cmd_path}[args.cmd](args)


if __name__ == '__main__':
    main()
