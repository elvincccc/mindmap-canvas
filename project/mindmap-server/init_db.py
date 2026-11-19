#!/usr/bin/env python3
"""把 data.json 的嵌套数据导入 SQLite 关系表。"""
import json, sqlite3, os, uuid

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, 'data.json')
DB = os.path.join(BASE, 'mindmap.db')

def nid():
    return uuid.uuid4().hex[:12]

def init():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.executescript('''
    DROP TABLE IF EXISTS examples;
    DROP TABLE IF EXISTS nodes;
    DROP TABLE IF EXISTS subjects;

    CREATE TABLE subjects (
        id TEXT PRIMARY KEY,
        color TEXT,
        root_name TEXT,
        root_signal TEXT,
        sort_order INTEGER
    );
    CREATE TABLE nodes (
        id TEXT PRIMARY KEY,
        subject_id TEXT NOT NULL,
        parent_id TEXT,
        name TEXT NOT NULL,
        level INTEGER NOT NULL,        -- 1=分支 2=子类 3=方法
        star INTEGER DEFAULT 0,
        signal TEXT,
        mod TEXT,
        sort_order INTEGER,
        FOREIGN KEY(subject_id) REFERENCES subjects(id)
    );
    CREATE TABLE examples (
        id TEXT PRIMARY KEY,
        node_id TEXT NOT NULL,
        q TEXT,
        src TEXT,
        hit INTEGER,                   -- 1=做对 0=做错 NULL=未标
        ans TEXT,
        opts TEXT,                     -- JSON 数组字符串
        solve TEXT,
        analysis TEXT,
        img TEXT,
        sort_order INTEGER,
        FOREIGN KEY(node_id) REFERENCES nodes(id)
    );
    CREATE INDEX idx_nodes_subject ON nodes(subject_id);
    CREATE INDEX idx_nodes_parent ON nodes(parent_id);
    CREATE INDEX idx_examples_node ON examples(node_id);
    ''')

    data = json.load(open(DATA, encoding='utf-8'))
    subjects = data['subjects']
    order = data.get('order', list(subjects.keys()))

    for si, sname in enumerate(order):
        s = subjects[sname]
        c.execute('INSERT INTO subjects VALUES(?,?,?,?,?)',
                  (sname, s.get('color',''), s['root']['name'], s['root'].get('signal',''), si))

        # 递归插入节点：branch(level1) -> children(level2) -> 其 children(level3)
        def add_node(name, level, parent_id, star, signal, mod, so):
            ident = nid()
            c.execute('INSERT INTO nodes(id,subject_id,parent_id,name,level,star,signal,mod,sort_order) VALUES(?,?,?,?,?,?,?,?,?)',
                      (ident, sname, parent_id, name, level, 1 if star else 0, signal, mod, so))
            return ident

        def add_example(node_id, ex, so):
            hit = ex.get('hit')
            c.execute('''INSERT INTO examples(id,node_id,q,src,hit,ans,opts,solve,analysis,img,sort_order)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                      (nid(), node_id, ex.get('q',''), ex.get('src',''),
                       1 if hit is True else (0 if hit is False else None),
                       ex.get('ans',''),
                       json.dumps(ex.get('opts',[]), ensure_ascii=False) if ex.get('opts') else None,
                       ex.get('solve',''), ex.get('analysis',''), ex.get('img',''), so))

        for bi, b in enumerate(s.get('branches', [])):
            bname = b['name']
            bid = add_node(bname, 1, None, b.get('star', False), None, bname, bi)
            for ci, child in enumerate(b.get('children', [])):
                cname = child['name'] if isinstance(child, dict) else child
                cstar = child.get('star', False) if isinstance(child, dict) else False
                cid = add_node(cname, 2, bid, cstar, None, bname, ci)
                grandchildren = child.get('children', []) if isinstance(child, dict) else []
                for gi, g in enumerate(grandchildren):
                    gname = g.get('name', g) if isinstance(g, dict) else g
                    gstar = g.get('star', False) if isinstance(g, dict) else False
                    gid = add_node(gname, 3, cid, gstar, None, bname, gi)
                    # 例题挂到 level3 节点（若 grandchildren 为空则挂 level2）
                    examples = g.get('examples', []) if isinstance(g, dict) else []
                    for ei, ex in enumerate(examples):
                        add_example(gid, ex, ei)
                # 若 level2 直接带例题（无 grandchildren）
                direct_ex = child.get('examples', []) if isinstance(child, dict) else []
                if direct_ex and not grandchildren:
                    for ei, ex in enumerate(direct_ex):
                        add_example(cid, ex, ei)
            # 分支自身例题
            for ei, ex in enumerate(b.get('examples', [])):
                add_example(bid, ex, ei)

    conn.commit()
    # 统计
    for t in ['subjects','nodes','examples']:
        print(f"{t}: {c.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]}")
    conn.close()
    print(f"数据库已生成: {DB}")

if __name__ == '__main__':
    init()
