#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
上传第71题材料表格截图到阿里云 OSS，返回公网外链。

凭证来源：不写死在脚本里，也不落盘。运行时从本次对话历史 jsonl 中
读取用户粘贴的那条凭证消息（AK/SK/bucket/region），仅内存使用，不回显明文。
图片：/tmp/q71img/p20_x258.png（2022-2023年G省社零额表格）。
对象名：mm5/q71/material_<md5前12>.png（内容寻址，重复上传同一图不产生新对象）。
"""
import re, sys, hashlib, json
import oss2

TRANSCRIPT = '/root/.codebuddy/projects/workspace/2f8a7d30-9c21-4f0b-1d75-f8a2615ff000.jsonl'
IMG = '/tmp/q71img/p20_x258.png'
PREFIX = 'mm5/q71/'

def load_creds():
    raw = open(TRANSCRIPT, encoding='utf-8').read()
    # 用户消息里的凭证：AK  SK  bucket  华南3(广州)
    ak = re.search(r'LTAI[A-Za-z0-9]{12,}', raw)
    # SK：紧跟 AK 之后、形如 30 位字母数字（用户原文第二段）
    sk = re.search(r'LTAI[A-Za-z0-9]{12,}\s+([A-Za-z0-9]{20,40})\s+alibbxtbox', raw)
    if not ak or not sk:
        raise SystemExit('未在对话记录中找到完整凭证')
    return ak.group(), sk.group(1), 'alibbxtbox', 'oss-cn-guangzhou.aliyuncs.com'

def main():
    ak, sk, bucket, endpoint = load_creds()
    auth = oss2.Auth(ak, sk)
    b = oss2.Bucket(auth, 'https://' + endpoint, bucket)

    data = open(IMG, 'rb').read()
    md5 = hashlib.md5(data).hexdigest()[:12]
    key = PREFIX + 'material_' + md5 + '.png'

    print('bucket=%s endpoint=%s' % (bucket, endpoint))
    print('对象名=%s  (%d bytes)' % (key, len(data)))

    result = b.put_object(key, data, headers={'Content-Type': 'image/png'})
    url = 'https://%s.%s/%s' % (bucket, endpoint, key)
    print('上传成功 HTTP=%s etag=%s' % (result.status, result.etag))
    print('URL=' + url)

    # 校验可公网读
    head = b.get_object_meta(key)
    print('校验 head HTTP=%s size=%s' % (head.status, head.content_length))

    # 把 URL 落到一个小文件供后续脚本读取
    out = '/workspace/mindmap-server/tools/q71_material_url.txt'
    open(out, 'w', encoding='utf-8').write(url)
    print('URL 已写入 ' + out)

if __name__ == '__main__':
    main()
