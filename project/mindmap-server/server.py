#!/usr/bin/env python3
"""思维导图真题数据管理 API (FastAPI + SQLite)"""
import json, os, sqlite3, uuid
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, 'mindmap.db')

app = FastAPI(title="思维导图数据管理 API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

# ---------- 数据模型 ----------
class ExampleIn(BaseModel):
    q: str = ""
    src: str = ""
    hit: Optional[bool] = None
    ans: str = ""
    opts: list = []
    solve: str = ""
    analysis: str = ""
    img: str = ""
    steps: list = []
    exclude: list = []

class NodeIn(BaseModel):
    name: str
    level: int = 3
    parent_id: Optional[str] = None
    star: bool = False
    signal: str = ""

class SubjectIn(BaseModel):
    name: str
    color: str = "indigo"
    root_name: str = ""
    root_signal: str = ""

# ---------- 静态页面 ----------
@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, 'admin.html'))

@app.get("/canvas")
def canvas():
    return FileResponse(os.path.join(BASE, 'canvas.html'))

# ---------- 读：组装成前端可用的树 ----------
@app.get("/api/tree")
def get_tree():
    conn = db(); c = conn.cursor()
    subjects_rows = c.execute("SELECT * FROM subjects ORDER BY sort_order").fetchall()
    nodes = c.execute("SELECT * FROM nodes ORDER BY sort_order").fetchall()
    examples = c.execute("SELECT * FROM examples ORDER BY sort_order").fetchall()

    # 按 node_id 归集例题
    ex_by_node = {}
    for e in examples:
        ex_by_node.setdefault(e['node_id'], []).append({
            'q': e['q'], 'src': e['src'],
            'hit': (True if e['hit']==1 else False if e['hit']==0 else None),
            'ans': e['ans'] or '',
            'opts': json.loads(e['opts']) if e['opts'] else [],
            'solve': e['solve'] or '', 'analysis': e['analysis'] or '', 'img': e['img'] or '',
            'steps': json.loads(e['steps']) if 'steps' in e.keys() and e['steps'] else [],
            'exclude': json.loads(e['exclude']) if 'exclude' in e.keys() and e['exclude'] else []
        })

    # 按 subject 分组节点
    nodes_by_subject = {}
    for n in nodes:
        nodes_by_subject.setdefault(n['subject_id'], []).append(n)

    subjects_out = {}
    order = []
    for s in subjects_rows:
        order.append(s['id'])
        snodes = nodes_by_subject.get(s['id'], [])
        by_id = {n['id']: n for n in snodes}
        children_of = {}
        for n in snodes:
            children_of.setdefault(n['parent_id'], []).append(n)

        def build(n):
            d = {'name': n['name'], 'star': bool(n['star']),
                 '__id': n['id'], '__level': n['level']}
            kids = children_of.get(n['id'], [])
            if kids:
                d['children'] = [build(k) for k in kids]
            exs = ex_by_node.get(n['id'], [])
            if exs:
                d['examples'] = exs
            return d

        branches = [build(n) for n in children_of.get(None, [])]
        # modules 配色：从分支 mod 字段重建
        modules = {}
        for n in snodes:
            if n['level']==1 and n['mod']:
                modules[n['name']] = n['mod']
        subjects_out[s['id']] = {
            'color': s['color'],
            'modules': modules,
            'root': {'name': s['root_name'], 'signal': s['root_signal']},
            'branches': branches
        }
    conn.close()
    return {'order': order, 'subjects': subjects_out}

# ---------- 科目 ----------
@app.get("/api/subjects")
def list_subjects():
    conn=db(); rows=conn.execute("SELECT * FROM subjects ORDER BY sort_order").fetchall(); conn.close()
    return [dict(r) for r in rows]

@app.post("/api/subjects", status_code=201)
def create_subject(s: SubjectIn):
    conn=db(); c=conn.cursor()
    so=c.execute("SELECT COALESCE(MAX(sort_order),0)+1 FROM subjects").fetchone()[0]
    try:
        c.execute("INSERT INTO subjects VALUES(?,?,?,?,?)",
                  (s.name, s.color, s.root_name or s.name, s.root_signal, so))
    except sqlite3.IntegrityError:
        conn.close(); raise HTTPException(400, "科目已存在")
    conn.commit(); conn.close()
    return {"ok": True, "name": s.name}

@app.put("/api/subjects/{name}")
def update_subject(name: str, s: SubjectIn):
    conn=db(); c=conn.cursor()
    c.execute("UPDATE subjects SET color=?,root_name=?,root_signal=? WHERE id=?",
              (s.color, s.root_name or name, s.root_signal, name))
    if c.rowcount==0: conn.close(); raise HTTPException(404,"科目不存在")
    conn.commit(); conn.close(); return {"ok": True}

@app.delete("/api/subjects/{name}")
def delete_subject(name: str):
    conn=db(); c=conn.cursor()
    ids=[r[0] for r in c.execute("SELECT id FROM nodes WHERE subject_id=?",(name,)).fetchall()]
    for nid in ids: c.execute("DELETE FROM examples WHERE node_id=?",(nid,))
    c.execute("DELETE FROM nodes WHERE subject_id=?",(name,))
    c.execute("DELETE FROM subjects WHERE id=?",(name,))
    conn.commit(); conn.close(); return {"ok": True}

# ---------- 节点 ----------
@app.get("/api/nodes")
def list_nodes(subject: Optional[str]=None):
    conn=db()
    if subject:
        rows=conn.execute("SELECT * FROM nodes WHERE subject_id=? ORDER BY level,sort_order",(subject,)).fetchall()
    else:
        rows=conn.execute("SELECT * FROM nodes ORDER BY subject_id,level,sort_order").fetchall()
    conn.close(); return [dict(r) for r in rows]

