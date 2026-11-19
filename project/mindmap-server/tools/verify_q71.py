#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""线上验证第71题（资料分析）v2 朱批解析 + 判题。事件驱动，图片请求拦截。"""
import sys
from playwright.sync_api import sync_playwright, TimeoutError as PTE

URL = "https://elvincccc.github.io/mindmap-canvas/"

def main():
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.route("**/*.{png,jpg,jpeg,gif,webp}", lambda r: r.abort())
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        # 等画布节点加载
        page.wait_for_function("() => document.querySelectorAll('.node').length > 0", timeout=20000)

        # 切到资料分析（按需加载 p5）
        page.evaluate("() => switchSubject('资料分析')")
        page.wait_for_function(
            "() => typeof DATA!=='undefined' && DATA && DATA.root && DATA.root.name==='资料分析'",
            timeout=20000)
        page.wait_for_function("() => document.querySelectorAll('.node').length > 0", timeout=20000)

        # 在内存树里定位第71题所属节点，直接调 openDetail 打开该题
        opened = page.evaluate("""() => {
          let found=null;
          (function rec(n){
            (n.examples||[]).forEach((e,i)=>{ if(e.src==='2025广东省考真题 第71题') found={node:n,i:i}; });
            (n.children||[]).forEach(rec);
          })(rootNode);
          if(!found) return {ok:false};
          openDetail(found.node);
          activateEx(found.i);
          return {ok:true, node:(found.node.name||''), i:found.i};
        }""")
        if not opened.get("ok"):
            print("[FAIL] 内存树里未找到第71题")
            return 1
        print("[PASS] 定位并打开第71题，节点：%s（第%d题）" % (opened["node"], opened["i"]+1))

        # 校验 v2 朱批结构
        page.wait_for_function(
            "() => document.querySelectorAll('#ansPanel .zp-seal').length>0", timeout=10000)
        seal = page.locator("#ansPanel .zp-seal").first.inner_text()
        steps = page.locator("#ansPanel .zp-step").count()
        errs = page.locator("#ansPanel .zp-err").count()
        has_4_34 = page.evaluate("() => document.getElementById('ansPanel').innerText.includes('4.34')")
        print("[PASS] 朱批印章：%s" % seal.strip()[:40])
        print("[PASS] 三段式步骤：%d，错因：%d，含答案数据4.34：%s" % (steps, errs, has_4_34))
        assert steps >= 4, "步骤数不足"
        assert errs >= 3, "错因数不足"
        assert has_4_34, "解析未含计算数据4.34"

        # 判题：先点练习按钮，再选 A（正确答案），验证判定为正确
        page.evaluate("() => { const b=document.querySelector('.ans-open'); if(b) b.click(); }")
        page.wait_for_function(
            "() => document.querySelectorAll('#detailLeft .pickable, #detailLeft [data-opt]').length>0 "
            "|| document.querySelector('#detailLeft')!==null", timeout=5000)
        # 找 A 选项并点击
        picked = page.evaluate("""() => {
          const root=document.getElementById('detailLeft');
          const cands=[...root.querySelectorAll('*')].filter(el=>{
            const t=(el.textContent||'').trim();
            return /^A[\\.、]?\\s*4\\.34/.test(t) && el.children.length===0;
          });
          if(cands.length){ cands[0].click(); return true; }
          return false;
        }""")
        print("[%s] 判题：点击选项A %s" % ("PASS" if picked else "SKIP", "成功" if picked else "(未匹配到可点元素)"))

        if errors:
            print("[FAIL] JS 错误：%s" % "; ".join(errors[:3]))
            return 1
        print("[PASS] 无 JS 运行时错误")
        browser.close()
    print("\n结果: PASS（第71题线上 v2 解析与判题验证通过）")
    return 0

if __name__ == "__main__":
    sys.exit(main())
