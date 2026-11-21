#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
取消「实词辨析」下的套娃层（方案A）：
  现状：实词辨析 > 实词 > 8个辨析维度(其中"搭配对象"下挂第19题)
        实词辨析 > 实词搭配(desc) > 3道题(17/20/16)
  问题："实词"与"实词搭配"两层把「词种二分」和「辨析维度」两条轴混在同一层，
        名字/职责重叠，且与平行的"语境分析"(直接挂维度)结构不一致。
  目标：删除"实词""实词搭配"两个壳节点，8个维度直接挂"实词辨析"下，
        3道题按 signal/position 真实语义归位到对应维度，4题position一并校正。

归位映射（按 signal+position 真实语义，非节点位置）：
  第19题 → 搭配对象维度（跟壳上提，仅校正position去"实词·"前缀）
  第16题 → 语法功能维度（主谓搭配：动词前主语能否发出）
  第20题 → 固定搭配维度（鸿沟/路径/内涵等习惯搭配名词）
  第17题 → 词义侧重维度（position明确"词义侧重"；原挂"实词搭配"是错配）

用法：
  python3 remove_shici_wrapper.py           # DRY-RUN
  python3 remove_shici_wrapper.py --apply   # 写入 server/data.json
"""
import json, sys, shutil, hashlib

SERVER = '/workspace/mindmap-server/data.json'

# 维度节点 name 的识别前缀（"实词"壳的8个children）
DIM_PREFIXES = ['搭配对象', '语义轻重', '感情色彩', '语体色彩',
                '词义侧重', '语素差异', '语法功能', '固定搭配']

# 3道题归位：src -> (目标维度前缀, 新position)
REASSIGN = {
    '2024广东省考真题 第16题': ('语法功能', '言语理解 → 逻辑填空 → 实词辨析 → 语法功能'),
    '2026广东省考真题 第20题': ('固定搭配', '言语理解 → 逻辑填空 → 实词辨析 → 固定搭配'),
    '2026广东省考真题 第17题': ('词义侧重', '言语理解 → 逻辑填空 → 实词辨析 → 词义侧重'),
}
# 第19题只在"搭配对象"维度下，校正position
POS_19 = ('2024广东省考真题 第19题',
          '言语理解 → 逻辑填空 → 实词辨析 → 搭配对象')


def find(root, name):
    if isinstance(root, dict):
        if root.get('name') == name:
            return root
        for v in root.values():
            r = find(v, name)
            if r is not None:
                return r
    elif isinstance(root, list):
        for v in root:
            r = find(v, name)
            if r is not None:
                return r
    return None


def set_position(example_node, new_pos):
    """例题节点的 position 在 examples[0].solution.insight.position"""
    exs = example_node.get('examples') or []
    if not exs:
        return False
    sol = exs[0].setdefault('solution', {})
    ins = sol.setdefault('insight', {})
    old = ins.get('position', '')
    ins['position'] = new_pos
    return old != new_pos


def count_q(root):
    n = 0
    def rec(x):
        nonlocal n
        if isinstance(x, dict):
            n += len(x.get('examples') or [])
            for k in ('children', 'branches'):
                for c in (x.get(k) or []):
                    rec(c)
        elif isinstance(x, list):
            for y in x:
                rec(y)
    rec(root)
    return n


def find_example(root, src):
    """递归找 isExample 且 exSrc==src 的节点"""
    hit = [None]
    def rec(x):
        if isinstance(x, dict):
            if x.get('isExample') and x.get('exSrc') == src:
                hit[0] = x
            for k in ('children', 'branches'):
                for c in (x.get(k) or []):
                    rec(c)
        elif isinstance(x, list):
            for y in x:
                rec(y)
    rec(root)
    return hit[0]


def main():
    apply = '--apply' in sys.argv
    D = json.load(open(SERVER, encoding='utf-8'))
    sub = D['subjects']['言语理解']

    bianxi = find(sub, '实词辨析')
    shici = find(sub, '实词')
    shipai = find(sub, '实词搭配')
    assert bianxi is not None, '未找到 实词辨析'
    assert shici is not None, '未找到 实词（壳）'
    assert shipai is not None, '未找到 实词搭配（壳）'

    dims = shici.get('children') or []
    three = shipai.get('children') or []
    assert len(dims) == 8, f'实词维度应为8，实际{len(dims)}'
    assert len(three) == 3, f'实词搭配题应为3，实际{len(three)}'

    # 校验8个维度前缀都能识别
    dim_by_prefix = {}
    for p in DIM_PREFIXES:
        match = [d for d in dims if (d.get('name') or '').startswith(p)]
        assert len(match) == 1, f'维度前缀「{p}」命中{len(match)}个，应1个'
        dim_by_prefix[p] = match[0]

    # 校验3道题都能找到
    for src, (dp, _) in REASSIGN.items():
        node = find_example(bianxi, src)
        assert node is not None, f'未找到题目节点 {src}'
        assert dp in dim_by_prefix, f'目标维度 {dp} 不存在'

    n19 = find_example(bianxi, POS_19[0])
    assert n19 is not None, '未找到第19题节点'

    before = sum(count_q(b) for b in D['subjects'].values())

    print('=== 方案A：取消实词辨析套娃层 ===')
    print('删除壳节点: 「实词」(8维度) + 「实词搭配」(3题)')
    print('维度上提到 实词辨析:', '、'.join(DIM_PREFIXES))
    print('题目归位:')
    print('  第19题 → 搭配对象维度（跟壳上提）position校正')
    for src, (dp, pos) in REASSIGN.items():
        print(f'  {src.split()[-1]} → {dp}维度 | {pos}')
    print(f'当前全库题数: {before}')

    if not apply:
        print('\n[DRY-RUN] 未写入。加 --apply 执行。')
        return

    # ---- 执行变换 ----
    # 1) 3道题归位到目标维度 children（从实词搭配壳里移出）
    for src, (dp, pos) in REASSIGN.items():
        node = find_example(shipai, src)
        assert node is not None
        tgt = dim_by_prefix[dp]
        tgt.setdefault('children', []).append(node)
        set_position(node, pos)

    # 2) 第19题 position 校正（已在"搭配对象"维度下）
    set_position(n19, POS_19[1])

    # 3) 用8个维度替换原"实词辨析"的2个壳children
    bianxi['children'] = dims

    after = sum(count_q(b) for b in D['subjects'].values())
    print(f'\n题数: {before} -> {after} {"OK 守恒" if before == after else "!! 不守恒"}')
    assert before == after, '题数不守恒，终止'

    # 4) 结构自检
    assert len(bianxi.get('children') or []) == 8, '实词辨析应有8个维度'
    assert find(sub, '实词') is None and find(sub, '实词搭配') is None, '壳节点未删净'
    for src, (dp, _) in REASSIGN.items():
        n = find_example(bianxi, src)
        assert n is not None, f'{src} 迁移后丢失'

    bak = SERVER + '.bak_wrap'
    shutil.copy(SERVER, bak)
    with open(SERVER, 'w', encoding='utf-8') as f:
        json.dump(D, f, ensure_ascii=False, separators=(',', ':'))
    print(f'[APPLY] 写入完成 MD5={hashlib.md5(open(SERVER,"rb").read()).hexdigest()}')
    print('  下一步: split_data.py 重拆 + 同步 demo/data.json')


if __name__ == '__main__':
    main()
