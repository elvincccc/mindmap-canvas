#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把数据文件里的 OSS URL 替换为 assets/img 相对路径。"""
import json, os

repl=json.load(open('/tmp/repl_map.json',encoding='utf-8'))
files=[
 '/workspace/mindmap-demo/data.json','/workspace/mindmap-demo/data.js',
 '/workspace/mindmap-demo/data/subjects/p1.json',
 '/workspace/mindmap-demo/data/subjects/p3.json',
 '/workspace/mindmap-demo/data/subjects/p4.json',
 '/workspace/mindmap-demo/data/subjects/p5.json',
 '/workspace/mindmap-server/data.json','/workspace/mindmap-server/data.js',
]

for f in files:
    if not os.path.exists(f):
        print('  跳过(不存在):',f); continue
    s=open(f,encoding='utf-8').read()
    before=s.count('alibbxtbox.oss-cn-guangzhou.aliyuncs.com')
    hit=0
    for old,new in repl.items():
        c=s.count(old)
        if c:
            s=s.replace(old,new); hit+=c
    after=s.count('alibbxtbox.oss-cn-guangzhou.aliyuncs.com')
    open(f,'w',encoding='utf-8').write(s)
    print(f'  {os.path.basename(f):<12} 原OSS{before:>3} 替换{hit:>3} 残留{after:>3}')
