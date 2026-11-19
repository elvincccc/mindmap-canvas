#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把批量重写的 solution 幂等注入全部数据文件（server/demo/data.js/p1）。

用法：
  python3 tools/batch_inject.py /tmp/batch_p1_1.json       # 注入
  python3 tools/batch_inject.py /tmp/batch_p1_1.json --check  # 只检查匹配

输入 JSON：{"src": "2026广东省考真题 第60题", "solution": {...}} 组成的数组，
以 src 为唯一键定位例题（判断推理内 src 唯一）。
"""
import json, sys, shutil, os

SERVER = '/workspace/mindmap-server/data.json'
DEMO = '/workspace/mindmap-demo/data.json'
DEMOJS = '/workspace/mindmap-demo/data.js'

# 科目名 → 分科文件；默认判断推理，可用 --subject 切换
SUBJECT_FILE = {
    '判断推理': '/workspace/mindmap-demo/data/subjects/p1.json',
    '数量关系': '/workspace/mindmap-demo/data/subjects/p3.json',
    '言语理解': '/workspace/mindmap-demo/data/subjects/p4.json',
    '资料分析': '/workspace/mindmap-demo/data/subjects/p5.json',
}

def get_subject():
    if '--subject' in sys.argv:
        return sys.argv[sys.argv.index('--subject') + 1]
    return '判断推理'

SUBJECT = get_subject()
SUBJ_FILE = SUBJECT_FILE.get(SUBJECT)
if not SUBJ_FILE:
    print(f'!! 未知科目 {SUBJECT}，可选: {list(SUBJECT_FILE)}')
    sys.exit(1)

SRC_FILES = [SERVER, DEMO, SUBJ_FILE]


JS_PREFIX = 'window.MM_DATA = '
_js_wrapped = False  # 原文件是否带 window.MM_DATA 包装，按原格式写回


def load_js(path):
    global _js_wrapped
    raw = open(path, encoding='utf-8').read()
    if raw.startswith(JS_PREFIX):
        _js_wrapped = True
        body = raw[len(JS_PREFIX):].strip()
        if body.endswith(';'):
            body = body[:-1]
        return json.loads(body)
    _js_wrapped = False
    return json.loads(raw)


def dump_js(path, data):
    body = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
    with open(path, 'w', encoding='utf-8') as f:
        f.write((JS_PREFIX + body + ';') if _js_wrapped else body)


def walk(node, fn):
    if isinstance(node, dict):
        fn(node)
        for v in node.values():
            walk(v, fn)
    elif isinstance(node, list):
        for v in node:
            walk(v, fn)


def count_solutions(obj):
    n = [0]
    def hit(d):
        if 'solution' in d:
            n[0] += 1
    walk(obj, hit)
    return n[0]


def main():
    batch = json.load(open(sys.argv[1], encoding='utf-8'))
    check_only = '--check' in sys.argv
    by_src = {x['src']: x['solution'] for x in batch}
    assert len(by_src) == len(batch), 'batch 内 src 有重复'
    print(f'批次: {len(batch)} 道, src 唯一')

    # 先核对：每个 src 在 server 里能定位到，且无 solution（幂等时允许已有）
    d = json.load(open(SERVER, encoding='utf-8'))
    found = {}
    def locate(x):
        s = x.get('src')
        if s in by_src:
            found.setdefault(s, []).append(x)
    walk(d['subjects'][SUBJECT], locate)
    miss = [s for s in by_src if s not in found]
    dup = [s for s, v in found.items() if len(v) > 1]
    if miss:
        print('!! 未定位:', miss)
    if dup:
        print(('!! src 重复定位(将全部注入): ' if '--allow-dup' in sys.argv else '!! src 重复定位: ') + str(dup))
    if miss or (dup and '--allow-dup' not in sys.argv):
        sys.exit(1)
    already = [s for s, v in found.items() if v[0].get('solution')]
    print(f'定位 {len(found)}/{len(by_src)}; 已有 solution {len(already)} (将覆盖)')
    if check_only:
        return

    # 注入四处
    for path in SRC_FILES:
        obj = json.load(open(path, encoding='utf-8'))
        n = [0]
        def inject(x, n=n):
            s = x.get('src')
            if s in by_src:
                x['solution'] = by_src[s]
                n[0] += 1
        # 只遍历目标科目，避免 src 跨科重名
        if 'subjects' in obj:
            walk(obj['subjects'][SUBJECT], inject)
        else:
            walk(obj, inject)
        json.dump(obj, open(path, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
        print(f'  {os.path.basename(path):12s} 注入 {n[0]} 道, 全库 solution={count_solutions(obj)}')

    jd = load_js(DEMOJS)
    n = [0]
    def inject_js(x):
        s = x.get('src')
        if s in by_src:
            x['solution'] = by_src[s]
            n[0] += 1
    walk(jd['subjects'][SUBJECT], inject_js)
    dump_js(DEMOJS, jd)
    print(f'  {"data.js":12s} 注入 {n[0]} 道, 全库 solution={count_solutions(jd)}')


if __name__ == '__main__':
    main()
