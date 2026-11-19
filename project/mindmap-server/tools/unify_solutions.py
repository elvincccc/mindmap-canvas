#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一三份数据的 solution：
  背景：demo/data.json 曾有 5 道 v2 样板，权威源 server/data.json 没有；
        第71题只注入了源。拆分后 demo/data/subjects/p1.json 的样板会丢失。
  做法：以 demo/data.json 的完整对象为基准（含 5 样板），把第71题也并进去，
        生成一份「6 题全量」数据，然后覆盖：
          server/data.json        （权威源）
          demo/data.json          （兜底分发）
          demo/data.js            （window.MM_DATA 本地兜底）
        再由 split_data.py 重新拆分 p1~p5，样板与第71题同时在位。
"""
import json, copy, os

SERVER_DATA = '/workspace/mindmap-server/data.json'
DEMO_DATA   = '/workspace/mindmap-demo/data.json'
DEMO_JS     = '/workspace/mindmap-demo/data.js'
Q71_SRC     = '2025广东省考真题 第71题'
Q71_NODE    = '累计求当期：当期值=本期累计−上期累计'

def iter_all(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from iter_all(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from iter_all(v)

def find_by_src(data, src):
    for o in iter_all(data):
        if o.get('src') == src:
            return o
    return None

def find_node(data, name):
    for o in iter_all(data):
        if o.get('name') == name:
            return o
    return None

src_data  = json.load(open(SERVER_DATA, encoding='utf-8'))   # 含第71题，无 5 样板
demo_data = json.load(open(DEMO_DATA, encoding='utf-8'))     # 含 5 样板，无第71题

# 1) 从源取出第71题完整对象
q71 = find_by_src(src_data, Q71_SRC)
assert q71 is not None, '源里没有第71题'
q71 = copy.deepcopy(q71)

# 2) 以 demo（含5样板）为基准，把第71题补进去
node = find_node(demo_data, Q71_NODE)
assert node is not None, 'demo 里没有目标节点'
exs = node.setdefault('examples', [])
exs[:] = [e for e in exs if e.get('src') != Q71_SRC]
exs.append(q71)

# 3) 统计全量 solution 数
def count_sol(data):
    return sum(1 for o in iter_all(data) if 'solution' in o)
print('合并后 solution 数:', count_sol(demo_data))

# 4) 覆盖三处
kw = dict(ensure_ascii=False, separators=(',', ':'))
with open(SERVER_DATA, 'w', encoding='utf-8') as f:
    json.dump(demo_data, f, **kw)
with open(DEMO_DATA, 'w', encoding='utf-8') as f:
    json.dump(demo_data, f, **kw)
with open(DEMO_JS, 'w', encoding='utf-8') as f:
    f.write('window.MM_DATA = ')
    json.dump(demo_data, f, **kw)
    f.write(';')

for p in (SERVER_DATA, DEMO_DATA, DEMO_JS):
    print('written', p, os.path.getsize(p), 'bytes')
