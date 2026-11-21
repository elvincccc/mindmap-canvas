#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""前端验证脚手架——把反复重写的 Playwright 专项验证样板固化。

设计原则：
- 重复样板（浏览器启动/禁缓存/pageerror+404监听/断言计数/PASS汇总/local-online切换）由本脚本统一处理；
- 具体断言通过内置预设（smoke/panel）或自定义 checks.json 提供，前端改动不再从零写脚本；
- local/online 一键切换，禁缓存内建（避免读到旧 docs.json/methods.json 的坑）。

子命令：
  smoke [url]                       标准冒烟：JS错误/404/关键按钮/节点数/弹窗打开
  panel [url] --name 方法提炼         面板专项：打开/卡片数/signal+steps渲染/关联例题跳转高亮/关闭返回
  custom [url] --checks checks.json  自定义断言清单（见下方格式）
  url 快捷值：local / online；也可直接给完整 URL

checks.json 格式（声明式断言，按顺序执行）：
{
  "checks": [
    {"name": "按钮存在", "type": "count", "selector": "#btnDocs", "op": "eq", "value": 1},
    {"name": "面板打开", "type": "class", "selector": "#docViewer", "has": "open", "after": {"type":"click","selector":"#btnDocs"}},
    {"name": "含关键词", "type": "text", "selector": "#docBody", "contains": "第"},
    {"name": "节点数>200", "type": "evaluate", "expr": "document.querySelectorAll('.node').length>200"}
  ]
}

用法示例：
  python3 tools/ui_probe.py smoke local
  python3 tools/ui_probe.py panel online --name 方法提炼
  python3 tools/ui_probe.py custom local --checks /tmp/checks.json
