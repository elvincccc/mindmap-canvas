#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ingest_v2.py —— 试卷错题录入 v2（hit 自动派生，杜绝手填）

设计原则（针对历史踩坑）：
  1. hit 唯一来源是 PDF 的「正确答案 vs 你的答案」：set(正确)==set(你的) → 做对
     —— 不再有 --hit 手填，从根上杜绝「第71题填反」的雷。
  2. 幂等：按 src 去重，重复跑不产生重复题。
   3. 数据摆放正确：以 mindmap-demo/data.json（含全部样板）为基准合并，
      同时覆盖 server/data.json + demo/data.json + 对应分科文件（data.js 已废弃），
     再跑 split_data.py —— 杜绝「样板只在 demo 被冲掉」。
  4. 先校验后部署：ans 与 solution.answer 一致、hit 与派生值一致、
     validate_v2 结构全 PASS，通过后才能 --deploy。

────────────────────────────── 用法 ──────────────────────────────
# 步骤1：从 PDF 解析权威答案对（含自动 hit），输出 answers.json
python3 tools/ingest_v2.py derive-answers \
    --pdf /root/uploads/xxx.pdf --out /tmp/answers.json

# 步骤2：AI 只写题目内容 + solution（不写 ans/hit），存 questions.json
#   格式见脚本底部 EXAMPLE_QUESTIONS

# 步骤3：预览（不写任何文件）
python3 tools/ingest_v2.py ingest \
    --questions questions.json --answers /tmp/answers.json --dry-run

# 步骤3b：确认后正式入库（写4处 + split；不加 --deploy 则不推送线上）
python3 tools/ingest_v2.py ingest \
    --questions questions.json --answers /tmp/answers.json

# 步骤3c：入库 + 原子部署 + 等 Pages
python3 tools/ingest_v2.py ingest \
    --questions questions.json --answers /tmp/answers.json --deploy
