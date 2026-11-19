#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
question_index.py —— 题目轻量索引：先读小索引定位，再按需抽单题全文。

解决痛点：AI 审查/核对某题时，不必把整份分科文件（如 p5.json 约 4 万 token）
读进上下文，只读索引（全库约 7 千 token）定位，再用 get 抽单题（约 400 token）。

设计原则（与项目铁律一致）：
  - 索引是「派生品」，不手写、不落项目数据目录，只读源数据生成
  - 默认输出到 /tmp，不污染仓库；--out 可指定
  - 不改动任何现有数据文件，纯粹新增读取入口
  - 仅供 AI 审查省上下文，前端/线上不用

用法：
  # 1) 生成索引（默认全库精简字段，写到 /tmp/question_index.json）
  python3 tools/question_index.py build
  python3 tools/question_index.py build --subject 资料分析 --out /tmp/idx_p5.json
  python3 tools/question_index.py build --full   # 需要一句话解法时用全字段版

  # 2) 按需抽单题全文（三种定位方式，题号撞车时用 卷名+题号 或 完整src）
  python3 tools/question_index.py get "2025广东省考真题 第84题"     # 完整 src 精确
  python3 tools/question_index.py get 84 --vol 2025广东省考真题      # 卷名+题号（推荐）
  python3 tools/question_index.py get 84 --subject 资料分析 --vol 26年省考35季
  python3 tools/question_index.py get 84 --subject 资料分析 --all    # 列出全部同号题
  python3 tools/question_index.py get "第84题" --fields oneLiner,steps,errors  # 只取解析某几块

索引字段（精简版）：subject / vol(卷名) / num / ans / node(知识点末级) / has_img
  --full 追加：oneLiner / position(完整知识树坐标)
"""
import argparse
import json
import re

SRC = '/workspace/mindmap-server/data.json'
DEFAULT_OUT = '/tmp/question_index.json'


def iter_examples(obj, path=None):
    """递归遍历任意科目对象，产出 (知识点路径, example)。"""
    path = path or []
    if not isinstance(obj, dict):
        return
    name = obj.get('name') or obj.get('title') or ''
    here = path + [name] if name else path
    for ex in obj.get('examples', []) or []:
        if isinstance(ex, dict):
            yield here, ex
    for key in ('children', 'branches'):
        for ch in obj.get(key, []) or []:
            yield from iter_examples(ch, here)


def parse_src(src):
    """从 '2025广东省考真题 第84题' 解析出 (卷名, 题号)。"""
    m = re.match(r'^(.*?)\s*第\s*(\d+)\s*题', src or '')
    if not m:
        return src or '', None
    return m.group(1).strip(), int(m.group(2))


def build(args):
    d = json.load(open(SRC, encoding='utf-8'))
    subjects = [args.subject] if args.subject else list(d['subjects'].keys())
    rows = []
    for subj in subjects:
        for node_path, ex in iter_examples(d['subjects'][subj]):
            vol, num = parse_src(ex.get('src', ''))
            sol = ex.get('solution', {}) or {}
            ins = sol.get('insight', {}) or {}
            row = {
                'subject': subj,
                'vol': vol,
                'num': num,
                'ans': ex.get('ans', ''),
                'node': ' > '.join(x for x in node_path if x).split(' > ')[-1][:26],
                'has_img': bool(ex.get('img')),
            }
            if args.full:
                row['oneLiner'] = sol.get('oneLiner', '')
                row['position'] = ins.get('position', '')
            rows.append(row)
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(rows, f, ensure_ascii=False, separators=(',', ':'))
    size = len(json.dumps(rows, ensure_ascii=False, separators=(',', ':')))
    print(f'索引已生成: {args.out}')
    print(f'  模式: {"全字段" if args.full else "精简版"}  题目数: {len(rows)}')
    print(f'  字符数: {size:,}  估算 token: ~{size//3:,}')
    if rows:
        print('  样例:')
        for r in rows[:3]:
            print(f'    {r["vol"]} #{r["num"]} {r["ans"]} | {r["node"][:24]}')


def get(args):
    d = json.load(open(SRC, encoding='utf-8'))
    subjects = [args.subject] if args.subject else list(d['subjects'].keys())
    key_is_num = args.key.isdigit()
    hits = []
    for subj in subjects:
        for node_path, ex in iter_examples(d['subjects'][subj]):
            src = ex.get('src', '')
            vol, num = parse_src(src)
            if key_is_num:
                matched = (num == int(args.key)) and (not args.vol or args.vol in vol)
            else:
                matched = args.key in src and (not args.vol or args.vol in vol)
            if matched:
                hits.append((subj, ' > '.join(x for x in node_path if x), ex))
    if not hits:
        print(f'未找到: {args.key}' + (f' (卷={args.vol})' if args.vol else ''))
        return
    if len(hits) > 1 and not args.all:
        print(f'命中 {len(hits)} 题，请细化（加 --vol 卷名 / --subject / --all）：')
        for s, p, e in hits:
            print(f'  {s} | {e.get("src")}')
        return
    for subj, node_path, ex in hits:
        print(f'=== {subj} | {ex.get("src")} ===')
        print(f'知识点路径: {node_path}')
        if args.fields:
            sol = ex.get('solution', {}) or {}
            want = [x.strip() for x in args.fields.split(',')]
            sub = {k: sol.get(k) for k in want if k in sol}
            print(json.dumps(sub, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(ex, ensure_ascii=False, indent=2))


def main():
    ap = argparse.ArgumentParser(description='题目轻量索引：build 建索引 / get 按需抽题')
    sub = ap.add_subparsers(dest='cmd', required=True)

    bp = sub.add_parser('build', help='生成轻量索引')
    bp.add_argument('--subject', help='只索引某科')
    bp.add_argument('--full', action='store_true', help='追加 oneLiner/position 字段')
    bp.add_argument('--out', default=DEFAULT_OUT)
    bp.set_defaults(func=build)

    gp = sub.add_parser('get', help='按需抽单题全文')
    gp.add_argument('key', help='题号数字 / src 片段')
    gp.add_argument('--subject', help='限定科目')
    gp.add_argument('--vol', help='限定卷名（解决题号撞车），如 2025广东省考真题')
    gp.add_argument('--fields', help='只取 solution 的某几块，逗号分隔，如 oneLiner,steps,errors')
    gp.add_argument('--all', action='store_true', help='命中多题时全部输出')
    gp.set_defaults(func=get)

    args = ap.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
