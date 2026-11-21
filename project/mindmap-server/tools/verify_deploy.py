#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
事件驱动的行测思维导图画布部署验证脚本（替代固定 sleep 轮询）。

设计要点：
  - 部署等待：gh run list 取最新 run id + gh run watch --exit-status --interval 5
    阻塞等待，完全不用固定 sleep。
  - 页面等待：全部基于事件/条件（domcontentloaded、wait_for_function、
    wait_for_selector、节点数稳定轮询），不用 networkidle，不写长 wait_for_timeout。
  - OSS 配图外链：page.route 拦截 image 请求直接 abort，避免外链拖慢/超时。
    （图片已拦截，不影响画布逻辑验证。）
  - 每个验证项独立捕获异常，FAIL 不中断后续项，最后汇总并以非 0 退出码结束。

用法示例：
  # 线上 Pages（默认地址）
  python3 tools/verify_deploy.py --mode online
  # 显式指定地址（线上 / 本地均可）
  python3 tools/verify_deploy.py --url https://elvincccc.github.io/mindmap-canvas/
  python3 tools/verify_deploy.py --mode local --url 'http://127.0.0.1:8800/canvas?api=1'
  # 等 deploy.yml 跑完再验证
  python3 tools/verify_deploy.py --mode online --wait-deploy

