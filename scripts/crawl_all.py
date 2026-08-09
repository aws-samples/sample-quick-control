#!/usr/bin/env python3
"""crawl_all.py — 单会话遍历 Quick 所有主要界面并 dump 元素图谱（快，避免多次启动）。
用法: uv run --with playwright python crawl_all.py [输出目录]
"""
import sys, os, json, time
from playwright.sync_api import sync_playwright

PORT=os.environ.get("QUICK_CDP_PORT","9333")
OUT=sys.argv[1] if len(sys.argv)>1 else "/tmp/quickmap"
os.makedirs(OUT, exist_ok=True)

MAPJS = r"""
() => {
  const vis = el => { const r=el.getBoundingClientRect(); const s=getComputedStyle(el);
    return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'; };
  const pick = el => ({tag:el.tagName.toLowerCase(),role:el.getAttribute('role')||'',
    aria:el.getAttribute('aria-label')||'',testid:el.getAttribute('data-testid')||'',
    ph:el.getAttribute('placeholder')||'',title:el.getAttribute('title')||'',
    text:(el.innerText||'').trim().slice(0,45),
    disabled:el.disabled||el.getAttribute('aria-disabled')==='true'||false,
    box:(()=>{const r=el.getBoundingClientRect();return[Math.round(r.x),Math.round(r.y)];})()});
  const sel='button,[role=button],[role=tab],[role=menuitem],[role=option],[role=switch],[role=checkbox],a[href],[contenteditable=true],textarea,input,select,[data-testid]';
  const out=[];const seen=new Set();
  document.querySelectorAll(sel).forEach(el=>{if(vis(el)){const p=pick(el);
    const k=(p.aria||p.testid||p.ph||p.title||p.text)+'|'+p.box[0]+','+p.box[1];
    if((p.aria||p.testid||p.ph||p.title||p.text||p.role)&&!seen.has(k)){seen.add(k);out.push(p);}}});
  return {url:location.href,title:document.title,
    headings:[...document.querySelectorAll('h1,h2,h3,h4')].filter(vis).map(h=>h.innerText.trim().slice(0,50)),
    elements:out};
}
"""

def connect():
    p=sync_playwright().start()
    b=p.chromium.connect_over_cdp(f"http://127.0.0.1:{PORT}")
    pg=None
    for c in b.contexts:
        for page in c.pages:
            try:
                if "Amazon Quick" in (page.title() or "") or "renderer/index" in page.url or "/chat" in page.url or "/feed" in page.url: pg=page;break
            except: pass
        if pg:break
    if not pg: pg=b.contexts[0].pages[0]
    return p,b,pg

def dump(pg,name):
    d=pg.evaluate(MAPJS)
    json.dump(d,open(f"{OUT}/{name}.json","w"),ensure_ascii=False,indent=1)
    # 只打印主内容区(x>300,跳过左侧栏)且非通用导航的元素
    NAV={'Go back','Go forward','Mission control','New chat','Activity feed','My stuff',
         'Agents & skills','More','Search chats','Recents menu','Settings','Capabilities',
         'My computer','My context','Customization','Delete','Task list','Session tabs'}
    main=[e for e in d['elements'] if e['box'][0]>290 and (e['aria'] or e['text'] or e['ph'] or e['testid']) not in NAV]
    print(f"\n=== {name} | {d['url'][:60]} | headings={d['headings']}")
    seen=set()
    for e in main:
        lab=e['aria'] or e['ph'] or e['testid'] or e['text'] or e['title'] or e['role']
        if not lab or lab in seen: continue
        seen.add(lab)
        print(f"   <{e['tag']}{'/'+e['role'] if e['role'] else ''}> {lab!r}{' [x]' if e['disabled'] else ''}")

def click_text(pg,txt,timeout=3000):
    try:
        pg.get_by_text(txt,exact=False).first.click(timeout=timeout); time.sleep(1.2); return True  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
    except Exception as e:
        return False

def click_role(pg,name,timeout=3000):
    try:
        pg.get_by_role("button",name=name).first.click(timeout=timeout); time.sleep(1.2); return True  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
    except Exception:
        return False

def main():
    p,b,pg=connect()
    try:
        # 主聊天页(先回 new chat 基线)
        click_role(pg,"New chat"); dump(pg,"01-mainchat")
        click_role(pg,"Activity feed"); dump(pg,"02-activity")
        click_role(pg,"My stuff"); dump(pg,"03-mystuff")
        click_role(pg,"Agents & skills"); dump(pg,"04-agents")
        click_role(pg,"Mission control"); dump(pg,"05-mission")
        # 设置各子页
        click_role(pg,"Capabilities"); dump(pg,"06-capabilities")
        click_role(pg,"My computer"); dump(pg,"07-mycomputer")
        click_role(pg,"My context"); dump(pg,"08-mycontext")
        click_role(pg,"Customization"); dump(pg,"09-customization")
        # 回主聊天，探输入框工具条(+ 号菜单 / 模型下拉)
        click_role(pg,"New chat")
        # 点 + 号(Add context)看弹出菜单
        if click_role(pg,"Add context"): dump(pg,"10-addcontext-menu")
        pg.keyboard.press("Escape"); time.sleep(0.5)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        # 点模型下拉
        if click_text(pg,"Smart"): dump(pg,"11-model-menu")
        pg.keyboard.press("Escape")
        print("\n✓ 遍历完成")
    finally:
        b.close(); p.stop()

if __name__=="__main__": main()
