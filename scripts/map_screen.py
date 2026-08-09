#!/usr/bin/env python3
"""map_screen.py — dump 当前 Quick 界面所有可交互元素的稳定定位特征。
输出 JSON：每个元素的 tag/role/aria-label/text/testid/placeholder/class 关键片段 + 是否可见。
用于为全功能 skill 建可靠选择器。
用法: uv run --with playwright python map_screen.py [输出json路径]
"""
import sys, os, json
from playwright.sync_api import sync_playwright

def _out_dir() -> str:
    """默认输出目录:用户私有缓存目录(0700),而不是全局可写的 /tmp。

    ★ 为什么不用 /tmp(bandit B108,PCSR 审核项):/tmp 全局可写且路径可预测,
      多用户机器上他人可预先创建同名文件或符号链接抢占(symlink attack),
      导致我们把截图/页面结构写到攻击者能读的位置、或覆盖其它文件。
      本项目是公开 sample —— 客户会照抄这个模式,所以这里做对更重要。
    覆盖方式:环境变量 QUICK_OUT_DIR,或命令行显式传路径(接口未变)。
    """
    d = os.environ.get("QUICK_OUT_DIR") or os.path.join(
        os.path.expanduser("~"), ".cache", "quick-control")
    os.makedirs(d, mode=0o700, exist_ok=True)
    return d


def _out(name: str) -> str:
    """把一个默认文件名解析成用户私有目录下的绝对路径。"""
    return os.path.join(_out_dir(), name)


PORT=os.environ.get("QUICK_CDP_PORT","9333")

JS = r"""
() => {
  const vis = el => { const r=el.getBoundingClientRect(); const s=getComputedStyle(el);
    return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'; };
  const pick = el => ({
    tag: el.tagName.toLowerCase(),
    role: el.getAttribute('role')||'',
    aria: el.getAttribute('aria-label')||'',
    testid: el.getAttribute('data-testid')||'',
    ph: el.getAttribute('placeholder')||'',
    title: el.getAttribute('title')||'',
    text: (el.innerText||'').trim().slice(0,40),
    href: (el.getAttribute('href')||'').slice(0,40),
    disabled: el.disabled||el.getAttribute('aria-disabled')==='true'||false,
    cls: (el.className&&el.className.baseVal!==undefined?el.className.baseVal:el.className||'').toString().slice(0,50),
    box: (()=>{const r=el.getBoundingClientRect();return [Math.round(r.x),Math.round(r.y),Math.round(r.width),Math.round(r.height)];})()
  });
  const sel = 'button,[role=button],[role=tab],[role=menuitem],[role=option],[role=switch],[role=checkbox],a[href],[contenteditable=true],textarea,input,select,[data-testid],[role=link]';
  const out=[];
  document.querySelectorAll(sel).forEach(el=>{ if(vis(el)){ const p=pick(el);
    // 至少有一个可定位特征才收
    if(p.aria||p.testid||p.ph||p.title||p.text||p.role) out.push(p); }});
  return {url: location.href, title: document.title,
          headings: [...document.querySelectorAll('h1,h2,h3')].filter(vis).map(h=>h.innerText.trim().slice(0,50)),
          elements: out};
}
"""

def main():
    outpath = sys.argv[1] if len(sys.argv)>1 else _out("quick_screen.json")
    p=sync_playwright().start()
    b=p.chromium.connect_over_cdp(f"http://127.0.0.1:{PORT}")
    pg=None
    for c in b.contexts:
        for page in c.pages:
            try:
                if "Amazon Quick" in (page.title() or "") or "renderer/index" in page.url: pg=page;break
            except: pass
        if pg:break
    if not pg: pg=b.contexts[0].pages[0]
    data=pg.evaluate(JS)
    json.dump(data, open(outpath,"w"), ensure_ascii=False, indent=1)
    # 精简打印
    print(f"URL: {data['url'][:80]}")
    print(f"标题栏 headings: {data['headings']}")
    print(f"可交互元素 {len(data['elements'])} 个：")
    seen=set()
    for e in data['elements']:
        key=(e['aria'] or e['testid'] or e['ph'] or e['text'] or e['title'])
        if key in seen: continue
        seen.add(key)
        label = e['aria'] or e['ph'] or e['testid'] or e['text'] or e['title'] or e['role']
        dis = " [disabled]" if e['disabled'] else ""
        print(f"  <{e['tag']}{'/'+e['role'] if e['role'] else ''}> {label!r}{dis}")
    b.close(); p.stop()
    print(f"\n完整 JSON → {outpath}")

if __name__=="__main__": main()