依赖：playwright（已安装，需 chromium 可用）；--wait-deploy 时还需要 gh CLI 且已登录。
"""

import argparse
import json
import subprocess
import sys
import traceback

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

DEFAULT_ONLINE = "https://elvincccc.github.io/mindmap-canvas/"
DEFAULT_LOCAL = "http://127.0.0.1:8800/canvas?api=1"
REPO = "elvincccc/mindmap-canvas"
WORKFLOW = "deploy.yml"

# 轮询比较两次 .node 计数，连续稳定若干次才返回（事件驱动，无长睡眠）。
STABLE_COUNT_JS = """
() => {
  const n = document.querySelectorAll('.node').length;
  const s = window.__verifyStable;
  if (!s || s.prev !== n) { window.__verifyStable = {prev: n, run: 1}; return false; }
  s.run++;
  if (s.run >= 3 && n > 0) return n;
  return false;
}
"""


class CheckFailed(Exception):
    """单个验证项失败。"""


class Report:
    def __init__(self):
        self.results = []  # (name, ok, detail)
        self.notes = []

    def run(self, name, fn):
        try:
            detail = fn() or ""
            self.results.append((name, True, detail))
            print("[PASS] {}{}".format(name, " — " + str(detail) if detail else ""))
        except Exception as exc:  # noqa: BLE001 - 单项失败不中断
            self.results.append((name, False, str(exc)))
            print("[FAIL] {} — {}".format(name, exc))

    def skip(self, name, why):
        print("[SKIP] {} — {}".format(name, why))

    def note(self, text):
        self.notes.append(text)

    def summary(self):
        passed = sum(1 for _, ok, _ in self.results if ok)
        failed = len(self.results) - passed
        print("\n" + "=" * 56)
        print("验证汇总: {} 项通过 / {} 项失败".format(passed, failed))
        for note in self.notes:
            print("  注: " + note)
        print("=" * 56)
        for name, ok, detail in self.results:
            print("  {} {}{}".format(
                "PASS" if ok else "FAIL", name,
                " — " + str(detail) if detail else ""))
        print("最终结果: {}".format("PASS" if failed == 0 else "FAIL"))
        return failed


def deploy_wait(report):
    """用 gh CLI 等待 workflow 完成（阻塞，无固定 sleep）。"""
    repo, wf = REPO, WORKFLOW
    list_cmd = ["gh", "run", "list", "--repo", repo, "--workflow", wf,
                "--limit", "1", "--json", "databaseId,status,conclusion"]
    proc = subprocess.run(list_cmd, capture_output=True, text=True, timeout=90)
    if proc.returncode != 0:
        raise CheckFailed("gh run list 失败: " + (proc.stderr.strip() or "未知错误"))
    runs = json.loads(proc.stdout.strip() or "[]")
    if not runs:
        raise CheckFailed("未找到 workflow {} 的最近 run".format(wf))
    run_id = runs[0]["databaseId"]
    print("  最新 run: id={} status={} conclusion={}".format(
        run_id, runs[0].get("status"), runs[0].get("conclusion")))

    watch_cmd = ["gh", "run", "watch", str(run_id), "--repo", repo,
                 "--exit-status", "--interval", "5"]
    print("  阻塞等待: " + " ".join(watch_cmd))
    # gh run watch 内部按 5s 轮询，超时上限只是安全护栏，不是验证用的固定 sleep。
    watch = subprocess.run(watch_cmd, timeout=1800)
    if watch.returncode != 0:
        raise CheckFailed("gh run watch 退出码 {}（部署未完成或失败）".format(watch.returncode))
    return "run {} 部署成功".format(run_id)


def wait_nodes_stable(page, timeout_ms=10000):
    """等待 .node 数量稳定并返回该数量（转 Python int，避免 JSHandle 比较错误）。"""
    page.evaluate("() => { window.__verifyStable = null; }")
    handle = page.wait_for_function(STABLE_COUNT_JS, polling=150, timeout=timeout_ms)
    return handle.json_value()


def check_toolbar(page):
    def cnt(sel):
        return page.locator(sel).count()
    ok = (cnt("#btnFull") == 1 and cnt("#btnCollapseAll") == 1
          and cnt("#btnExpandAll") == 1
          and cnt("#btnZoomIn") == 0 and cnt("#btnZoomOut") == 0)
    if not ok:
        raise CheckFailed(
            "btnFull={} btnCollapseAll={} btnExpandAll={} btnZoomIn={} btnZoomOut={}".format(
                cnt("#btnFull"), cnt("#btnCollapseAll"), cnt("#btnExpandAll"),
                cnt("#btnZoomIn"), cnt("#btnZoomOut")))
    return "btnFull / btnCollapseAll / btnExpandAll 存在，btnZoomIn / btnZoomOut 不存在"


def check_volselect(page):
    # 试卷数随录入增长（2026-11-20 已 6 套+全部=7），不写死具体数字：
    # 只要求恰好 1 个下拉框、至少 2 个 option（"全部"+至少 1 套试卷）。
    sel_cnt = page.locator("#volSelect").count()
    opt_cnt = page.locator("#volSelect option").count()
    if sel_cnt != 1 or opt_cnt < 2:
        raise CheckFailed("#volSelect 数量={}，option 数量={}（期望 1 个下拉框、≥2 个 option）".format(sel_cnt, opt_cnt))
    return "下拉框存在且含 {} 个 option（试卷，随录入增长）".format(opt_cnt)


def check_expand_collapse(page):
    page.locator("#btnCollapseAll").click()
    collapsed = wait_nodes_stable(page)
    page.locator("#btnExpandAll").click()
    expanded = wait_nodes_stable(page)
    if not (expanded > collapsed > 0):
        raise CheckFailed("默认收起={}，展开后={}（期望展开后 > 收起且均 > 0）".format(
            collapsed, expanded))
    return "默认收起 {} 个节点，展开后 {} 个节点".format(collapsed, expanded)


def check_volume_change(page):
    base = page.evaluate("() => countEx(rootNode)")
    values = page.evaluate(
        "() => [...document.getElementById('volSelect').options].map(o => o.value).filter(v => v)")
    for value in values:
        page.evaluate(
            """v => { const s = document.getElementById('volSelect');
                     s.value = v; s.dispatchEvent(new Event('change', {bubbles: true})); }""",
            value)
        try:
            page.wait_for_function("b => countEx(rootNode) !== b", arg=base, timeout=5000)
        except PlaywrightTimeoutError:
            continue
        now = page.evaluate("() => countEx(rootNode)")
        # 还原为“全部”，避免影响后续验证项。
        page.evaluate(
            """() => { const s = document.getElementById('volSelect');
                       s.value = ''; s.dispatchEvent(new Event('change', {bubbles: true})); }""")
        return "选卷「{}」后 countEx(rootNode): {} → {}".format(value, base, now)
    raise CheckFailed("遍历 {} 个试卷均未使 countEx(rootNode) 变化（基线={}）".format(
        len(values), base))


def check_popup(page):
    # 优先点击真实“例题”按钮；无例题节点时回退到直接调用 openDetail。
    btn = page.locator(".ex-open-btn")
    if btn.count() > 0:
        btn.first.click(timeout=5000)
    else:
        page.evaluate("() => openDetail(rootNode)")
    page.wait_for_selector("#detailBox.open", timeout=5000)
    if page.locator("#detailRight").count() != 1:
        raise CheckFailed("弹窗已打开但 #detailRight 不存在")
    return "弹窗可打开且含右栏解析区 #detailRight"


def check_ans_tab(page):
    # 确保弹窗处于打开状态。
    if page.locator("#detailBox.open").count() == 0:
        check_popup(page)
    ans_btn = page.locator(".ans-open")
    if ans_btn.count() == 0:
        raise CheckFailed("弹窗内无 .ans-open 按钮，无法验证右栏解析 Tab")
    ans_btn.first.click(timeout=5000)
    # 兼容两套解析结构：v2 朱批与旧 Tab（.ans-tab）。
    # 注意（6.44）：新 UI 已删除大印章 .zp-seal，答案延时到左栏揭晓，
    # v2 解析展开的真实标志改为 .zp-step / .zp-hero，不能再等 .zp-seal。
    page.wait_for_function(
        "() => document.querySelectorAll('#detailRight .ans-tab').length>0 "
        "|| document.querySelectorAll('#detailRight .zp-step').length>0 "
        "|| document.querySelectorAll('#detailRight .zp-hero').length>0",
        timeout=5000,
    )
    steps = page.locator("#detailRight .zp-step").count()
    if steps or page.locator("#detailRight .zp-hero").count():
        return "右栏 v2 朱批解析存在（步骤 {} · 无大印章答案）".format(steps)
    n = page.locator("#detailRight .ans-tab").count()
    if n == 0:
        raise CheckFailed("点击解析后 #detailRight 下无 .ans-tab/.zp-step/.zp-hero")
    return "右栏解析 Tab 存在（{} 个 .ans-tab）".format(n)


def check_no_js_errors(page, errors):
    if errors:
        raise CheckFailed("捕获 {} 个 pageerror: {}".format(len(errors), " | ".join(errors[:5])))
    return "无未捕获 JS 错误（pageerror=0）"


def browser_checks(report, url):
    """执行所有基于 Playwright 的验证项。"""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1440, "height": 900})

        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))

        def abort_images(route):
            if route.request.resource_type == "image":
                route.abort()
            else:
                route.continue_()

        page.route("**/*", abort_images)
        report.note("图片请求已拦截（resource_type=image 直接 abort），不影响画布逻辑验证")

        # 事件驱动导航与数据渲染等待（不用 networkidle）。
        print("  导航: " + url)
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_function(
            "() => {const e=document.getElementById('statLine');"
            "return e && e.textContent.trim().length > 0}",
            timeout=30000)
        page.wait_for_selector(".node", timeout=30000)

        report.run("工具栏按钮", lambda: check_toolbar(page))
        report.run("试卷下拉框(≥2项)", lambda: check_volselect(page))
        report.run("默认收起/展开节点数", lambda: check_expand_collapse(page))
        report.run("选卷后 countEx 变化", lambda: check_volume_change(page))
        report.run("弹窗与右栏解析区", lambda: check_popup(page))
        report.run("右栏解析(v2朱批/旧Tab)", lambda: check_ans_tab(page))
        report.run("零 JS 错误", lambda: check_no_js_errors(page, errors))

        browser.close()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="事件驱动的思维导图画布部署验证（无 networkidle / 无长固定 sleep）")
    parser.add_argument(
        "--url", default=None,
        help="目标地址；默认 online={} / local={}".format(DEFAULT_ONLINE, DEFAULT_LOCAL))
    parser.add_argument("--mode", choices=["online", "local"], default="online",
                        help="验证模式（默认 online）")
    parser.add_argument("--wait-deploy", action="store_true",
                        help="先用 gh run watch 等待 deploy.yml 完成再验证")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    url = args.url or (DEFAULT_LOCAL if args.mode == "local" else DEFAULT_ONLINE)
    report = Report()
    print("模式: {} | 地址: {}".format(args.mode, url))

    if args.wait_deploy:
        print("\n[部署等待]")
        report.run("GitHub 部署完成", lambda: deploy_wait(report))
    else:
        report.skip("GitHub 部署完成", "未指定 --wait-deploy")

    print("\n[浏览器验证]")
    try:
        browser_checks(report, url)
    except PlaywrightTimeoutError as exc:
        report.results.append(("页面初始化", False, "等待超时: {}".format(exc)))
        print("[FAIL] 页面初始化 — 等待超时: {}".format(exc))
    except Exception as exc:  # noqa: BLE001 - 初始化异常也记录为 FAIL
        report.results.append(("页面初始化", False, str(exc)))
        print("[FAIL] 页面初始化 — {}".format(exc))
        traceback.print_exc()

    return 1 if report.summary() else 0


if __name__ == "__main__":
    sys.exit(main())
