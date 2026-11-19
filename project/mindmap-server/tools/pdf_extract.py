#!/usr/bin/env python3
"""
试卷 PDF 题目提取器：按题号提取题干、选项、配图，输出结构化 JSON 供 AI 解题后入库。

用法：
  python3 pdf_extract.py <pdf路径> [--nums 3,5,7] [--out 提取结果.json] [--dump-all]

工作流程：
  1. 用 PyMuPDF 提取每页文本 + 内嵌图片
  2. 按"第N题 / N. / N、"等模式切分题目块
  3. 抽取指定题号（--nums）或列出全部题号（--dump-all）
  4. 输出 JSON：{题号: {q, opts, img, page, raw}}
  5. AI 读取后补全 ans/solve/analysis，再调用 ingest.py 入库
"""
import sys, os, re, json, argparse

try:
    import fitz  # PyMuPDF
except ImportError:
    sys.exit("需要 PyMuPDF: pip install pymupdf")

# 题号识别模式：匹配行首的 "第3题" "3." "3、" "3．" "（3）" 等
NUM_PATTERNS = [
    re.compile(r'^\s*第\s*(\d{1,3})\s*题'),
    re.compile(r'^\s*(\d{1,3})\s*[.．、]'),
    re.compile(r'^\s*[（(]\s*(\d{1,3})\s*[）)]'),
]

def detect_num(line):
    for pat in NUM_PATTERNS:
        m = pat.match(line)
        if m:
            return int(m.group(1))
    return None

def extract(pdf_path):
    doc = fitz.open(pdf_path)
    # 逐页收集带行号的文本
    pages = []
    for pi, page in enumerate(doc):
        text = page.get_text("text")
        pages.append((pi, text))
    # 合并全部文本，记录每个题号出现的行位置
    all_lines = []  # (page, lineno, text)
    for pi, text in pages:
        for li, line in enumerate(text.splitlines()):
            all_lines.append((pi, li, line))

    # 找题号边界
    marks = []  # (num, index_in_all_lines)
    for idx, (pi, li, line) in enumerate(all_lines):
        n = detect_num(line)
        if n and 1 <= n <= 300:
            marks.append((n, idx))
    # 去重：同一题号多次出现（跨页页眉）保留第一次，且要求递增
    seen = set(); clean = []
    for n, idx in marks:
        if n not in seen:
            seen.add(n); clean.append((n, idx))

    questions = {}
    for i, (num, start) in enumerate(clean):
        end = clean[i+1][1] if i+1 < len(clean) else len(all_lines)
        block_lines = all_lines[start:end]
        block = "\n".join(l[2] for l in block_lines)
        page = block_lines[0][0] + 1 if block_lines else 0
        q, opts = split_q_opts(block)
        questions[num] = {
            "num": num, "page": page,
            "q": q, "opts": opts,
            "raw": block[:2000]
        }
    doc.close()
    return questions

def split_q_opts(block):
    """把题目块拆成题干 + 选项。支持选项分行 或 行内多个(A. B. C. D.)两种排版。"""
    lines = [l.strip() for l in block.splitlines() if l.strip()]
    if not lines:
        return "", []
    first = lines[0]
    first = re.sub(r'^\s*(第\s*\d+\s*题|[\d]+[.．、]|[(（]\d+[)）])\s*', '', first).strip()
    q_lines = [first]
    opts = []

    # 行内多选项拆分：把 "A. xx B. xx C. xx" 切成 ["A. xx","B. xx",...]
    inline_pat = re.compile(r'([A-Da-d])\s*[.．、:：]\s*')
    # 题干第一行内若直接含选项标记（如 "3. 题干 A. xx B. xx"），就地拆分
    m0 = inline_pat.search(first)
    if m0:
        q_lines = [first[:m0.start()].strip()]
    def split_inline(line):
        parts = inline_pat.split(line)
        # parts = ['', 'A', ' A内容 ', 'B', ' B内容 ', ...]
        out = []
        for i in range(1, len(parts)-1, 2):
            letter, content = parts[i], parts[i+1].strip()
            out.append(f"{letter}. {content}")
        return out

    # 第一行内的选项
    if m0:
        opts.extend([p for p in split_inline(first[m0.start():]) if p])

    rest = "\n".join(lines[1:])
    # 判断是否有行内选项标记
    if inline_pat.search(rest):
        # 题干 = 选项标记之前的内容
        m = inline_pat.search(rest)
        q_tail = rest[:m.start()].strip()
        if q_tail: q_lines.append(q_tail)
        opts = [p for p in split_inline(rest[m.start():]) if p]
    else:
        # 逐行判断
        opt_start = False
        for line in lines[1:]:
            if re.match(r'^\s*[A-Da-d]\s*[.．、:：]', line):
                opt_start = True
            if opt_start:
                sub = split_inline(line)
                opts.extend(sub if sub else [line])
            else:
                q_lines.append(line)
    return "\n".join(q_lines).strip(), opts

def extract_images(pdf_path, out_dir, pages=None):
    """提取指定页（或全部页）的内嵌图片到 out_dir，返回路径列表"""
    os.makedirs(out_dir, exist_ok=True)
    doc = fitz.open(pdf_path)
    paths = []
    targets = pages if pages else range(len(doc))
    for pi in targets:
        if pi >= len(doc): continue
        page = doc[pi]
        for ii, img in enumerate(page.get_images(full=True)):
            xref = img[0]
            try:
                base = doc.extract_image(xref)
                ext = base["ext"]
                fn = f"p{pi+1}_x{xref}.{ext}"
                fp = os.path.join(out_dir, fn)
                with open(fp, "wb") as f:
                    f.write(base["image"])
                paths.append(fp)
            except Exception:
                pass
    doc.close()
    return paths

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--nums", help="逗号分隔的题号，如 3,5,7；不填则提取全部")
    ap.add_argument("--out", default="extracted.json", help="输出 JSON 路径")
    ap.add_argument("--dump-all", action="store_true", help="仅列出所有检测到的题号")
    ap.add_argument("--imgdir", help="提取内嵌图片到该目录")
    args = ap.parse_args()

    questions = extract(args.pdf)
    if args.dump_all:
        print("检测到的题号:", sorted(questions.keys()))
        for n in sorted(questions):
            print(f"  第{n}题 (p{questions[n]['page']}): {questions[n]['q'][:50]}")
        return

    if args.imgdir:
        imgs = extract_images(args.pdf, args.imgdir)
        print(f"提取图片 {len(imgs)} 张到 {args.imgdir}")

    if args.nums:
        nums = [int(x) for x in re.findall(r'\d+', args.nums)]
        selected = {n: questions[n] for n in nums if n in questions}
        missing = [n for n in nums if n not in questions]
        if missing: print("未找到题号:", missing)
    else:
        selected = questions

    json.dump(selected, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"已提取 {len(selected)} 道题到 {args.out}")
    for n, d in sorted(selected.items()):
        print(f"  第{n}题(p{d['page']}): {d['q'][:60]} | 选项{len(d['opts'])}")

if __name__ == "__main__":
    main()
