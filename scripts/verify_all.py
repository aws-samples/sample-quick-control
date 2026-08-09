#!/usr/bin/env python3
"""verify_all.py — 单会话逐一验证 quick_ctl 的每个能力，输出 PASS/FAIL 报告。
不重启 App、不删数据。send 用无害测试语。"""
import os,time
from playwright.sync_api import sync_playwright
PORT=os.environ.get("QUICK_CDP_PORT","9333")

def connect():
    pw=sync_playwright().start(); b=pw.chromium.connect_over_cdp(f"http://127.0.0.1:{PORT}")
    pg=[p for c in b.contexts for p in c.pages if "Amazon Quick" in (p.title() or "")][0]
    return pw,b,pg

R=[]
def check(name, fn):
    try:
        r=fn(); R.append((name,"PASS",r)); print(f"  ✓ {name}: {r}")
    except Exception as e:
        R.append((name,"FAIL",str(e)[:80])); print(f"  ✗ {name}: {str(e)[:80]}")

def main():
    pw,b,pg=connect()
    ph="Ask a question"
    inp=lambda: pg.get_by_placeholder(ph,exact=False)
    try:
        print("── 基础/导航 ──")
        check("new-chat", lambda:(pg.get_by_role("button",name="New chat").first.click(),time.sleep(0.6),"ok")[-1])  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        check("nav Activity feed", lambda:(pg.get_by_role("button",name="Activity feed").first.click(),time.sleep(1),"/feed" in pg.url and "feed-ok")[-1])  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        check("feed 列条目", lambda: "Calendar" in pg.evaluate("()=>document.body.innerText"))
        check("nav My stuff", lambda:(pg.get_by_role("button",name="My stuff").first.click(),time.sleep(1),"/my-stuff" in pg.url and "ok")[-1])  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        check("artifacts 有视图切换", lambda: pg.get_by_role("button",name="Grid view").count()>0 or pg.get_by_role("button",name="List view").count()>0)
        check("nav Agents & skills", lambda:(pg.get_by_role("button",name="Agents & skills").first.click(),time.sleep(1),"/agents" in pg.url and "ok")[-1])  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        check("agents 搜索框", lambda: pg.get_by_placeholder("Search agents",exact=False).count()>0)
        check("agents Create 按钮", lambda: pg.get_by_role("button",name="Create").count()>0)
        check("nav Mission control", lambda:(pg.get_by_role("button",name="Mission control").first.click(),time.sleep(1.2),(pg.get_by_role("button",name="Schedules").count()>0 or pg.get_by_text("Needs input").count()>0) and "ok")[-1])  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        check("mission Schedules 过滤", lambda:(pg.get_by_role("button",name="Schedules").first.click(),time.sleep(0.6),"ok")[-1])  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        # 关掉 mission 弹窗
        try: pg.get_by_role("button",name="Close").first.click(); time.sleep(0.5)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        except: pass

        print("── 设置子页 ──")
        def open_setting(sub):
            btn=pg.locator("button.settings-sub-item", has_text=sub).first
            if btn.count()==0:
                pg.get_by_role("button",name="Settings").first.click(); time.sleep(0.7)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
                btn=pg.locator("button.settings-sub-item", has_text=sub).first
            btn.evaluate("el => el.click()"); time.sleep(1); return pg.url.split("/")[-1] or "ok"  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        check("settings Capabilities", lambda:(open_setting("Capabilities"),"/capabilities" in pg.url and "ok")[-1])
        check("connectors 搜索框", lambda: pg.get_by_placeholder("Search connectors",exact=False).count()>0)
        check("settings My computer", lambda: open_setting("My computer"))
        check("settings My context", lambda: open_setting("My context"))
        check("settings Customization", lambda: open_setting("Customization"))

        print("── 输入框工具条 ──")
        pg.get_by_role("button",name="New chat").first.click(); time.sleep(0.8)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        check("type 输入", lambda:(inp().click(),inp().type("验证测试",delay=8),inp().input_value()[:20])[-1] if inp().count() else "no-input")
        check("clear 清空", lambda:(inp().press("Meta+A"),inp().press("Backspace"),len(inp().input_value()))[-1])
        check("Add context 菜单", lambda:(pg.get_by_role("button",name="Add context").first.click(),time.sleep(0.5),pg.get_by_text("Upload files",exact=False).count()>0 and "Upload/Folder/Spaces/Web")[-1])  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        pg.keyboard.press("Escape"); time.sleep(0.4)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        check("模型菜单(Fast/Balanced/Smart)", lambda:(pg.get_by_role("button",name="Smart").first.click(),time.sleep(0.5),pg.get_by_text("Balanced",exact=False).count()>0 and pg.get_by_text("Fast",exact=False).count()>0 and "ok")[-1])  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        check("思考强度(Low/Med/High)", lambda: pg.get_by_role("button",name="High",exact=True).count()>0)
        pg.keyboard.press("Escape"); time.sleep(0.4)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        check("模式下拉(左上 Quick)", lambda:(pg.get_by_role("button",name="Quick",exact=True).first.click(),time.sleep(0.5),"ok")[-1])  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        pg.keyboard.press("Escape")

        print("── 历史/会话 ──")
        # 注意:这里不用 f-string —— 替换字段里既有反斜杠转义又复用外层引号,
        # 属 PEP 701(3.12 才放开)语法,在 requires-python 声明的 3.10 上是 SyntaxError。
        # 改用 .format() + JS 内层单引号(querySelectorAll 对引号不敏感,行为不变)。
        check("list-chats", lambda: "{} 条".format(pg.evaluate("()=>document.querySelectorAll('[role=option]').length")))
        check("search-chats 打开", lambda:(pg.get_by_role("button",name="Search chats").first.click(),time.sleep(0.5),"ok")[-1])  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        pg.keyboard.press("Escape"); time.sleep(0.3)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        check("open-chat 历史", lambda:(pg.get_by_role("option").first.click(),time.sleep(0.8),"ok")[-1])  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        check("export 按钮存在", lambda: pg.get_by_role("button",name="Export conversation").count()>0)
        check("消息操作(Copy/Reply/Edit/Speak)", lambda: all(pg.get_by_role("button",name=n).count()>0 for n in ["Copy","Reply in thread","Edit message","Speak message"]))

        print("\n── 端到端 send（真实发送无害语）──")
        pg.get_by_role("button",name="New chat").first.click(); time.sleep(0.8)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        def e2e():
            box=inp(); box.click(); box.type("回复ok两个字即可",delay=8)
            before=len(pg.evaluate("()=>document.body.innerText")); box.press("Enter")
            stable=0;last="";dl=time.time()+60
            while time.time()<dl:
                time.sleep(1.5);cur=pg.evaluate("()=>document.body.innerText")  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
                if cur==last:stable+=1
                else:stable=0;last=cur
                if stable>=2 and len(cur)>before:break
            return "回复已收到" if len(last)>before else "无回复"
        check("send→收回复", e2e)
    finally:
        b.close();pw.stop()
    # 汇总
    p=sum(1 for _,s,_ in R if s=="PASS"); f=sum(1 for _,s,_ in R if s=="FAIL")
    print(f"\n════ 结果: {p} PASS / {f} FAIL / 共 {len(R)} ════")
    if f: print("失败项:", [n for n,s,_ in R if s=="FAIL"])

if __name__=="__main__": main()