"""
import sys, os, re, json, argparse, subprocess, hashlib
from datetime import datetime

SERVER = '/workspace/mindmap-server'
DEMO = '/workspace/mindmap-demo'
DATA_SERVER = os.path.join(SERVER, 'data.json')
DATA_DEMO = os.path.join(DEMO, 'data.json')

SUBJ_FILE = {'判断推理':'p1.json','常识应用':'p2.json','数量关系':'p3.json',
             '言语理解':'p4.json','资料分析':'p5.json'}

# 校验口径与 tools/validate_v2.py 保持一致（2026-11-19 更新）
# error.type 开放填写，仅查非空；词表仅作参考，不再拦截
# 字数区间：(下限(不含), 上限(含))；action≤12 / why 20~35 / detail 40~55
# 边界容差 TOLERANCE=5：多写或少写 1~5 字一律放行（实际放行 why 15~40、detail 35~60）
TOLERANCE = 5
STEP_LIMITS = {"action": (None, 12), "why": (20, 35), "detail": (40, 55)}


# ─────────────────────── helpers ───────────────────────
def iter_all(o):
    if isinstance(o, dict):
        yield o
        for v in o.values():
            yield from iter_all(v)
    elif isinstance(o, list):
        for v in o:
            yield from iter_all(v)

def find_node(root, name):
    """按节点名精确/包含匹配，返回第一个命中的节点对象。"""
    exact = None
    loose = None
    for o in iter_all(root):
        nm = o.get('name')
        if not nm or 'examples' not in o and 'children' not in o:
            continue
        if nm == name and exact is None:
            exact = o
        elif name in nm and loose is None:
            loose = o
    return exact or loose

def load_json_with_js(path):
    raw = open(path, encoding='utf-8').read()
    if path.endswith('data.js'):
        prefix = 'window.MM_DATA = '
        body = raw[len(prefix):].strip() if raw.startswith(prefix) else raw.strip()
        if body.endswith(';'): body = body[:-1]
        return json.loads(body), prefix
    return json.loads(raw), None

def dump_json(path, data, prefix=None):
    kw = dict(ensure_ascii=False, separators=(',', ':'))
    with open(path, 'w', encoding='utf-8') as f:
        if prefix:
            f.write(prefix); json.dump(data, f, **kw); f.write(';')
        else:
            json.dump(data, f, **kw)


# ─────────────────────── derive-answers ───────────────────────
def cmd_derive_answers(args):
    """从 PDF 全文正则解析「正确答案/你的答案」，自动派生 hit。"""
    try:
        import fitz
    except ImportError:
        sys.exit("需要 PyMuPDF: pip install pymupdf")
    doc = fitz.open(args.pdf)
    lines = []
    for page in doc:
        lines.extend(page.get_text('text').splitlines())
    doc.close()

    # 粉笔版 PDF 的「答案总表前置」：题号、正确答案、你的答案分别在文档的
    # 三个有序序列里（题号区在后、答案区在前），必须「按出现顺序 zip」配对，
    # 绝不能用「遇到答案行时 cur 停留在哪个题号」——那样只有答案区前的 23 题能配对。
    num_re = re.compile(r'\s*(\d{1,3})\s*[.．、]?\s*$')          # 独立题号行，如 "71."
    cor_re = re.compile(r'正确答案\s*[:：]\s*([A-Da-d]+)')
    my_re  = re.compile(r'你的答案\s*[:：]\s*([A-Da-d]+)')
    nums = [int(num_re.match(l).group(1)) for l in lines
            if num_re.match(l) and 1 <= int(num_re.match(l).group(1)) <= 300]
    corrects = [cor_re.search(l).group(1).upper() for l in lines if cor_re.search(l)]
    mines = [my_re.search(l).group(1).upper() for l in lines if my_re.search(l)]

    result = {}
    ambiguous = []
    if not (len(nums) == len(corrects) == len(mines)):
        ambiguous.append({'num':0, 'reason':
            '三序列长度不等(题号%d/正确%d/你的%d)，配对可能错位，请人工核对'
            % (len(nums), len(corrects), len(mines))})
    for num, c, m in zip(nums, corrects, mines):
        hit = (set(c) == set(m))
        result[str(num)] = {'correct':c, 'mine':m, 'hit':hit}

    out = {
        'pdf': os.path.basename(args.pdf),
        'generated': datetime.now().isoformat(timespec='seconds'),
        'total': len(result),
        'wrong_count': sum(1 for v in result.values() if not v['hit']),
        'answers': result,
        'ambiguous': ambiguous,
    }
    json.dump(out, open(args.out,'w',encoding='utf-8'), ensure_ascii=False, indent=2)
    print('解析答案对: %d 题 | 做对 %d | 做错 %d | 歧义 %d' % (
        len(result), len(result)-out['wrong_count'], out['wrong_count'], len(ambiguous)))
    if ambiguous:
        print('⚠ 以下题号答案对不完整，需人工核对（跨页/多选格式可能丢失）:')
        for a in ambiguous:
            print('   第%d题: %s' % (a['num'], a['reason']))
    print('已写出:', args.out)
    return 0


# ─────────────────────── validate solution ───────────────────────
def validate_question(q, ans, hit, derived_hit):
    """返回 (errors, warnings)。校验答案一致性 + v2 结构。"""
    errs, warns = [], []
    sol = q.get('solution')
    if not isinstance(sol, dict):
        errs.append('缺少 solution'); return errs, warns
    if str(sol.get('answer','')).upper() != str(ans).upper():
        errs.append('solution.answer(%s) != 派生ans(%s)' % (sol.get('answer'), ans))
    if hit != derived_hit:
        errs.append('题目hit(%s) != 派生hit(%s)' % (hit, derived_hit))
    ol = sol.get('oneLiner','')
    if not ol: errs.append('oneLiner缺失')
    elif len(ol) > 35 + TOLERANCE: errs.append('oneLiner超%d字(%d)' % (35+TOLERANCE, len(ol)))
    steps = sol.get('steps')
    if not isinstance(steps, list): errs.append('steps缺失')
    else:
        ns = [s.get('n') for s in steps]
        if ns and ns != list(range(1,len(steps)+1)): errs.append('steps.n非连续')
        if sum(1 for s in steps if s.get('key')) > 1: errs.append('多个key:true')
        for s in steps:
            for f,(lo,hi) in STEP_LIMITS.items():
                v = s.get(f)
                if not v: errs.append('steps[%s]缺%s' % (s.get('n'),f))
                else:
                    if lo is not None and len(v) < lo - TOLERANCE: errs.append('steps[%s].%s不足(需≥%d,实际%d)'%(s.get('n'),f,lo-TOLERANCE,len(v)))
                    if len(v) > hi + TOLERANCE: errs.append('steps[%s].%s超%d字(%d)'%(s.get('n'),f,hi+TOLERANCE,len(v)))
    # errors 只错项
    errL = {str(e.get('o','')).strip().upper() for e in sol.get('errors',[])}
    expect = {str(o).strip()[:1].upper() for o in q.get('opts',[]) if o} - {str(ans).upper()}
    if errL != expect:
        errs.append('errors字母%s != 期望%s' % (sorted(errL), sorted(expect)))
    for e in sol.get('errors',[]):
        t,w = e.get('type'), e.get('why')
        if not t: errs.append('选项%s缺type'%e.get('o'))
        # type 开放填写，不再校验词表
        if not w: errs.append('选项%s缺why'%e.get('o'))
        elif len(w) > 30 + TOLERANCE: errs.append('选项%s why超%d字(%d)'%(e.get('o'),30+TOLERANCE,len(w)))
    ins = sol.get('insight')
    if not isinstance(ins, dict): errs.append('insight非对象')
    else:
        st = ins.get('strategy')
        if not isinstance(st, dict): errs.append('insight.strategy缺失')
        else:
            for f in ('shouldDo','bestWay','timeCost','traps'):
                if not st.get(f): warns.append('strategy.%s缺失'%f)
    return errs, warns


# ─────────────────────── ingest ───────────────────────
def cmd_ingest(args):
    qdoc = json.load(open(args.questions, encoding='utf-8'))
    adoc = json.load(open(args.answers, encoding='utf-8'))
    answers = adoc['answers']
    vol = qdoc['vol']
    subject = qdoc['subject']
    node_name = qdoc['node']
    questions = qdoc['questions']

    if subject not in SUBJ_FILE:
        sys.exit('未知科目: %s（可选 %s）' % (subject, list(SUBJ_FILE)))

    # 1) 派生 ans / hit / src，并校验
    prepared = []
    fatal = False
    print('=== 派生 ans / hit（hit 来自PDF答案对）===')
    for q in questions:
        num = str(q['num'])
        src = '%s 第%s题' % (vol, num)
        if num not in answers:
            print('  [FAIL] %s: answers.json 无此题答案对（可能被标为歧义，需人工核对）'%src)
            fatal = True; continue
        a = answers[num]
        ans, hit = a['correct'], a['hit']
        errs, warns = validate_question(q, ans, hit, hit)
        if errs:
            print('  [FAIL] %s: ans=%s hit=%s | %s' % (src, ans, hit, '; '.join(errs)))
            fatal = True
        else:
            print('  [PASS] %s: 正确=%s 你的=%s → ans=%s hit=%s%s' % (
                src, a['correct'], a['mine'], ans, '做对' if hit else '做错',
                '  (另: '+', '.join(warns)+')' if warns else ''))
        prepared.append((src, num, ans, hit, q))
    if fatal:
        print('\n存在校验失败，已中止（未写入任何文件）。')
        return 1

    # 2) 以 demo 完整对象为基准合并（防样板被冲）
    base, _ = load_json_with_js(DATA_DEMO)
    subject_obj = base['subjects'][subject]
    target = find_node(subject_obj, node_name)
    if target is None:
        sys.exit('未找到节点: %s / %s' % (subject, node_name))
    print('\n=== 挂载节点: %s > %s ===' % (subject, node_name))

    changed = 0
    for src, num, ans, hit, q in prepared:
        exs = target.setdefault('examples', [])
        exs[:] = [e for e in exs if e.get('src') != src]   # 幂等去重
        ex = {
            'q': q.get('q',''), 'src': src, 'hit': hit, 'ans': ans,
            'opts': q.get('opts',[]),
            'solve': q.get('solve',''), 'analysis': q.get('analysis',''),
            'steps': q.get('steps',[]), 'exclude': q.get('exclude',[]),
            'solution': q['solution'],
        }
        if q.get('img'): ex['img'] = q['img']
        exs.append(ex)
        changed += 1
        print('  + %s (hit=%s)' % (src, hit))

    if args.dry_run:
        print('\n[DRY-RUN] 未写入任何文件。预览: 将新增/更新 %d 道题到 %s/%s' % (
            changed, subject, node_name))
        return 0

    # 3) 覆盖 3 处 + split
    print('\n=== 写入 3 处数据 ===')
    dump_json(DATA_DEMO, base)
    dump_json(DATA_SERVER, base)
    p5 = os.path.join(DEMO, 'data', 'subjects', SUBJ_FILE[subject])
    dump_json(p5, subject_obj)
    for p in (DATA_SERVER, DATA_DEMO, p5):
        print('  written', os.path.basename(p), os.path.getsize(p), 'bytes')

    # 4) split（会重新生成 manifest + 全部分科，含样板）
    print('\n=== split_data.py ===')
    r = subprocess.run([sys.executable, os.path.join(SERVER,'tools','split_data.py')],
                       capture_output=True, text=True)
    print(r.stdout[-800:])
    if r.returncode != 0:
        print('split 失败:', r.stderr); return 1

    # 5) validate_v2 全量
    print('\n=== validate_v2 全量 ===')
    r = subprocess.run([sys.executable, os.path.join(SERVER,'tools','validate_v2.py'), DATA_SERVER],
                       capture_output=True, text=True)
    tail = '\n'.join(r.stdout.strip().splitlines()[-3:])
    print(tail)
    if r.returncode != 0:
        print('v2 校验失败，已写入数据但未部署，请检查。'); return 1

    # 6) 对账：全量 solution 数 + 每科分布
    print('\n=== 数据对账 ===')
    total = sum(1 for o in iter_all(base) if 'solution' in o)
    print('  全量 solution 数:', total)
    for subj, fn in SUBJ_FILE.items():
        fp = os.path.join(DEMO,'data','subjects',fn)
        sd = json.load(open(fp,encoding='utf-8'))
        print('  %s(%s): %d' % (subj, fn, sum(1 for o in iter_all(sd) if 'solution' in o)))

    # 7) 可选部署
    if args.deploy:
        files = ['data.json','data/manifest.json',
                 'data/subjects/p1.json','data/subjects/p2.json',
                 'data/subjects/p3.json','data/subjects/p4.json','data/subjects/p5.json']
        print('\n=== 原子部署 ===')
        msg = 'feat: 录入%s（%s，%d题，hit自动派生）' % (vol, subject, changed)
        cmd = [sys.executable, os.path.join(SERVER,'tools','gh_upload_atomic.py'),
               DEMO] + files + ['--message', msg]
        r = subprocess.run(cmd, capture_output=True, text=True)
        print(r.stdout[-600:])
        if r.returncode != 0:
            print('部署失败:', r.stderr); return 1
    else:
        print('\n（未指定 --deploy，未推送线上。确认后加 --deploy 重跑或直接部署。）')

    print('\n完成: %d 道题已入库%s。' % (changed, '并部署' if args.deploy else ''))
    return 0


EXAMPLE_QUESTIONS = r'''
{
  "vol": "2025广东省考真题",
  "subject": "资料分析",
  "node": "累计求当期：当期值=本期累计−上期累计",
  "questions": [
    {
      "num": 71,
      "q": "2023年1~11月，G省社会消费品零售额约为（　　）万亿元。",
      "opts": ["A.4.34","B.4.43","C.4.54","D.4.63"],
      "img": "https://alibbxtbox.oss-cn-guangzhou.aliyuncs.com/mm5/q71/material_xxx.png",
      "solve": "旧字段解法（可选）",
      "analysis": "旧字段解析（可选）",
      "steps": [], "exclude": [],
      "solution": {
        "answer": "A",
        "oneLiner": "累计减12月：47494.86−4055.97≈4.34万亿元",
        "steps": [{"n":1,"action":"...","why":"...","detail":"..."}],
        "errors": [{"o":"B","type":"计算错误","why":"..."}],
        "insight": {"signal":"...","essence":"...","formula":[],"pitfalls":[],
                    "strategy":{"shouldDo":"必做","bestWay":"...","timeCost":"约45秒","traps":"..."}}
      }
    }
  ]
}
'''


def main():
    ap = argparse.ArgumentParser(description='试卷错题录入 v2（hit 自动派生）')
    sub = ap.add_subparsers(dest='cmd')

    p1 = sub.add_parser('derive-answers', help='从PDF解析答案对并派生hit')
    p1.add_argument('--pdf', required=True)
    p1.add_argument('--out', required=True)
    p1.set_defaults(fn=cmd_derive_answers)

    p2 = sub.add_parser('ingest', help='录入题目（自动派生ans/hit）')
    p2.add_argument('--questions', required=True)
    p2.add_argument('--answers', required=True)
    p2.add_argument('--dry-run', action='store_true')
    p2.add_argument('--deploy', action='store_true')
    p2.set_defaults(fn=cmd_ingest)

    args = ap.parse_args()
    if not hasattr(args, 'fn'):
        ap.print_help(); return 0
    return args.fn(args)

if __name__ == '__main__':
    sys.exit(main())
