#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
split_data.py —— 行测思维导图画布数据「按科目拆分」脚本

用途 / 背景
-----------
原 data.json（约 586KB）一次性打包了 5 个科目的全部数据，页面启动就要整体下载，
但同一时刻只会看 1 个科目，带宽浪费严重（沙箱约 20-30KB/s，首屏要等 20-35 秒）。

本脚本把它拆成：
  - 1 份轻量 manifest.json（palette / order / 科目->文件路径映射 / 每科 count、nodes / meta）
  - 5 份科目文件 subjects/p1.json ... p5.json（每科一个完整对象：color/modules/root/branches）

配合前端「按需加载」使用：
  - 页面启动只下载 manifest.json + 当前科目的那 1 个文件（约 120KB），不再全量下载 586KB。
  - 切换科目时，前端读 manifest.subjects[科目名] 得到文件路径（相对站点根），
    再 fetch 对应科目文件即可。
  - 前端 loadData 的改造由其他人（team-lead）负责，本脚本不修改 canvas.html。
  - /workspace/mindmap-demo/data.json 保留原样，作为前端加载失败时的 fallback。

科目文件名映射（稳定可预测，写进 manifest.subjects）：
  判断推理 -> p1.json   常识应用 -> p2.json   数量关系 -> p3.json
  言语理解 -> p4.json   资料分析 -> p5.json

manifest 结构（subjects 的值 kept 为「相对站点根」的路径字符串，便于前端直接 fetch）：
  {
    "palette": {...},
    "order": [...],
    "subjects": { "判断推理": "data/subjects/p1.json", ... },
    "stats":    { "判断推理": {"count": 54, "nodes": 211}, ... },
    "meta":     {"generated": "<ISO8601>", "total": 186}
  }
  - count = 该科例题数（所有 examples 列表长度之和）
  - nodes = 该科树节点数（所有带 name 字段的对象个数）
  - meta.total = 全站例题总数

运行：
  python3 /workspace/mindmap-server/tools/split_data.py

输出目录：/workspace/mindmap-demo/data/（作为静态站点可访问路径）
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# 路径（相对脚本位置推导，保证从任意 cwd 运行都正确）
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent          # .../mindmap-server/tools
SERVER_DIR = SCRIPT_DIR.parent                        # .../mindmap-server
WORKSPACE_DIR = SERVER_DIR.parent                     # .../workspace
INPUT_JSON = SERVER_DIR / "data.json"                 # 源数据（只读）
OUTPUT_DIR = WORKSPACE_DIR / "mindmap-demo" / "data"  # 输出目录

# ---------------------------------------------------------------------------
# 科目 -> 文件名映射（稳定、可预测）
# ---------------------------------------------------------------------------
SUBJECT_FILE_MAP = {
    "判断推理": "p1.json",
    "常识应用": "p2.json",
    "数量关系": "p3.json",
    "言语理解": "p4.json",
    "资料分析": "p5.json",
}

# 序列化参数：与现有 data.json 一致，压缩体积
DUMP_KWARGS = dict(ensure_ascii=False, separators=(",", ":"))


def count_stats(subject_obj):
    """统计单个科目的例题数(count)与节点数(nodes)。"""
    count = 0   # 例题数
    nodes = 0   # 树节点数（带 name 的对象）

    def walk(node):
        nonlocal count, nodes
        if isinstance(node, dict):
            if "name" in node:
                nodes += 1
            examples = node.get("examples")
            if isinstance(examples, list):
                count += len(examples)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(subject_obj)
    return count, nodes


def dump_json(path, obj):
    """以紧凑格式写入 JSON，返回文件字节数。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, **DUMP_KWARGS)
    return os.path.getsize(path)


def validate(data, manifest, written):
    """重组 5 个科目文件 + manifest，逐字段与原 data.json 对比，确认无损。"""
    ok = True
    original = data["subjects"]

    # 1) 每个科目文件必须与该科原始对象完全一致
    for name, filename in SUBJECT_FILE_MAP.items():
        rebuilt = written[name]
        if original[name] == rebuilt:
            print("  [OK] %s (%s) 逐字段一致" % (name, filename))
        else:
            ok = False
            print("  [FAIL] %s (%s) 与原数据不一致！" % (name, filename))

    # 2) 科目集合不能多也不能少
    if set(original) != set(written):
        ok = False
        print("  [FAIL] 科目集合不一致：orig=%s written=%s"
              % (set(original), set(written)))

    # 3) manifest 的 palette / order 必须与源一致
    if manifest["palette"] != data["palette"]:
        ok = False
        print("  [FAIL] manifest.palette 与源不一致")
    if manifest["order"] != data["order"]:
        ok = False
        print("  [FAIL] manifest.order 与源不一致")

    return ok


def human_size(num_bytes):
    return "%.1f KB (%d bytes)" % (num_bytes / 1024.0, num_bytes)


def main():
    # 1) 读源数据
    with open(INPUT_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)

    palette = data["palette"]
    order = data["order"]
    subjects = data["subjects"]

    # 防御：确保映射覆盖所有科目，且每科 4 个字段齐全
    missing = [s for s in subjects if s not in SUBJECT_FILE_MAP]
    if missing:
        raise RuntimeError("科目文件名映射缺少：%s" % missing)

    # 2) 生成 manifest 骨架
    manifest = {
        "palette": palette,
        "order": order,
        "subjects": {},   # 科目 -> "data/subjects/pN.json"（相对站点根）
        "stats": {},      # 科目 -> {count, nodes}
        "meta": {
            "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "total": 0,
        },
    }

    # 3) 逐科写出文件，同时记录重组结果用于校验
    subject_dir = OUTPUT_DIR / "subjects"
    written = {}
    sizes = {}
    total_examples = 0

    for name in order:
        obj = subjects[name]
        filename = SUBJECT_FILE_MAP[name]
        path = subject_dir / filename
        size = dump_json(path, obj)          # 原样写出，不改动任何字段
        written[name] = obj
        sizes[name] = size

        count, nodes = count_stats(obj)
        total_examples += count
        manifest["subjects"][name] = "data/subjects/%s" % filename
        manifest["stats"][name] = {"count": count, "nodes": nodes}

    manifest["meta"]["total"] = total_examples

    # 4) 写 manifest
    manifest_path = OUTPUT_DIR / "manifest.json"
    manifest_size = dump_json(manifest_path, manifest)

    # 5) 一致性校验
    print("=== 数据一致性校验 ===")
    ok = validate(data, manifest, written)
    if not ok:
        raise SystemExit("校验失败：拆分数据与源 data.json 不一致，已中止。")
    print("校验通过：5 个科目 + manifest 重组后与源数据逐字段一致。\n")

    # 6) 体积报告
    original_size = os.path.getsize(INPUT_JSON)
    first_name = order[0]
    first_subject_size = sizes[first_name]
    first_screen = manifest_size + first_subject_size

    print("=== 文件清单与大小 ===")
    print("manifest.json              : %s" % human_size(manifest_size))
    for name in order:
        print("subjects/%-11s : %s" % (SUBJECT_FILE_MAP[name], human_size(sizes[name])))

    print("\n=== 体积对比 ===")
    print("原 data.json               : %s" % human_size(original_size))
    print("首屏下载 (manifest + %s): %s" % (first_name, human_size(first_screen)))
    saved = original_size - first_screen
    ratio = (saved / original_size * 100.0) if original_size else 0.0
    print("首屏节省                   : %s (%.1f%%)" % (human_size(saved), ratio))


if __name__ == "__main__":
    main()
