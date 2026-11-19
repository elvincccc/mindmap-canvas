#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
解析数据 v2（三段式·详版）校验脚本。

结构：answer / oneLiner / steps[] (三段式) / errors[] / insight{} (对象)
检查：
  1. answer 与 ans 一致；oneLiner ≤35 字
  2. steps.n 连续；action≤12 / why 20~45 / detail 50~70 字（边界放行±3字）；至多一个 key
  3. errors 字母集合 = 选项字母 − 答案字母（只错项）
  4. error.type 仅需非空（开放填写、随机应变）；why ≤30 字
  5. insight 为对象，含 signal/essence/strategy；strategy 含 4 子字段
  6. 输出错误类型分布

用法：
  python3 tools/validate_v2.py 解析样板题v2.json --samples
  python3 tools/validate_v2.py data.json
"""
import argparse
import json
import sys
from collections import Counter

# error.type 开放填写：以下仅为参考建议，校验器不再拦截表外类型（2026-11-19 起）
REFERENCE_ERROR_TYPES = {
    "肯后推肯前", "否前推否后", "箭头方向颠倒", "强加因果", "因果倒置",
    "无中生有", "偷换概念", "以偏概全", "样本不当", "另有他因",
    "范围扩大", "范围缩小", "绝对化",
    "无关选项", "力度不足", "支持项",
    "自相矛盾", "计算错误",
    # 言语理解专用
    "搭配不当", "语义重复", "偏离主旨", "衔接不当", "语序不当", "不合设问",
}
# 字段字数区间：(下限(不含), 上限(含))；None 表示该侧不设限
# action ≤12；why 20~45；detail 50~70（下限强制、自然书写，避免顶格）
# 边界容差 TOLERANCE=3：多写或少写 1~3 字一律放行（即实际放行 why 17~48、detail 47~73）
TOLERANCE = 3
STEP_LIMITS = {
    "action": (None, 12),
    "why": (20, 45),
    "detail": (50, 70),
}


def letters(opts):
    return {str(o).strip()[:1].upper() for o in (opts or []) if o}


def validate(item):
    errs, warns = [], []
    sol = item.get("solution")
    if not isinstance(sol, dict):
        return ["缺少 solution"], warns

    ans = str(item.get("ans") or "").strip().upper()
    if str(sol.get("answer") or "").strip().upper() != ans:
        errs.append(f"answer({sol.get('answer')}) != ans({ans})")

    ol = sol.get("oneLiner")
    if not ol:
        errs.append("oneLiner 缺失")
    elif len(ol) > 35 + TOLERANCE:
        errs.append(f"oneLiner 超 {35 + TOLERANCE} 字（{len(ol)}）")

    # steps 三段式
    steps = sol.get("steps")
    if not isinstance(steps, list):
        errs.append("steps 缺失（无步骤应写 []）")
    else:
        ns = [s.get("n") for s in steps]
        if ns and ns != list(range(1, len(steps) + 1)):
            errs.append(f"steps.n 非连续: {ns}")
        if sum(1 for s in steps if s.get("key")) > 1:
            errs.append("多个 key:true")
        for s in steps:
            for f, (lo, hi) in STEP_LIMITS.items():
                v = s.get(f)
                if not v:
                    errs.append(f"steps[{s.get('n')}] 缺 {f}")
                    continue
                # 边界容差：多写或少写 1~3 字放行（下限放宽 TOLERANCE、上限放宽 TOLERANCE）
                if lo is not None and len(v) < lo - TOLERANCE:
                    errs.append(f"steps[{s.get('n')}].{f} 不足（{len(v)}字，需 ≥{lo - TOLERANCE}）")
                if hi is not None and len(v) > hi + TOLERANCE:
                    errs.append(f"steps[{s.get('n')}].{f} 超 {hi + TOLERANCE} 字（{len(v)}）")

    # errors 只错项
    errL = {str(e.get("o", "")).strip().upper() for e in sol.get("errors", [])}
    expect = letters(item.get("opts")) - {ans}
    if errL != expect:
        errs.append(f"errors 字母 {sorted(errL)} != 期望 {sorted(expect)}")
    for e in sol.get("errors", []):
        t, w = e.get("type"), e.get("why")
        if not t:
            errs.append(f"选项 {e.get('o')} 缺 type")
        # type 开放填写，不再校验是否在词表
        if not w:
            errs.append(f"选项 {e.get('o')} 缺 why")
        elif len(w) > 30 + TOLERANCE:
            errs.append(f"选项 {e.get('o')} why 超 {30 + TOLERANCE} 字（{len(w)}）")

    # insight 对象 + 详版
    ins = sol.get("insight")
    if not isinstance(ins, dict):
        errs.append("insight 必须是对象")
    else:
        for f in ("signal", "essence"):
            if not ins.get(f):
                warns.append(f"insight.{f} 缺失")
        for f in ("formula", "pitfalls"):
            if not isinstance(ins.get(f), list):
                warns.append(f"insight.{f} 缺失或非数组")
        st = ins.get("strategy")
        if not isinstance(st, dict):
            errs.append("insight.strategy 缺失")
        else:
            for f in ("shouldDo", "bestWay", "timeCost", "traps"):
                if not st.get(f):
                    warns.append(f"strategy.{f} 缺失")
    return errs, warns


def iter_examples(obj, seen=None):
    """遍历所有带 solution 的例题，按对象 id 去重（同一例题可能在 examples 列表
    里被 yield 一次、又因自身含 solution 被再 yield 一次，导致重复计数）。"""
    if seen is None:
        seen = set()
    if isinstance(obj, dict):
        if "solution" in obj and id(obj) not in seen:
            seen.add(id(obj))
            yield obj
        for v in obj.values():
            yield from iter_examples(v, seen)
    elif isinstance(obj, list):
        for v in obj:
            yield from iter_examples(v, seen)


def main():
    ap = argparse.ArgumentParser(description="解析数据 v2（三段式·详版）校验")
    ap.add_argument("file")
    ap.add_argument("--samples", action="store_true")
    args = ap.parse_args()

    data = json.load(open(args.file, encoding="utf-8"))
    items = data["samples"] if args.samples else [x for x in iter_examples(data) if "solution" in x]

    bad = 0
    ec = Counter()
    print(f"校验: {args.file}\n题目数: {len(items)}\n")
    for i, item in enumerate(items):
        label = item.get("src") or item.get("key") or f"#{i+1}"
        errs, warns = validate(item)
        if errs:
            bad += 1
            print(f"[FAIL] {label}")
            for e in errs:
                print(f"       ✗ {e}")
        else:
            nstep = len(item["solution"].get("steps") or [])
            print(f"[PASS] {label}  (三段式步骤{nstep})")
        for w in warns:
            print(f"       ! {w}")
        for e in (item.get("solution") or {}).get("errors", []):
            if e.get("type"):
                ec[e["type"]] += 1

    print("\n" + "=" * 50)
    print(f"结果: {len(items)-bad}/{len(items)} 通过, {bad} 失败")
    print("\n错误类型分布:")
    for k, v in ec.most_common():
        print(f"  {v:2d}  {k}")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