@app.post("/api/nodes", status_code=201)
def create_node(n: NodeIn, subject: str):
    conn=db(); c=conn.cursor()
    so=c.execute("SELECT COALESCE(MAX(sort_order),0)+1 FROM nodes WHERE parent_id IS ?",
                 (n.parent_id,)).fetchone()[0]
    ident=uuid.uuid4().hex[:12]
    mod=None
    if n.parent_id:
        p=c.execute("SELECT mod FROM nodes WHERE id=?",(n.parent_id,)).fetchone()
        mod=p['mod'] if p else None
    c.execute("INSERT INTO nodes VALUES(?,?,?,?,?,?,?,?,?)",
              (ident, subject, n.parent_id, n.name, n.level, 1 if n.star else 0, n.signal, mod, so))
    conn.commit(); conn.close(); return {"ok": True, "id": ident}

@app.put("/api/nodes/{ident}")
def update_node(ident: str, n: NodeIn):
    conn=db(); c=conn.cursor()
    c.execute("UPDATE nodes SET name=?,star=?,signal=? WHERE id=?",
              (n.name, 1 if n.star else 0, n.signal, ident))
    if c.rowcount==0: conn.close(); raise HTTPException(404,"节点不存在")
    conn.commit(); conn.close(); return {"ok": True}

@app.delete("/api/nodes/{ident}")
def delete_node(ident: str):
    conn=db(); c=conn.cursor()
    # 递归删除子节点及其例题
    def rm(nid):
        for child in c.execute("SELECT id FROM nodes WHERE parent_id=?",(nid,)).fetchall():
            rm(child['id'])
        c.execute("DELETE FROM examples WHERE node_id=?",(nid,))
        c.execute("DELETE FROM nodes WHERE id=?",(nid,))
    rm(ident)
    conn.commit(); conn.close(); return {"ok": True}

# ---------- 例题 ----------
@app.get("/api/examples")
def list_examples(node_id: Optional[str]=None):
    conn=db()
    if node_id:
        rows=conn.execute("SELECT * FROM examples WHERE node_id=? ORDER BY sort_order",(node_id,)).fetchall()
    else:
        rows=conn.execute("SELECT * FROM examples ORDER BY node_id,sort_order").fetchall()
    conn.close()
    out=[]
    for r in rows:
        d=dict(r)
        d['hit']=(True if d['hit']==1 else False if d['hit']==0 else None)
        d['opts']=json.loads(d['opts']) if d['opts'] else []
        out.append(d)
    return out

@app.post("/api/examples", status_code=201)
def create_example(node_id: str, e: ExampleIn):
    conn=db(); c=conn.cursor()
    if not c.execute("SELECT 1 FROM nodes WHERE id=?",(node_id,)).fetchone():
        conn.close(); raise HTTPException(404,"节点不存在")
    so=c.execute("SELECT COALESCE(MAX(sort_order),0)+1 FROM examples WHERE node_id=?",(node_id,)).fetchone()[0]
    ident=uuid.uuid4().hex[:12]
    c.execute('''INSERT INTO examples(id,node_id,q,src,hit,ans,opts,solve,analysis,img,steps,exclude,sort_order)
                 VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',
              (ident, node_id, e.q, e.src, 1 if e.hit is True else 0 if e.hit is False else None,
               e.ans, json.dumps(e.opts,ensure_ascii=False), e.solve, e.analysis, e.img,
               json.dumps(e.steps,ensure_ascii=False) if e.steps else None,
               json.dumps(e.exclude,ensure_ascii=False) if e.exclude else None, so))
    conn.commit(); conn.close(); return {"ok": True, "id": ident}

@app.put("/api/examples/{ident}")
def update_example(ident: str, e: ExampleIn):
    conn=db(); c=conn.cursor()
    c.execute('''UPDATE examples SET q=?,src=?,hit=?,ans=?,opts=?,solve=?,analysis=?,img=?,steps=?,exclude=? WHERE id=?''',
              (e.q, e.src, 1 if e.hit is True else 0 if e.hit is False else None,
               e.ans, json.dumps(e.opts,ensure_ascii=False), e.solve, e.analysis, e.img,
               json.dumps(e.steps,ensure_ascii=False) if e.steps else None,
               json.dumps(e.exclude,ensure_ascii=False) if e.exclude else None, ident))
    if c.rowcount==0: conn.close(); raise HTTPException(404,"例题不存在")
    conn.commit(); conn.close(); return {"ok": True}

@app.delete("/api/examples/{ident}")
def delete_example(ident: str):
    conn=db(); c=conn.cursor()
    c.execute("DELETE FROM examples WHERE id=?",(ident,))
    conn.commit(); conn.close(); return {"ok": True}

# ---------- 统计 ----------
@app.get("/api/stats")
def stats():
    conn=db(); c=conn.cursor()
    out={
        'subjects': c.execute("SELECT COUNT(*) FROM subjects").fetchone()[0],
        'nodes': c.execute("SELECT COUNT(*) FROM nodes").fetchone()[0],
        'examples': c.execute("SELECT COUNT(*) FROM examples").fetchone()[0],
        'with_img': c.execute("SELECT COUNT(*) FROM examples WHERE img!=''").fetchone()[0],
        'real': c.execute("SELECT COUNT(*) FROM examples WHERE src NOT LIKE '%季%'").fetchone()[0],
        'mock': c.execute("SELECT COUNT(*) FROM examples WHERE src LIKE '%季%'").fetchone()[0],
    }
    conn.close(); return out
