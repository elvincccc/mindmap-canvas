#!/usr/bin/env python3
"""
题目入库脚本：把结构化题目（AI 已补全 ans/solve/analysis）写入后端数据库。

用法：
  # 批量导入 JSON 文件（数组，每题含 node_id/subject/q/src/ans/opts/solve/analysis/img/hit）
  python3 ingest.py --file questions.json

  # 单题快速入库
  python3 ingest.py --subject 判断推理 --node-id xxx --q "题干" --src "2026省考 第3题" \
      --ans B --opts '["A.甲","B.乙"]' --solve "解法" --analysis "解析" --img ""

  # 从之前提取的 full_examples.json 按题源匹配 node_id 批量导入
  python3 ingest.py --full-examples /tmp/full_examples.json --map src_to_node.json

环境变量 API_BASE 可指定后端地址，默认 http://127.0.0.1:8800
"""
import sys, os, json, argparse, urllib.request, urllib.parse

API_BASE = os.environ.get("API_BASE", "http://127.0.0.1:8800")

def api(path, method="GET", body=None):
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    req = urllib.request.Request(API_BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)

def find_node_id(subject, name):
    """按节点名找 id（精确或包含匹配）"""
    nodes = api("/api/nodes?subject=" + urllib.parse.quote(subject))
    for n in nodes:
        if n["name"] == name:
            return n["id"]
    for n in nodes:
        if name in n["name"] or n["name"] in name:
            return n["id"]
    return None

def ingest_one(item):
    node_id = item.get("node_id")
    if not node_id and item.get("subject") and item.get("node_name"):
        node_id = find_node_id(item["subject"], item["node_name"])
    if not node_id:
        return False, "无 node_id 且无法按名称匹配"
    body = {
        "q": item.get("q", ""), "src": item.get("src", ""),
        "hit": item.get("hit"), "ans": item.get("ans", ""),
        "opts": item.get("opts", []), "solve": item.get("solve", ""),
        "analysis": item.get("analysis", ""), "img": item.get("img", "")
    }
    try:
        api("/api/examples?node_id=" + node_id, "POST", body)
        return True, "ok"
    except Exception as e:
        return False, str(e)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", help="批量 JSON 文件（数组）")
    ap.add_argument("--subject")
    ap.add_argument("--node-id")
    ap.add_argument("--node-name")
    ap.add_argument("--q")
    ap.add_argument("--src")
    ap.add_argument("--ans")
    ap.add_argument("--opts", help="JSON 数组字符串")
    ap.add_argument("--solve", default="")
    ap.add_argument("--analysis", default="")
    ap.add_argument("--img", default="")
    ap.add_argument("--hit", choices=["true", "false", "none"], default="none")
    args = ap.parse_args()

    hit = {"true": True, "false": False, "none": None}[args.hit]

    if args.file:
        items = json.load(open(args.file, encoding="utf-8"))
        ok = fail = 0
        for it in items:
            good, msg = ingest_one(it)
            if good: ok += 1
            else:
                fail += 1
                print(f"  FAIL {it.get('src','?')}: {msg}")
        print(f"批量导入完成: 成功 {ok}, 失败 {fail}")
    else:
        item = {
            "node_id": args.node_id, "subject": args.subject, "node_name": args.node_name,
            "q": args.q, "src": args.src, "ans": args.ans,
            "opts": json.loads(args.opts) if args.opts else [],
            "solve": args.solve, "analysis": args.analysis, "img": args.img, "hit": hit
        }
        good, msg = ingest_one(item)
        print("入库成功" if good else f"入库失败: {msg}")

if __name__ == "__main__":
    main()