"""
import argparse, json, sys, time

URLS = {
    'local': 'http://127.0.0.1:8765/index.html',
    'online': 'https://elvincccc.github.io/mindmap-canvas/index.html',
}


def resolve_url(url):
    return URLS.get(url, url)


class Probe:
    def __init__(self, page):
        self.page = page
        self.results = []

    def ck(self, name, cond, extra=''):
        self.results.append(bool(cond))
        print(f'  [{"PASS" if cond else "FAIL"}] {name}' + (f'  {extra}' if extra else ''))
        return bool(cond)

    def summary(self, label):
        ok = sum(self.results)
        total = len(self.results)
        print(f'\n========== {label}: {ok}/{total} ==========')
        return ok == total


def make_page(pw, url):
    browser = pw.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 1440, 'height': 900})
    errs, bad = [], []
    page.on('pageerror', lambda e: errs.append(str(e)))
    page.on('response', lambda r: bad.append((r.status, r.url))
            if r.status >= 400 and 'favicon' not in r.url else None)
    # 禁缓存：所有 .json fetch 加时间戳（规避旧 docs/methods 缓存坑）
    page.add_init_script("""
      const _f=window.fetch;
      window.fetch=function(u,o){
        if(typeof u==='string'&&u.indexOf('.json')>=0)u=u+'?cb='+Date.now();
        return _f.call(this,u,o);
      };
    """)
    sep = '&' if '?' in url else '?'
    page.goto(url + sep + 'cb=' + str(int(time.time())), wait_until='networkidle', timeout=60000)
    page.wait_for_timeout(1200)
    return browser, page, errs, bad


def cmd_smoke(args, pw):
    url = resolve_url(args.url)
    browser, page, errs, bad = make_page(pw, url)
    pr = Probe(page)
    print(f'=== smoke @ {url} ===')
    pr.ck('页面标题非空', bool(page.title()))
    pr.ck('关键按钮存在', page.locator('#btnDocs').count() == 1 and page.locator('#btnMethods').count() == 1)
    # 默认收起时只有少量顶层节点，先点「展开全部」再数（按钮名可能是 btnExpandAll/展开全部）
    try:
        page.click('#btnExpandAll', timeout=2000)
        page.wait_for_timeout(500)
    except Exception:
        pass
    n = page.evaluate("document.querySelectorAll('.node').length")
    pr.ck('节点已渲染(>50)', n > 50, f'节点数={n}')
    # 弹窗可打开
    try:
        page.locator('.ex-open-btn').first.click(timeout=3000)
        page.wait_for_timeout(500)
        pr.ck('弹窗可打开', page.locator('#detailBox').evaluate("e=>e.classList.contains('open')"))
    except Exception as e:
        pr.ck('弹窗可打开', False, str(e)[:50])
    pr.ck('JS 零错误', len(errs) == 0, str(errs[:2]))
    pr.ck('无 404 资源', len(bad) == 0, str(bad[:2]))
    ok = pr.summary(f'smoke {args.url}')
    browser.close()
    return ok


def cmd_panel(args, pw):
    url = resolve_url(args.url)
    browser, page, errs, bad = make_page(pw, url)
    pr = Probe(page)
    name = args.name
    is_method = '方法' in name
    btn = '#btnMethods' if is_method else '#btnDocs'
    viewer = '#methodViewer' if is_method else '#docViewer'
    lst = '#methList' if is_method else '#docList'
    body = '#methBody' if is_method else '#docBody'
    print(f'=== panel「{name}」@ {url} ===')
    page.click(btn)
    page.wait_for_timeout(1200)
    pr.ck('面板已打开', page.locator(viewer).evaluate("e=>e.classList.contains('open')"))
    cnt = page.locator(f'{lst} .doc-item').count()
    pr.ck('卡片数>0', cnt > 0, f'实际={cnt}')
    if is_method:
        # 逐卡检查字段
        names = [page.locator(f'{lst} .doc-item').nth(i).inner_text().strip() for i in range(cnt)]
        for i, nm in enumerate(names):
            page.locator(f'{lst} .doc-item').nth(i).click()
            page.wait_for_timeout(200)
            sig = page.locator(f'{body} .meth-signal').count()
            mnem = page.locator(f'{body} .meth-mn').count()
            Steps = page.locator(f'{body} .meth-steps li').count()
            dims = page.locator(f'{body} .meth-dims').count()
            pr.ck(f'{nm}: signal+口诀+结构', sig == 1 and mnem == 1 and (Steps > 0 or dims == 1),
                  f'steps={Steps} dims={dims}')
        # 关联例题跳转 + 关闭返回
        if page.locator(f'{body} .meth-ex').count() > 0:
            if not page.locator('#methExList').evaluate("e=>e.classList.contains('open')"):
                page.click('#methExBtn')
                page.wait_for_timeout(200)
            page.locator(f'{body} .meth-ex').first.click()
            page.wait_for_timeout(900)
            pr.ck('关联例题→弹窗打开', page.locator('#detailBox').evaluate("e=>e.classList.contains('open')"))
            page.keyboard.press('Escape')
            page.wait_for_timeout(900)
            pr.ck('关闭→返回方法面板', page.locator(viewer).evaluate("e=>e.classList.contains('open')"))
    else:
        # 文档面板：首个文档有正文
        if cnt > 0:
            page.locator(f'{lst} .doc-item').first.click()
            page.wait_for_timeout(400)
            pr.ck('文档正文非空', len(page.locator(body).inner_text()) > 100)
    pr.ck('JS 零错误', len(errs) == 0, str(errs[:2]))
    ok = pr.summary(f'panel {name} {args.url}')
    browser.close()
    return ok


def cmd_custom(args, pw):
    url = resolve_url(args.url)
    with open(args.checks, encoding='utf-8') as f:
        cfg = json.load(f)
    browser, page, errs, bad = make_page(pw, url)
    pr = Probe(page)
    print(f'=== custom @ {url} ({len(cfg["checks"])} checks) ===')
    for c in cfg['checks']:
        # 可选前置动作
        if c.get('after'):
            act = c['after']
            if act.get('type') == 'click':
                page.click(act['selector'])
                page.wait_for_timeout(act.get('wait', 300))
        t = c['type']
        sel = c.get('selector', '')
        if t == 'count':
            n = page.locator(sel).count()
            op, v = c.get('op', 'eq'), c.get('value', 1)
            cond = {'eq': n == v, 'gt': n > v, 'gte': n >= v, 'lt': n < v}.get(op, n == v)
            pr.ck(c['name'], cond, f'n={n}')
        elif t == 'class':
            cond = page.locator(sel).evaluate("(e,c)=>e.classList.contains(c)", c['has'])
            pr.ck(c['name'], cond)
        elif t == 'text':
            txt = page.locator(sel).inner_text()
            pr.ck(c['name'], c['contains'] in txt)
        elif t == 'evaluate':
            pr.ck(c['name'], bool(page.evaluate(c['expr'])))
        else:
            pr.ck(c['name'] + ' (未知type)', False)
    pr.ck('JS 零错误', len(errs) == 0, str(errs[:2]))
    ok = pr.summary(f'custom {args.url}')
    browser.close()
    return ok


def main():
    ap = argparse.ArgumentParser(description='前端验证脚手架（Playwright 样板固化）')
    sub = ap.add_subparsers(dest='cmd', required=True)
    p_smoke = sub.add_parser('smoke', help='标准冒烟')
    p_smoke.add_argument('url', nargs='?', default='local', help='local/online 或完整URL')
    p_panel = sub.add_parser('panel', help='面板专项')
    p_panel.add_argument('url', nargs='?', default='local')
    p_panel.add_argument('--name', default='方法提炼', help='面板名，含"方法"走方法面板，否则文档面板')
    p_custom = sub.add_parser('custom', help='自定义断言清单')
    p_custom.add_argument('url', nargs='?', default='local')
    p_custom.add_argument('--checks', required=True, help='checks.json 路径')
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        ok = {'smoke': cmd_smoke, 'panel': cmd_panel, 'custom': cmd_custom}[args.cmd](args, pw)
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
