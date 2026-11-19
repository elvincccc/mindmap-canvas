#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
regroup_examples.py —— 按 src 把例题从旧知识点节点移到新节点（修正归类错误）

用途：补录/审查时发现题目挂错节点，用本脚本精确迁移，避免手工改树出错。
路径用「模块 > 分支 > 知识点前缀」三段表示，前缀匹配即可（无需写全特殊字符）。

用法：
  # 先看会改什么，不写文件
  python3 tools/regroup_examples.py --dry \
    --move "2025广东省考真题 第84题|其他综合/综合/能够推出判断|增长/增长量/增长量：Δ=现期−基期"

  # 确认后实际执行（默认同时改四个文件）
  python3 tools/regroup_examples.py \
    --move "2025广东省考真题 第84题|其他综合/综合/能够推出判断|增长/增长量/增长量：Δ=现期−基期"

  # 指定文件
  python3 tools/regroup_examples.py --files /path/a.json /path/b.json --move "..."

约定：
  - --move 可重复，格式：src|旧节点路径|新节点路径（路径以 / 分隔）
  - src 必须精确匹配且唯一命中；命中数≠1 直接报错，防止误移
  - 目标知识点须含 examples 字段；找不到节点直接报错
  - 写回统一用紧凑 JSON（ensure_ascii=False, separators=(',',':')）
"""
import argparse
import json
import sys

DEFAULT_FILES = [
    '/workspace/mindmap-demo/data/subjects/p5.json',  # 线上主数据源
    '/workspace/mindmap-demo/data.json',               # 线上回退
    '/workspace/mindmap-demo/data.js',                 # 本地 file:// 兜底
    '/workspace/mindmap-server/data.json',             # 后台副本
]


def name_match(name, seg):
    """知识点名很长且含特殊字符，用前缀匹配定位"""
    return name == seg or name.startswith(seg)


def find_knowledge_node(subject_data, path_parts, subject):
    """path_parts: [模块, 分支, 知识点前缀] -> 返回含 examples 的知识点 dict"""
    branches = subject_data['branches']
    mod = next((b for b in branches if name_match(b['name'], path_parts[0])), None)
    if not mod:
        raise ValueError(f'[{subject}] 模块未找到: {path_parts[0]}')
    br = next((b for b in mod.get('children', []) if name_match(b['name'], path_parts[1])), None)
    if not br:
        raise ValueError(f'[{subject}] 分支未找到: {path_parts[1]}')
    kp = next((c for c in br.get('children', [])
               if 'examples' in c and name_match(c['name'], path_parts[2])), None)
    if not kp:
        raise ValueError(f'[{subject}] 知识点未找到: {path_parts[2]}')
    return kp, ' > '.join([mod['name'], br['name'], kp['name']])


def apply_moves(root, moves, subject='资料分析'):
    """root 可以是完整四轨数据(含 subjects)或单科数据(含 branches)"""
    data = root['subjects'][subject] if 'subjects' in root else root
    logs = []
    for src, old_path, new_path in moves:
        old_node, old_full = find_knowledge_node(data, old_path, subject)
        new_node, new_full = find_knowledge_node(data, new_path, subject)
        hits = [e for e in old_node['examples'] if e.get('src') == src]
        if len(hits) != 1:
            raise ValueError(f'[{subject}] {src}: 在旧节点命中 {len(hits)} 条（预期1），已跳过全部写回')
        e = hits[0]
        old_node['examples'].remove(e)
        new_node['examples'].append(e)
        logs.append(f'{src}\n    - {old_full}\n    + {new_full}')
    return logs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--move', action='append', required=True,
                    help='src|旧路径|新路径，路径用 / 分隔，可重复')
    ap.add_argument('--files', nargs='+', default=DEFAULT_FILES)
    ap.add_argument('--subject', default='资料分析')
    ap.add_argument('--dry', action='store_true', help='只打印，不写回')
    args = ap.parse_args()

    moves = []
    for raw in args.move:
        parts = raw.split('|')
        if len(parts) != 3:
            sys.exit(f'--move 格式错误: {raw}（应为 src|旧路径|新路径）')
        moves.append((parts[0].strip(), parts[1].strip().split('/'), parts[2].strip().split('/')))

    for path in args.files:
        try:
            with open(path, encoding='utf-8') as f:
                root = json.load(f)
        except FileNotFoundError:
            print(f'跳过（不存在）: {path}')
            continue
        logs = apply_moves(root, moves, args.subject)
        if not args.dry:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(root, f, ensure_ascii=False, separators=(',', ':'))
        print(f'{"[DRY] " if args.dry else "[已写] "}{path}')
        for log in logs:
            print('    ' + log)
    print('\n完成。' + ('（DRY 模式未写任何文件）' if args.dry else ''))


if __name__ == '__main__':
    main()
