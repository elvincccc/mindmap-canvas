#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第71题：题干 q 去掉文字版材料，只保留问题句（材料由截图承担）。幂等，四处同步。"""
import json, os

SRC = '2025广东省考真题 第71题'
NEW_Q = '2023年1~11月，G省社会消费品零售额约为（\u3000\u3000）万亿元。'
SERVER_DATA = '/workspace/mindmap-server/data.json'
DEMO_DATA   = '/workspace/mindmap-demo/data.json'
DEMO_JS     = '/workspace/mindmap-demo/data.js'
P5          = '/workspace/mindmap-demo/data/subjects/p5.json'

def iter_all(o):
    if isinstance(o, dict):
        yield o
        for v in o.values():
            yield from iter_all(v)
    elif isinstance(o, list):
        for v in o:
            yield from iter_all(v)

def patch(data):
    n = 0
    for o in iter_all(data):
        if o.get('src') == SRC:
            o['q'] = NEW_Q
            n += 1
    return n

kw = dict(ensure_ascii=False, separators=(',', ':'))
for path, is_js in [(SERVER_DATA, False), (DEMO_DATA, False), (P5, False), (DEMO_JS, True)]:
    raw = open(path, encoding='utf-8').read()
    if is_js:
        prefix = 'window.MM_DATA = '
        body = raw[len(prefix):].strip() if raw.startswith(prefix) else raw.strip()
        if body.endswith(';'):
            body = body[:-1]
        data = json.loads(body)
    else:
        data = json.loads(raw)
    n = patch(data)
    assert n == 1, '%s: 命中第71题 %d 次' % (path, n)
    with open(path, 'w', encoding='utf-8') as f:
        if is_js:
            f.write(prefix); json.dump(data, f, **kw); f.write(';')
        else:
            json.dump(data, f, **kw)
    print('OK %-12s q已精简 (%d bytes)' % (os.path.basename(path), os.path.getsize(path)))
print('新题干:', NEW_Q)
