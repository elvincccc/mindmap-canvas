#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""线上终验第71题：做错标签(左栏+朱批)、材料图、题干只留问题句。"""
import sys
from playwright.sync_api import sync_playwright

URL = "https://elvincccc.github.io/mindmap-canvas/"
OSS_HOST = "alibbxtbox.oss-cn-guangzhou.aliyuncs.com"

def main():
    errors=[]
    with sync_playwright() as p:
        b=p.chromium.launch(headless=True)
        pg=b.new_page(viewport={"width":1440,"height":900})
        pg.on("pageerror",lambda e:errors.append(str(e)))
        pg.goto(URL,wait_until="domcontentloaded",timeout=60000)
        pg.wait_for_function("() => document.querySelectorAll('.node').length>0",timeout=20000)
        pg.evaluate("() => switchSubject('资料分析')")
        pg.wait_for_function("() => typeof DATA!=='undefined' && DATA.root && DATA.root.name==='资料分析'",timeout=20000)
        ok=pg.evaluate("""() => {
          let f=null;
          (function r(n){(n.examples||[]).forEach((e,i)=>{if(e.src==='2025广东省考真题 第71题')f={n:n,i:i}});(n.children||[]).forEach(r)})(rootNode);
          if(!f)return false; openDetail(f.n); activateEx(f.i); return true;
        }""")
        assert ok,"未找到第71题"
        pg.wait_for_function("() => document.querySelectorAll('#detailBody .ex-card').length>0",timeout=8000)

        # 左栏卡片：定位第71题卡片（用题干关键词）
        card=pg.evaluate("""() => {
          const c=[...document.querySelectorAll('#detailBody .ex-card')].find(x=>x.textContent.includes('2023年1~11月'));
          if(!c)return {ok:false};
          const wrong=c.querySelector('.ex-tag.wrong');
          const right=c.querySelector('.ex-tag.right');
          const q=c.querySelector('.ex-q');
          const img=c.querySelector('.ex-fig img');
          return {ok:true, wrong:!!wrong, wrongTxt:wrong?wrong.textContent.trim():'', right:!!right,
                  q:q?q.textContent.trim():'', img:img?img.getAttribute('src'):null};
        }""")
        print("[INFO] 左栏卡片:",card)
        assert card.get("ok"),"未找到卡片"
        assert card["wrong"] and not card["right"],"左栏做错标签不对"
        assert "❌" in card["wrongTxt"] or "做错" in card["wrongTxt"],"标签文案不对"
        assert "4055.97" not in card["q"],"题干还残留文字材料数据"
        assert "社会消费品零售额约为" in card["q"],"题干问题句丢失"
        print("[PASS] 左栏：❌做错标签正确，题干只剩问题句")

        # 材料图
        assert card["img"] and OSS_HOST in card["img"],"材料图外链丢失"
        pg.wait_for_function("""() => {const i=[...document.querySelectorAll('#detailBody .ex-fig img')].find(x=>x.naturalWidth>0);return !!i}""",timeout=20000)
        print("[PASS] 材料图正常加载")

        # 右栏朱批做错标签
        pg.evaluate("() => {const b=document.querySelector('.ans-open'); if(b)b.click()}")
        pg.wait_for_function("() => document.querySelector('#ansPanel .zp-seal')",timeout=8000)
        ztag=pg.evaluate("""() => {const e=document.querySelector('#ansPanel .zp-tag-no');return e?e.textContent.trim():null}""")
        seal=pg.locator('#ansPanel .zp-seal').first.inner_text()
        print("[INFO] 朱批: 印章=%s, 做错标签=%s"%(seal.strip(),ztag))
        assert ztag and "错" in ztag,"朱批做错标签缺失"
        print("[PASS] 右栏朱批：✕做错标签正确，印章=%s"%seal.strip())

        if errors:
            print("[FAIL] JS错误:",errors[:3]);return 1
        print("[PASS] 无JS错误")
        b.close()
    print("\n结果: PASS（做错标签+题干精简+材料图 全部通过）")
    return 0

if __name__=="__main__":
    sys.exit(main())
