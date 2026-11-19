#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""导出判断推理中尚无 solution 的例题完整清单，按题型路径分组。"""
import json, sys

SRC = '/workspace/mindmap-server/data.json'
OUT = '/tmp/pending_p1.json'

d = json.load(open(SRC, encoding='utf-8'))
p1 = d['subjects']['判断推理']

rows = []

def walk(node, path):
    """沿 children/branches 递归，收集题目及其题型路径。"""
    if not isinstance(node, dict):
        return
    name = node.get('name') or node.get('title') or ''
    here = path + [name] if name else path
    # 本题节点的例题
    for ex in node.get('examples', []) or []:
        if not isinstance(ex, dict):
            continue
        rows.append({
            'path': ' > '.join(x for x in here if x),
            'src': ex.get('src', ''),
            'q': ex.get('q', ''),
            'opts': ex.get('opts', []),
            'ans': ex.get('ans', ''),
            'hit': ex.get('hit'),
            'img': ex.get('img', ''),
            'solve': ex.get('solve', ''),
            'analysis': ex.get('analysis', ''),
            'steps': ex.get('steps', []),
            'exclude': ex.get('exclude', []),
            'has_solution': bool(ex.get('solution')),
        })
    for key in ('children', 'branches'):
        for ch in node.get(key, []) or []:
            walk(ch, here)

walk(p1, [])

pending = [r for r in rows if not r['has_solution']]
done = [r for r in rows if r['has_solution']]

json.dump(pending, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)

# 报告
from collections import Counter
print(f'判断推理总例题: {len(rows)}')
print(f'已有 solution: {len(done)}')
print(f'待写: {len(pending)}')
print(f'待写中配图题: {sum(1 for r in pending if r["img"])}')
print()
print('=== 按题型路径分组 ===')
g = {}
for r in pending:
    top = r['path'].split(' > ')[1] if ' > ' in r['path'] and len(r['path'].split(' > '))>1 else r['path'].split(' > ')[0]
    g.setdefault(top, []).append(r)
for k, v in sorted(g.items(), key=lambda x: -len(x[1])):
    imgs = sum(1 for r in v if r['img'])
    print(f'  {k}: {len(v)} 道 (配图 {imgs})')
print()
print(f'清单已写入: {OUT}')
