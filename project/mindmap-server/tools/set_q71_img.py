#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把第71题材料图 OSS 外链写进 img 字段，并同步三份数据 + 分科文件。幂等。"""
import json, os

SRC = '2025广东省考真题 第71题'
IMG = open('/workspace/mindmap-server/tools/q71_material_url.txt', encoding='utf-8').read().strip()
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
    done = 0
    for o in iter_all(data):
        if o.get('src') == SRC:
            o['img'] = IMG
            done += 1
    return done

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
    assert n == 1, '%s: 命中第71题 %d 次（期望1）' % (path, n)
    with open(path, 'w', encoding='utf-8') as f:
        if is_js:
            f.write(prefix)
            json.dump(data, f, **kw)
            f.write(';')
        else:
            json.dump(data, f, **kw)
    print('OK %s  img已写入 (%d bytes)' % (os.path.basename(path), os.path.getsize(path)))

print('img URL =', IMG)
