#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""线上验证第71题材料表格截图：URL正确、真实加载(naturalWidth>0)、Lightbox可放大。不拦截图片。"""
import sys
from playwright.sync_api import sync_playwright

URL = "https://elvincccc.github.io/mindmap-canvas/"
OSS_HOST = "alibbxtbox.oss-cn-guangzhou.aliyuncs.com"

def main():
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_function("() => document.querySelectorAll('.node').length > 0", timeout=20000)

        # 切到资料分析
        page.evaluate("() => switchSubject('资料分析')")
        page.wait_for_function(
            "() => typeof DATA!=='undefined' && DATA && DATA.root && DATA.root.name==='资料分析'",
            timeout=20000)

        # 定位并打开第71题
        opened = page.evaluate("""() => {
          let found=null;
          (function rec(n){
            (n.examples||[]).forEach((e,i)=>{ if(e.src==='2025广东省考真题 第71题') found={node:n,i:i}; });
            (n.children||[]).forEach(rec);
          })(rootNode);
          if(!found) return {ok:false};
          openDetail(found.node); activateEx(found.i); return {ok:true};
        }""")
        assert opened.get("ok"), "未找到第71题"
        page.wait_for_function("() => document.querySelectorAll('#detailBody .ex-card').length>0", timeout=8000)

        # 找到第71题那张卡片里的配图
        info = page.evaluate("""(host) => {
          const cards=[...document.querySelectorAll('#detailBody .ex-card')];
          const card=cards.find(c=>c.textContent.includes('第71题')||c.textContent.includes('社会消费品零售额'));
          if(!card) return {ok:false, reason:'no card'};
          const fig=card.querySelector('.ex-fig img');
          if(!fig) return {ok:false, reason:'no img in card', cardText:card.textContent.slice(0,60)};
          return {ok:true, src:fig.getAttribute('src'), nw:fig.naturalWidth, nh:fig.naturalHeight, complete:fig.complete};
        }""", OSS_HOST)
        print("[INFO] 配图信息:", info)
        assert info.get("ok"), "卡片内无配图: %s" % info.get("reason")
        assert OSS_HOST in info["src"], "图片URL不是OSS外链: %s" % info["src"]

        # 等图片真实加载完成
        page.wait_for_function(
            """() => {
              const cards=[...document.querySelectorAll('#detailBody .ex-card')];
              const card=cards.find(c=>c.querySelector('.ex-fig img'));
              const img=card&&card.querySelector('.ex-fig img');
              return img && img.complete && img.naturalWidth>0;
            }""", timeout=20000)
        dims = page.evaluate("""() => {
          const img=[...document.querySelectorAll('#detailBody .ex-fig img')].find(i=>i.naturalWidth>0);
          return {w:img.naturalWidth,h:img.naturalHeight};
        }""")
        print("[PASS] 材料图真实加载成功：%d×%d px" % (dims["w"], dims["h"]))

        # 点击配图验证 Lightbox 放大
        page.evaluate("""() => {
          const img=[...document.querySelectorAll('#detailBody .ex-fig img')].find(i=>i.naturalWidth>0);
          img.closest('.ex-fig').click();
        }""")
        page.wait_for_function("() => document.getElementById('lightbox').classList.contains('open')", timeout=5000)
        lb_src = page.evaluate("() => document.querySelector('#lightbox img').getAttribute('src')")
        print("[PASS] Lightbox 放大可用，src=%s" % lb_src.split('/')[-1])

        # v2 朱批解析仍在（回归）
        seal = page.locator("#ansPanel .zp-seal").first.inner_text()
        print("[PASS] v2朱批解析仍在，印章=%s" % seal.strip())

        if errors:
            print("[FAIL] JS错误:", errors[:3]); return 1
        print("[PASS] 无JS错误")
        browser.close()
    print("\n结果: PASS（第71题材料图加载 + 放大 + 朱批解析 全部通过）")
    return 0

if __name__ == "__main__":
    sys.exit(main())
