#!/usr/bin/env python3
"""probe_settings.py — 探 Settings 子页导航方式 + 验证一批真实动作。单会话。"""
import os,time,json
from playwright.sync_api import sync_playwright
PORT=os.environ.get("QUICK_CDP_PORT","9333")

MAPJS=open(os.path.join(os.path.dirname(__file__),"crawl_all.py")).read().split('MAPJS = r"""')[1].split('"""')[0]

def connect():
    p=sync_playwright().start(); b=p.chromium.connect_over_cdp(f"http://127.0.0.1:{PORT}")
    pg=None
    for c in b.contexts:
        for page in c.pages:
            try:
                if "Amazon Quick" in (page.title() or ""): pg=page;break
            except: pass
        if pg:break
    return p,b,pg or b.contexts[0].pages[0]

def main():
    p,b,pg=connect()
    try:
        # 1) 探 Settings：先看点击 "Settings" 会发生什么(它可能是展开/折叠)
        print("=== 点 Settings 前 URL:", pg.url[:50])
        # Settings 子项可能需要滚到底部侧栏。直接尝试各子项的 role=button 点击后看 URL
        for item in ["Capabilities","My computer","My context","Customization"]:
            try:
                pg.get_by_role("button",name=item,exact=True).first.click(timeout=2500)
                time.sleep(1.5)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
                d=pg.evaluate(MAPJS)
                main=[e for e in d['elements'] if e['box'][0]>290][:22]
                print(f"\n### {item} → {d['url'][:55]}")
                print("   headings:", d['headings'][:4])
                for e in main:
                    lab=e['aria'] or e['ph'] or e['testid'] or e['text']
                    if lab: print(f"     <{e['tag']}{'/'+e['role'] if e['role'] else ''}> {lab!r}")
            except Exception as ex:
                print(f"\n### {item}: 点击失败 {str(ex)[:60]}")
        # 回主聊天
        pg.get_by_role("button",name="New chat").first.click(); time.sleep(1)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
    finally:
        b.close();p.stop()

if __name__=="__main__": main()
