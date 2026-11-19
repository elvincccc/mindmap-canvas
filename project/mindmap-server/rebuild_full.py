#!/usr/bin/env python3
"""从 baseline 完整 SUBJECTS 重建知识点树 + 导入全部真题。

层级映射: module→L1, type→L2, sub→L3, method→L4
清空 nodes/examples，按科目顺序重建。
"""
import json, sqlite3, os, uuid

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, 'mindmap.db')
SRC = '/tmp/baseline_subjects.json'

def nid():
    return uuid.uuid4().hex[:12]

def hit_val(v):
    return 1 if v is True else 0 if v is False else None

def main():
    data = json.load(open(SRC, encoding='utf-8'))
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    # 清空
    c.execute('DELETE FROM examples')
    c.execute('DELETE FROM nodes')
    c.execute('DELETE FROM subjects')

    total_nodes = total_ex = 0
    for si, (sname, sobj) in enumerate(data.items()):
        s = sobj['data']
        root = s['root']
        c.execute('INSERT INTO subjects VALUES(?,?,?,?,?)',
                  (sname, s.get('color', 'indigo'), root.get('name', sname),
                   root.get('signal', ''), si))

        modules = s.get('modules', {})

        def add_examples(node_id, examples):
            nonlocal total_ex
            for ei, ex in enumerate(examples or []):
                c.execute('''INSERT INTO examples(id,node_id,q,src,hit,ans,opts,solve,analysis,img,sort_order)
                             VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                          (nid(), node_id, ex.get('q', ''), ex.get('src', ''),
                           hit_val(ex.get('hit')), ex.get('ans', ''),
                           json.dumps(ex.get('opts', []), ensure_ascii=False) if ex.get('opts') else None,
                           ex.get('solve', ''), ex.get('analysis', ''), ex.get('img', ''), ei))
                total_ex += 1

        def add_node(n, level, parent_id, so, mod):
            nonlocal total_nodes
            ident = nid()
            name = n.get('name', '')
            star = 1 if n.get('star') else 0
            signal = n.get('signal', '') or ''
            c.execute('INSERT INTO nodes(id,subject_id,parent_id,name,level,star,signal,mod,sort_order) VALUES(?,?,?,?,?,?,?,?,?)',
                      (ident, sname, parent_id, name, level, star, signal, mod, so))
            total_nodes += 1
            add_examples(ident, n.get('examples', []))
            for ci, ch in enumerate(n.get('children', [])):
                add_node(ch, level + 1, ident, ci, mod)
            return ident

        for bi, t in enumerate(s.get('types', [])):
            mod_name = t.get('module') or t.get('name')
            mod_color = modules.get(mod_name, s.get('color', 'indigo'))
            add_node(t, 1, None, bi, mod_color)

        print(f"{sname}: 完成")

    conn.commit()
    print(f"\n总计: {total_nodes} 节点, {total_ex} 例题")
    for t in ['subjects', 'nodes', 'examples']:
        print(f"  {t}: {c.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]}")
    # 层级分布
    print("层级分布:", dict(c.execute('SELECT level,COUNT(*) FROM nodes GROUP BY level').fetchall()))
    conn.close()

if __name__ == '__main__':
    main()
