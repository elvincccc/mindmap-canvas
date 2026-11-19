#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
将 data.json 中的 base64 / URL-encoded data URI 图片上传到你自己的阿里云 OSS，
并把 imgs 字段替换为公网外链，然后同步：
  1) data.json          (静态发布数据)
  2) data.js            (window.MM_DATA 本地兜底)
  3) mindmap.db examples.img (数据库，与静态数据保持一致)

用法（凭证通过环境变量传入，不写死在脚本里）：
  export OSS_ACCESS_KEY_ID="你的AccessKeyID"
  export OSS_ACCESS_KEY_SECRET="你的AccessKeySecret"
  export OSS_BUCKET="你的bucket名"
  export OSS_ENDPOINT="oss-cn-guangzhou.aliyuncs.com"   # 带地域的公网endpoint
  export OSS_PREFIX="mm5/"                              # 可选，对象前缀目录

  python3.11 tools/upload_b64_to_oss.py

  # 先演练不实际上传：
  DRY_RUN=1 python3.11 tools/upload_b64_to_oss.py

说明：
  - 使用公共读 ACL 上传（图片需公网可访问），对象 URL = https://{bucket}.{endpoint}/{prefix}{filename}
  - 若你有自定义域名/CDN，设置 OSS_CUSTOM_DOMAIN 即可用 https://{domain}/{prefix}{filename}
  - 每一步都有日志；替换前自动备份 data.json / data.js / mindmap.db
"""
import os, sys, json, base64, re, urllib.parse, shutil, hashlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # mindmap-server/
DATA_JSON = os.path.join(ROOT, 'data.json')
DATA_JS = os.path.join(ROOT, 'data.js')
DB = os.path.join(ROOT, 'mindmap.db')

AK = os.getenv('OSS_ACCESS_KEY_ID')
SK = os.getenv('OSS_ACCESS_KEY_SECRET')
BUCKET = os.getenv('OSS_BUCKET')
ENDPOINT = os.getenv('OSS_ENDPOINT', 'oss-cn-guangzhou.aliyuncs.com')
PREFIX = os.getenv('OSS_PREFIX', 'mm5/')
DOMAIN = os.getenv('OSS_CUSTOM_DOMAIN', '')
DRY_RUN = os.getenv('DRY_RUN') == '1'

if not DOMAIN:
    for k, v in [('OSS_ACCESS_KEY_ID', AK), ('OSS_ACCESS_KEY_SECRET', SK), ('OSS_BUCKET', BUCKET)]:
        if not v:
            print(f'[错误] 缺少环境变量 {k}'); sys.exit(1)

import oss2

MIME_EXT = {'image/jpeg':'jpg','image/png':'png','image/svg+xml':'svg','image/gif':'gif','image/webp':'webp'}

def decode_data_uri(img):
    """返回 (mime, bytes)；非 data URI 返回 None"""
    if not str(img).startswith('data:'):
        return None
    m = re.match(r'data:([^;,]+)(?:;[^,]*)?,(.*)', img, re.S)
    if not m:
        return None
    mime = m.group(1)
    payload = m.group(2)
    if ';base64' in img[:m.start(2)+20]:
        data = base64.b64decode(payload)
    else:
        data = urllib.parse.unquote_to_bytes(payload)
    return mime, data

def public_url(filename):
    if DOMAIN:
        return f'https://{DOMAIN}/{PREFIX}{filename}'
    return f'https://{BUCKET}.{ENDPOINT}/{PREFIX}{filename}'

def main():
    d = json.load(open(DATA_JSON, encoding='utf-8'))

    # 收集所有 data URI 图片的位置（精确到 examples 数组下标）
    targets = []
    def walk(node):
        for e in node.get('examples', []):
            dec = decode_data_uri(e.get('img', ''))
            if dec:
                targets.append((e, dec[0], dec[1]))
        for c in node.get('children', []):
            walk(c)
    for s in d['subjects'].values():
        for b in s.get('branches', []):
            walk(b)

    print(f'发现 {len(targets)} 张内嵌图片待上传')
    if not targets:
        print('无需处理'); return

    # 备份
    if not DRY_RUN:
        for f in (DATA_JSON, DATA_JS, DB):
            if os.path.exists(f):
                shutil.copy2(f, f + '.bak_upload')
        print('已备份 data.json / data.js / mindmap.db 为 *.bak_upload')

    # 初始化 OSS
    bucket = None
    if not DRY_RUN:
        auth = oss2.Auth(AK, SK)
        bucket = oss2.Bucket(auth, f'https://{ENDPOINT}', BUCKET)

    mapping = {}       # 原 img -> 新外链
    uploaded = {}      # 内容 hash -> 外链（去重：相同图片只上传一次）
    for i, (e, mime, data) in enumerate(targets, 1):
        ext = MIME_EXT.get(mime, 'img')
        digest = hashlib.md5(data).hexdigest()[:8]
        old_img = e['img']
        # 去重：若相同内容已上传，直接复用外链
        if digest in uploaded:
            url = uploaded[digest]
            print(f'  [复用] 与已上传图片相同 -> {url}')
            mapping[old_img] = url
            e['img'] = url
            continue
        filename = f'b64_{i:02d}_{digest}.{ext}'
        url = public_url(filename)
        if DRY_RUN:
            print(f'  [演练] {filename} ({len(data)}B) -> {url}')
        else:
            headers = {'Content-Type': mime, 'x-oss-object-acl': 'public-read'}
            bucket.put_object(PREFIX + filename, data, headers=headers)
            print(f'  [上传] {filename} ({len(data)}B) -> {url}')
        uploaded[digest] = url
        mapping[old_img] = url
        e['img'] = url

    if DRY_RUN:
        print('\n[演练完成] 未写入任何文件'); return

    # 写回 data.json
    with open(DATA_JSON, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, separators=(',', ':'))
    # 重新生成 data.js
    with open(DATA_JS, 'w', encoding='utf-8') as f:
        f.write('window.MM_DATA = ')
        json.dump(d, f, ensure_ascii=False, separators=(',', ':'))
        f.write(';\n')

    # 同步数据库
    import sqlite3
    con = sqlite3.connect(DB)
    cur = con.cursor()
    updated = 0
    for old, new in mapping.items():
        cur.execute('UPDATE examples SET img=? WHERE img=?', (new, old))
        updated += cur.rowcount
    con.commit()
    con.close()
    print(f'\n完成：替换 data.json/data.js 中 {len(mapping)} 处，数据库更新 {updated} 行')

    # 校验
    leftovers = 0
    def check(node):
        nonlocal leftovers
        for e in node.get('examples', []):
            if str(e.get('img','')).startswith('data:'): leftovers += 1
        for c in node.get('children', []): check(c)
    for s in d['subjects'].values():
        for b in s.get('branches', []): check(b)
    print(f'校验：剩余内嵌图片 {leftovers} 张（应为 0）')
    print(f'data.json 大小: {os.path.getsize(DATA_JSON)//1024} KB')

if __name__ == '__main__':
    main()
