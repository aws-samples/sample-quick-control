#!/usr/bin/env python3
"""quick_ctl.py — 全功能控制本机 Amazon Quick Desktop（Electron + CDP）。

一律用: uv run --with playwright python quick_ctl.py <命令> [参数]
（首次会自动装 playwright；建议先 `uv run --with playwright python -m playwright install chromium` 一次。）

━━━ 连接/状态 ━━━
  ensure                     确保 Quick 带调试端口运行（未开则带 --remote-debugging-port 重启）
  focus                      把 Amazon Quick 窗口前置到前台（OS 级激活，非 CDP）
  status                     JSON 打印连接/URL/模型
  status-all [--chats A B..] JSON 打印每个侧栏对话的状态(看板用；省略 --chats 则全量)
  screenshot [路径]          截图（默认 /tmp/quick.png）
  map [路径]                 dump 当前界面所有可交互元素（建选择器/排错用）

━━━ 对话（最常用）━━━
  send "<文本>" [--no-wait]  输入并发送；默认等生成结束并回读末尾
  ask "<文本>"               = send（等回复）
  type "<文本>"              只输入不发送（现场演示：把词打进去给观众看）
  clear-input                清空输入框
  read [--full]              读当前对话消息（--full 打印全部可见文字）
  stop                       停止正在生成（点 Stop）
  new-chat                   开新对话
  regenerate                 重新生成上一条回复(New conversation/重试)

━━━ 历史/会话 ━━━
  list-chats                 列出左侧 Recents 历史对话
  open-chat "<关键词>"       按标题打开历史对话
  delete-chat "<关键词>"     删除指定历史对话（危险，需 --yes）
  search-chats "<词>"        搜索对话
  export                     导出当前对话

━━━ 模型/参数 ━━━
  set-model <Fast|Balanced|Smart>   切换模型质量
  set-effort <Low|Med|High>         切换思考强度（Smart 下）
  set-mode <Quick|Agent|...>        切换左上模式下拉

━━━ 上下文/附件（+ 号菜单）━━━
  attach <文件路径>          上传本地文件
  add-folder                 选择文件夹（触发系统选择器）
  add-space                  打开 Spaces 选择
  web-search-toggle          开/关 Web search 上下文

━━━ 导航 ━━━
  nav <New chat|Activity feed|My stuff|Agents & skills|Mission control>
  settings <Capabilities|My computer|My context|Customization>
  click "<可见文字>"         点任意含该文字的按钮
  click-role "<label>"       按 aria-label 精确点按钮

━━━ 各功能区动作 ━━━
  feed [--ask "<问题>"]      Activity feed：列出条目 / 就 feed 提问
  feed-done "<条目关键词>"   把 feed 条目标记为 done
  agents [--search "<词>"]   Agents & skills：列出/搜索 agent
  run-agent "<agent名>"      在新对话里 @ 该 agent
  mission [--filter All|Needs input|Schedules]   Mission Control 运行历史
  connectors [--search "<词>"]   Capabilities：列出连接器
  artifacts                  My stuff：列出生成的交付物

━━━ 逃生舱 ━━━
  eval "<js>"                页面内执行 JS 返回结果
  wait-idle [超时秒]         等生成结束

环境变量: QUICK_CDP_PORT（默认 9333）
"""
import sys, os, time, json, subprocess

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


PORT = os.environ.get("QUICK_CDP_PORT", "9333")
CDP = f"http://127.0.0.1:{PORT}"
APP = "/Applications/Amazon Quick.app/Contents/MacOS/Amazon Quick"
APP_NAME = "Amazon Quick"
PH = "Ask a question"
# 需要人工介入的审批/许可按钮词(英文小写,因扫描时统一转小写;中文无大小写)
NEEDS_INPUT_TOKENS = ("allow","approve","continue","grant","允许","授权","继续","同意","确认")
# 选项卡(choice card)等待态的"跳过"按钮词:真机确认 agent 等待时渲染为一组可用 radio + Skip 按钮,无 Allow/Approve
SKIP_TOKENS = ("skip","跳过")

def _derive_state(generating, needs_input):
    """纯函数:由两个布尔推导对话状态(优先级:需输入 > 生成中 > 完成)。无浏览器/无 I/O。"""
    return "needs_input" if needs_input else "thinking" if generating else "done"

# ---------- 连接底座 ----------
def _http_ok():
    import urllib.request
    try:
        urllib.request.urlopen(f"{CDP}/json/version", timeout=2).read(); return True
    except Exception:
        return False

def ensure():
    if _http_ok():
        print(f"✓ Quick 已在调试模式 (port {PORT})"); return
    if subprocess.run(["pgrep","-f","MacOS/Amazon Quick"],capture_output=True).returncode==0:
        print("重启 Quick 以开调试端口..."); subprocess.run(["killall",APP_NAME],capture_output=True); time.sleep(2)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
    subprocess.Popen([APP,f"--remote-debugging-port={PORT}"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    for _ in range(25):
        time.sleep(1)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        if _http_ok(): print(f"✓ 已带调试端口启动 (port {PORT})"); return
    print("✗ 无法连接 CDP",file=sys.stderr); sys.exit(1)

def focus():
    """把 Amazon Quick 窗口前置到前台(OS 级激活,非 CDP)。
    用 open -a(无需自动化授权权限;osascript activate 需要 Automation 权限)。"""
    try:
        r = subprocess.run(["open", "-a", APP_NAME], capture_output=True)
    except Exception as e:
        print(f"✗ 无法前置 Amazon Quick: {e}", file=sys.stderr); sys.exit(1)
    if r.returncode != 0:
        print(f"✗ 无法前置 Amazon Quick (open 退出码 {r.returncode})", file=sys.stderr); sys.exit(1)
    print("✓ 已前置 Amazon Quick")

def _page():
    from playwright.sync_api import sync_playwright
    if not _http_ok():
        print("✗ 未在调试模式，先跑 ensure",file=sys.stderr); sys.exit(1)
    pw = sync_playwright().start()
    b = pw.chromium.connect_over_cdp(CDP)
    pg=None
    for c in b.contexts:
        for page in c.pages:
            try:
                if "Amazon Quick" in (page.title() or ""): pg=page;break
            except Exception: pass
        if pg: break
    if pg is None: pg=b.contexts[0].pages[0]
    return pw,b,pg

def _inp(pg): return pg.get_by_placeholder(PH, exact=False)
def _txt(pg): return pg.evaluate("()=>document.body.innerText")

MAPJS = r"""
() => {
  const vis=el=>{const r=el.getBoundingClientRect();const s=getComputedStyle(el);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none';};
  const pick=el=>({tag:el.tagName.toLowerCase(),role:el.getAttribute('role')||'',aria:el.getAttribute('aria-label')||'',testid:el.getAttribute('data-testid')||'',ph:el.getAttribute('placeholder')||'',title:el.getAttribute('title')||'',text:(el.innerText||'').trim().slice(0,45),disabled:el.disabled||el.getAttribute('aria-disabled')==='true'||false,box:(()=>{const r=el.getBoundingClientRect();return[Math.round(r.x),Math.round(r.y)];})()});
  const sel='button,[role=button],[role=tab],[role=menuitem],[role=option],[role=switch],[role=checkbox],a[href],[contenteditable=true],textarea,input,select,[data-testid]';
  const out=[],seen=new Set();
  document.querySelectorAll(sel).forEach(el=>{if(vis(el)){const p=pick(el);const k=(p.aria||p.testid||p.ph||p.title||p.text)+'|'+p.box.join(',');if((p.aria||p.testid||p.ph||p.title||p.text||p.role)&&!seen.has(k)){seen.add(k);out.push(p);}}});
  return {url:location.href,title:document.title,headings:[...document.querySelectorAll('h1,h2,h3,h4')].filter(vis).map(h=>h.innerText.trim().slice(0,50)),elements:out};
}
"""

# ---------- 命令 ----------
def status():
    pw,b,pg=_page()
    try:
        lines=[l.strip() for l in _txt(pg).split("\n") if l.strip()]
        gen=_generating(pg); ni=_needs_input(pg)  # 对同一个已打开的 pg 读,不另开连接
        print(json.dumps({"connected":True,"port":PORT,"url":pg.url[:75],
            "model":next((l for l in lines if l in("Quick","Smart","Fast","Balanced")),"?"),
            "generating":gen,"needs_input":ni,"state":_derive_state(gen,ni)},ensure_ascii=False))
    finally: b.close();pw.stop()

def screenshot(path=_out("quick.png")):
    pw,b,pg=_page()
    try: pg.screenshot(path=path); print(f"✓ 截图 → {path}")
    finally: b.close();pw.stop()

def do_map(path=_out("quick_screen.json")):
    pw,b,pg=_page()
    try:
        d=pg.evaluate(MAPJS); json.dump(d,open(path,"w"),ensure_ascii=False,indent=1)
        print(f"URL:{d['url'][:60]} headings={d['headings'][:4]}")
        seen=set()
        for e in d['elements']:
            lab=e['aria'] or e['ph'] or e['testid'] or e['text'] or e['title'] or e['role']
            if lab and lab not in seen:
                seen.add(lab); print(f"  <{e['tag']}{'/'+e['role'] if e['role'] else ''}> {lab!r}{' [x]' if e['disabled'] else ''}")
        print(f"→ {path}")
    finally: b.close();pw.stop()

# ★ 待真机复核(BUG 2b):用户曾在生成进行中观察到 status 返回 state:done,
#   说明此构建对"进行中"控件的标注可能不同于 Stop / Stop generating。
#   但确切信号(aria-label 文案、禁用态 composer 语义、"停止"中文变体)无法在死端口 CI 下观测,
#   盲目放宽匹配会误伤 _wait_idle/wait_done(二者都依赖 _generating),故此处【刻意】维持原判据不变,
#   待真机复核(见 .agents/tasks/verification.md 的"待真机验证"小节)后再按实测信号收窄/放宽。
def _generating(pg):
    """是否仍在生成：有 Stop 按钮，或页面末尾还停在 Thinking/Thought(无正文)。"""
    if pg.get_by_role("button",name="Stop").count()>0: return True
    if pg.get_by_text("Stop",exact=True).count()>0: return True
    # 输入框被禁用通常表示生成中
    try:
        if pg.get_by_role("button",name="Stop generating").count()>0: return True
    except Exception: pass
    return False

def _needs_input(pg):
    """是否在等待人工介入。单次 CDP 读(不另开连接),两条判据任一命中即 True:
    1) 可见的许可/审批按钮:扫 button/[role=button],(aria-label+innerText) 转小写后匹配 NEEDS_INPUT_TOKENS;
    2) 选项卡等待态(真机确认):存在可用的 button[role=radio] 且同时有一个文字含 SKIP_TOKENS 的可见按钮,
       —— 这种"多选项 + Skip、无 Allow/Approve"的形态,仅靠判据1 会漏判成 done。"""
    try:
        return bool(pg.evaluate("([toks,skips])=>{const vis=el=>{const r=el.getBoundingClientRect();const s=getComputedStyle(el);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none';};const btns=[...document.querySelectorAll('button,[role=button]')].filter(vis);if(btns.some(el=>{const t=((el.getAttribute('aria-label')||'')+' '+(el.innerText||'')).toLowerCase();return toks.some(k=>t.includes(k));}))return true;const dis=el=>el.disabled||el.getAttribute('aria-disabled')==='true';const radio=[...document.querySelectorAll('button[role=radio]')].some(el=>vis(el)&&!dis(el));const skip=btns.some(el=>{const t=((el.getAttribute('aria-label')||'')+' '+(el.innerText||'')).toLowerCase();return skips.some(k=>t.includes(k));});return radio&&skip;}", [list(NEEDS_INPUT_TOKENS), list(SKIP_TOKENS)]))
    except Exception:
        return False

def _wait_idle(pg, before_len, timeout=240):
    """等生成结束：文字稳定 N 轮 + 无 Stop 按钮 + 尾部不再是 Thinking。
    思考停顿会让文字暂时不变,故要求更长稳定窗口(4轮≈6s)且不在生成态。"""
    stable=0; last=""
    dl=time.time()+timeout
    while time.time()<dl:
        time.sleep(1.5); cur=_txt(pg)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        gen=_generating(pg)
        if cur==last and not gen: stable+=1
        else: stable=0; last=cur
        if stable>=4 and len(cur)>before_len: break
    return last

def wait_done(timeout=300, start_grace=45):
    """纯看 Stop 按钮判生成完成(不读文字,最可靠,适合看板等长静默 artifact)。
    阶段A:等生成启动(出现 Stop 按钮),最多等 start_grace 秒。
    阶段B:Stop 按钮连续 5 轮(≈10s)不出现 = 完成。"""
    pw,b,pg=_page()
    try:
        dl=time.time()+timeout
        started=False
        ga=time.time()+start_grace
        while time.time()<ga:
            # started 目前只作阶段A的记录,下游不读(阶段B 纯看 Stop 按钮消失计数)。
            # 保留赋值不动:是否该据此区分"从未开始生成"属行为变更,另案处理。
            if _generating(pg): started=True; break  # noqa: F841
            time.sleep(1.5)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        gone=0
        while time.time()<dl:
            time.sleep(2)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
            if _generating(pg):
                gone=0
            else:
                gone+=1
                if gone>=5:   # Stop 连续消失 ≈10s,确认完成
                    print("DONE"); return
        print("TIMEOUT")
    finally:
        b.close(); pw.stop()

def send(text, wait=True):
    pw,b,pg=_page()
    try:
        box=_inp(pg); box.click(); box.press("Meta+A"); box.press("Backspace")
        box.type(text,delay=8); time.sleep(0.3)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        before=len(_txt(pg)); box.press("Enter")
        if not wait: print("✓ 已发送(不等回复)"); return
        last=_wait_idle(pg, before)
        nl=[l for l in last.split("\n") if l.strip()]
        print("=== 对话尾部 ==="); print("\n".join(nl[-14:]))
    finally: b.close();pw.stop()

def type_only(text):
    pw,b,pg=_page()
    try:
        box=_inp(pg); box.click(); box.press("Meta+A"); box.press("Backspace"); box.type(text,delay=10)
        print(f"✓ 已输入(未发送): {text[:60]}")
    finally: b.close();pw.stop()

def clear_input():
    pw,b,pg=_page()
    try: box=_inp(pg);box.click();box.press("Meta+A");box.press("Backspace");print("✓ 已清空")
    finally: b.close();pw.stop()

def read(full=False):
    pw,b,pg=_page()
    try:
        lines=[l for l in _txt(pg).split("\n") if l.strip()]
        print("\n".join(lines if full else lines[-40:]))
    finally: b.close();pw.stop()

def stop():
    pw,b,pg=_page()
    try:
        for name in ("Stop","停止"):
            if pg.get_by_role("button",name=name).count()>0: pg.get_by_role("button",name=name).first.click();print("✓ 已停止");return
        print("(未发现进行中的生成)")
    finally: b.close();pw.stop()

def new_chat():
    """开新对话:点左栏主导航的 "Chat"(data-testid=nav-home)。真机确认此构建无全局 "New chat" 按钮,
    按 New-chat 名称找只会命中每个文件夹里的 "New chat in folder",会误把焦点落到顶部文件夹。
    依次尝试三个独立定位器(各自 .count() 判定,不用 .or_() 合并,避免 strict-mode 命中多元素而崩):
      1) [data-testid=nav-home] —— 命中则点 .first;
      2) 否则精确 role=button name="Chat"(exact,不子串误伤)—— 命中则点 .first;
      3) 否则 JS 兜底:点第一个 button[data-testid=nav-home],或去空白后文字恰为 "Chat" 的按钮。
    三者皆空则中文 stderr 提示 + sys.exit(1)(不抛未捕获 traceback);走 try 内以保证 finally 关浏览器。"""
    pw,b,pg=_page()
    try:
        home=pg.locator("[data-testid=nav-home]")
        chat=pg.get_by_role("button",name="Chat",exact=True)
        if home.count()>=1: home.first.click()
        elif chat.count()>=1: chat.first.click()
        elif not pg.evaluate("""()=>{const b=document.querySelector('button[data-testid=nav-home]')||[...document.querySelectorAll('button')].find(x=>(x.innerText||'').trim()==='Chat');if(b){b.click();return true;}return false;}"""):
            print("✗ 未找到 Chat 导航按钮",file=sys.stderr); sys.exit(1)
        time.sleep(0.6); print("✓ 新对话 (Chat)")  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
    finally: b.close();pw.stop()

def regenerate():
    pw,b,pg=_page()
    try:
        pg.get_by_role("button",name="New conversation").or_(pg.get_by_text("Retry",exact=False)).first.click()
        print("✓ 已触发重新生成")
    finally: b.close();pw.stop()

def list_chats():
    pw,b,pg=_page()
    try:
        items=pg.evaluate("""()=>Array.from(document.querySelectorAll('[role=option]')).map(e=>(e.getAttribute('aria-label')||e.innerText||'').trim()).filter(Boolean)""")
        print("\n".join(dict.fromkeys(items)) if items else "(无历史对话)")
    finally: b.close();pw.stop()

# JS 兜底:在 [role=option] 行里点第一个 aria-label/innerText(去空白)含 kw 的行(点行本身,不点标题 span)。
# 镜像 _act_in/open_chat_cycle 的 JS-click 风格;命中返回 true,否则 false。
OPEN_CHAT_FALLBACK_JS = r"""
(kw) => {
  const k=(kw||'').trim();
  const opts=[...document.querySelectorAll('[role=option]')];
  const hit=opts.find(o=>(((o.getAttribute('aria-label')||'')+' '+(o.innerText||'')).trim()).includes(k));
  if(hit){hit.click();return true;}
  return false;
}
"""

def open_chat(kw):
    """按标题打开历史对话:始终点整行([role=option]),绝不点标题 span,绝不触发 strict mode。
    依次尝试三个独立定位器(各自 .count() 判定,不用 .or_() 合并,避免 strict-mode 命中多元素而崩):
      1) 精确 role=option(exact)—— 命中则点 .first;
      2) 否则子串 role=option —— 命中则点 .first;
      3) 否则 JS 兜底:遍历 [role=option] 点第一个标题含 kw 的行。
    三者皆空则打印中文未找到提示到 stderr 并 sys.exit(1)(不抛未捕获 traceback);stderr/exit 走 try 内以保证 finally 关浏览器。"""
    pw,b,pg=_page()
    try:
        exact=pg.get_by_role("option",name=kw,exact=True)
        contains=pg.get_by_role("option",name=kw)
        if exact.count()>=1: exact.first.click()
        elif contains.count()>=1: contains.first.click()
        elif not pg.evaluate(OPEN_CHAT_FALLBACK_JS, kw):
            print(f"✗ 未找到对话『{kw}』",file=sys.stderr); sys.exit(1)
        time.sleep(0.8); print(f"✓ 打开『{kw}』")  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
    finally: b.close();pw.stop()

def _slugify(s):
    """把对话标题转成 URL slug 风格:转小写、非字母数字(含中文)→连字符、去首尾连字符。
    与 Quick 的 file:///chat/<id>/<slug> 对齐,用于反推当前激活对话。"""
    out=[]; prev_dash=True  # 以 True 起手可吃掉前导连字符
    for ch in s.lower():
        if ch.isalnum(): out.append(ch); prev_dash=False
        elif not prev_dash: out.append("-"); prev_dash=True
    return "".join(out).strip("-")

def _active_index(names, url):
    """从 URL 末段 slug 反推当前激活对话在 names 里的下标(无匹配返回 -1)。纯函数,无 I/O。
    把每个标题 slugify 后与 URL 末段 slug 做 contains/startswith 容错匹配(slug 可能被截断)。"""
    tail=(url.rstrip("/").split("/")[-1] or "").lower()  # URL 末段 slug
    if not tail: return -1
    for i,nm in enumerate(names):
        sg=_slugify(nm)
        if sg and (tail.startswith(sg) or sg.startswith(tail) or sg in tail or tail in sg):
            return i
    return -1

def open_chat_cycle(direction):
    """在左侧 [role=option] 历史列表里按 direction(next/prev)循环切换,支持回绕。
    单次 page.evaluate 返回有序名单与当前页 URL;激活项由 URL 推导(见下)。
    ★ 激活项判据改用 pg.url(真机确认):侧栏行并无 aria-selected / selected 类标记,
      唯一可靠信号是地址栏 file:///chat/<id>/<slug>。做法:把每个选项标题 slugify 后与
      URL 末段 slug 做 contains/startswith 容错匹配(slug 可能被截断),命中即激活项。
      仅当没有任何选项匹配 URL slug 时才降级:next→第一条,prev→最后一条,并打印中文提示。"""
    pw,b,pg=_page()
    try:
        d=pg.evaluate("""()=>{const opts=[...document.querySelectorAll('[role=option]')];const names=opts.map(e=>(e.getAttribute('aria-label')||e.innerText||'').trim());return{names:names.filter(Boolean),url:location.href};}""")
        names=d["names"]; n=len(names)
        if n==0: print("(无历史对话)"); return
        active=_active_index(names, d["url"])  # 由 URL slug 推导激活项
        if active==-1:
            print("⚠ 未能从 URL 识别当前激活对话,降级到边界项")
            idx=0 if direction=="next" else n-1
        else:
            idx=(active+1)%n if direction=="next" else (active-1)%n
        kw=names[idx]
        exact=pg.get_by_role("option",name=kw,exact=True)
        contains=pg.get_by_role("option",name=kw)
        if exact.count()>=1: exact.first.click()
        elif contains.count()>=1: contains.first.click()
        elif not pg.evaluate(OPEN_CHAT_FALLBACK_JS, kw):
            print(f"✗ 未找到对话『{kw}』",file=sys.stderr); sys.exit(1)
        time.sleep(0.8)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        print(f"✓ 切换到『{kw}』")
    finally: b.close();pw.stop()

# 侧栏行扫描 JS:优先 .history-item,拿每行 [role=option] 标题 + 是否有 span.approval-dot;降级到 [role=option]。
# 另【附加】采集每行是否报告"激活"(sel):aria-selected==='true' 或 box className 含 \bactive\b。
# 这是加法式扩展(JSON 不删/改既有键):当前构建侧栏行据真机 ground truth 并无此标记,
# 故 sel 恒 false、不改变现有行为;若未来构建补上该标记,_dom_active_index 便可据此优先判激活项。
STATUS_ALL_JS = r"""
() => {
  const nm=o=>((o.getAttribute('aria-label')||o.innerText||'').trim());
  const act=(o,box)=>(o&&o.getAttribute('aria-selected')==='true')||/\b(active)\b/.test((box&&box.className)||'');
  const rows=[];
  const items=[...document.querySelectorAll('.history-item')];
  if(items.length){
    items.forEach(it=>{const o=it.querySelector('[role=option]');const name=o?nm(o):(it.innerText||'').trim();if(name)rows.push({name,dot:!!it.querySelector('span.approval-dot'),sel:act(o,it)});});
  }else{
    [...document.querySelectorAll('[role=option]')].forEach(o=>{const name=nm(o);if(!name)return;const box=o.closest('.history-item')||o.parentElement;rows.push({name,dot:!!(box&&box.querySelector('span.approval-dot')),sel:act(o,box)});});
  }
  return {rows,url:location.href};
}
"""

def _dom_active_index(rows):
    """纯函数:若【且仅若】恰有一行 sel 为真,返回其下标;零行或多于一行报告 sel 为真则返回 -1(有歧义 → 交回 URL-slug 判据)。无 I/O。
    rows 为 [{"name","dot","sel"},...](sel 缺省按假处理)。"""
    idxs=[i for i,r in enumerate(rows) if r.get("sel")]
    return idxs[0] if len(idxs)==1 else -1

def _chat_state(dot, is_active, active_state):
    """纯函数:单行最终状态。激活行用传入的 active_state;非激活行有待处理点→attention,否则 idle。"""
    return active_state if is_active else ("attention" if dot else "idle")

def _assemble_chats(rows, active_idx, active_state, chats):
    """纯函数:组装输出的 chats 列表。rows 为浏览器返回的 [{"name","dot"},...]。
    chats 为 None 时按侧栏顺序全量输出(found 恒 True);否则按请求顺序精确匹配(非子串),
    缺失的名字输出 found:False、state idle、active False。无浏览器/无 I/O。"""
    if chats is None:
        return [{"name":r["name"],"state":_chat_state(r["dot"],i==active_idx,active_state),
                 "active":i==active_idx,"found":True} for i,r in enumerate(rows)]
    out=[]
    for req in chats:
        idx=next((i for i,r in enumerate(rows) if r["name"].strip()==req.strip()),-1)  # 精确匹配
        if idx==-1: out.append({"name":req,"state":"idle","active":False,"found":False})
        else: out.append({"name":rows[idx]["name"],"state":_chat_state(rows[idx]["dot"],idx==active_idx,active_state),
                          "active":idx==active_idx,"found":True})
    return out

def status_all(chats=None):
    """一次 CDP 连接 + 一次主 page.evaluate,报告每个侧栏对话的状态(供 Stream Deck 看板)。
    激活对话由 URL slug 推导,其状态走 _derive_state(读已打开的 pg,不另开连接);
    其余对话按有无 span.approval-dot 映射 attention/idle。"""
    pw,b,pg=_page()
    try:
        d=pg.evaluate(STATUS_ALL_JS)
        rows=[r for r in d["rows"] if r.get("name")]  # 过滤空名
        # 优先用 DOM-active 标记(恰一行报告 sel 时);无/歧义则降级到 URL-slug(既有行为,不退化)。
        active_idx=_dom_active_index(rows)
        if active_idx==-1: active_idx=_active_index([r["name"] for r in rows], d["url"])
        active_state=_derive_state(_generating(pg), _needs_input(pg))  # 仅激活项读 pg,无新连接
        active_name=rows[active_idx]["name"] if active_idx>=0 else None
        out=_assemble_chats(rows, active_idx, active_state, chats)
        print(json.dumps({"connected":True,"active":active_name,"chats":out},ensure_ascii=False))
    finally: b.close();pw.stop()

def delete_chat(kw, yes=False):
    if not yes: print("⚠ 删除对话不可逆，需加 --yes 确认",file=sys.stderr); sys.exit(1)
    pw,b,pg=_page()
    try:
        row=pg.get_by_role("option",name=kw).first; row.hover()
        pg.get_by_role("button",name="Delete").first.click(); time.sleep(0.4)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        # 确认弹窗
        for c in ("Delete","确认","Confirm"):
            if pg.get_by_role("button",name=c).count()>0: pg.get_by_role("button",name=c).last.click();break
        print(f"✓ 已删除『{kw}』")
    finally: b.close();pw.stop()

def search_chats(q):
    pw,b,pg=_page()
    try:
        pg.get_by_role("button",name="Search chats").first.click(); time.sleep(0.5)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        pg.keyboard.type(q,delay=15); time.sleep(1)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        print(_txt(pg)[:1500])
    finally: b.close();pw.stop()

def export():
    pw,b,pg=_page()
    try: pg.get_by_role("button",name="Export conversation").first.click();time.sleep(0.5);print("✓ 已触发导出")  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
    finally: b.close();pw.stop()

def _open_menu_pick(pg, opener_text, item_text):
    """通用：点开某下拉/菜单再选项。"""
    pg.get_by_text(opener_text,exact=True).first.click(); time.sleep(0.5)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
    pg.get_by_text(item_text,exact=False).first.click(); time.sleep(0.4)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等

def set_model(name):
    pw,b,pg=_page()
    try:
        pg.get_by_role("button",name="Smart").or_(pg.get_by_role("button",name="Fast")).or_(pg.get_by_role("button",name="Balanced")).first.click();time.sleep(0.5)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        pg.get_by_text(name,exact=False).first.click(); print(f"✓ 模型 → {name}")
    finally: b.close();pw.stop()

def set_effort(level):
    pw,b,pg=_page()
    try:
        pg.get_by_role("button",name="Smart").first.click(); time.sleep(0.5)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        pg.get_by_role("button",name=level,exact=True).first.click(); print(f"✓ 思考强度 → {level}")
    finally: b.close();pw.stop()

def set_mode(name):
    pw,b,pg=_page()
    try:
        pg.get_by_role("button",name="Quick",exact=True).first.click(); time.sleep(0.5)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        pg.get_by_text(name,exact=False).first.click(); print(f"✓ 模式 → {name}")
    finally: b.close();pw.stop()

def attach(path):
    path=os.path.abspath(os.path.expanduser(path))
    pw,b,pg=_page()
    try:
        with pg.expect_file_chooser(timeout=8000) as fc:
            pg.get_by_role("button",name="Add context").first.click(); time.sleep(0.3)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
            pg.get_by_text("Upload files",exact=False).first.click()
        fc.value.set_files(path); time.sleep(0.5); print(f"✓ 已上传 {path}")  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
    finally: b.close();pw.stop()

def add_context_item(item):
    pw,b,pg=_page()
    try:
        pg.get_by_role("button",name="Add context").first.click(); time.sleep(0.4)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        pg.get_by_text(item,exact=False).first.click(); print(f"✓ Add context → {item}")
    finally: b.close();pw.stop()

def nav(label):
    pw,b,pg=_page()
    try: pg.get_by_role("button",name=label).first.click();time.sleep(0.6);print(f"✓ 导航: {label}")  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
    finally: b.close();pw.stop()

def _click_setting(pg, sub):
    """点 Settings 子项。这些 button.settings-sub-item 被 chat-section 覆盖，
    普通/force click 会被遮挡，必须用 JS click。"""
    btn=pg.locator("button.settings-sub-item", has_text=sub).first
    if btn.count()==0:
        pg.get_by_role("button",name="Settings").first.click(); time.sleep(0.7)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        btn=pg.locator("button.settings-sub-item", has_text=sub).first
    btn.evaluate("el => el.click()"); time.sleep(0.9)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等

def settings(sub):
    pw,b,pg=_page()
    try:
        _click_setting(pg, sub); print(f"✓ Settings → {sub} ({pg.url.split('/')[-1] or 'root'})")
    finally: b.close();pw.stop()

def click(text):
    pw,b,pg=_page()
    try: pg.get_by_text(text,exact=False).first.click();time.sleep(0.4);print(f"✓ 点: {text}")  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
    finally: b.close();pw.stop()

def click_role(label):
    pw,b,pg=_page()
    try: pg.get_by_role("button",name=label).first.click();time.sleep(0.4);print(f"✓ 点: {label}")  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
    finally: b.close();pw.stop()

def feed(ask=None):
    pw,b,pg=_page()
    try:
        pg.get_by_role("button",name="Activity feed").first.click(); time.sleep(1)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        if ask:
            pg.get_by_role("button",name="Ask Quick about your feed").first.click(); time.sleep(0.5)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
            box=_inp(pg); box.click(); box.type(ask,delay=8); box.press("Enter")
            print(_wait_idle(pg,len(_txt(pg)))[-800:])
        else:
            print(_txt(pg)[:1500])
    finally: b.close();pw.stop()

def feed_done(kw):
    pw,b,pg=_page()
    try:
        pg.get_by_role("button",name="Activity feed").first.click(); time.sleep(1)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        # 找到含 kw 的条目附近的 Mark as done
        pg.get_by_role("button",name="Mark as done").first.click(); print("✓ 标记完成(第一条)")
    finally: b.close();pw.stop()

def agents(search=None):
    pw,b,pg=_page()
    try:
        pg.get_by_role("button",name="Agents & skills").first.click(); time.sleep(1)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        if search:
            pg.get_by_placeholder("Search agents",exact=False).first.fill(search); time.sleep(1)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        print(_txt(pg)[:1500])
    finally: b.close();pw.stop()

def run_agent(name):
    pw,b,pg=_page()
    try:
        pg.get_by_role("button",name="New chat").first.click(); time.sleep(0.5)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        box=_inp(pg); box.click(); box.type("@"+name,delay=25); time.sleep(1)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        pg.keyboard.press("Enter")  # 选中第一个匹配
        print(f"✓ 已 @{name}（可继续 send 指令）")
    finally: b.close();pw.stop()

def mission(flt=None):
    pw,b,pg=_page()
    try:
        pg.get_by_role("button",name="Mission control").first.click(); time.sleep(1)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        if flt: pg.get_by_role("button",name=flt,exact=True).first.click(); time.sleep(0.6)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        print(_txt(pg)[:1800])
    finally: b.close();pw.stop()

def connectors(search=None):
    pw,b,pg=_page()
    try:
        _click_setting(pg, "Capabilities")
        if search: pg.get_by_placeholder("Search connectors",exact=False).first.fill(search); time.sleep(1)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        print(_txt(pg)[:1500])
    finally: b.close();pw.stop()

def artifacts():
    pw,b,pg=_page()
    try:
        pg.get_by_role("button",name="My stuff").first.click(); time.sleep(1)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        print(_txt(pg)[:1500])
    finally: b.close();pw.stop()

# ───────── 消息操作（悬停消息后出现的操作栏）─────────
def _hover_last_quick(pg):
    """悬停到最后一条 Quick(assistant) 回复气泡上，露出 .message-action-bar 操作栏。"""
    try:
        pg.locator(".message.assistant").last.hover(timeout=5000); time.sleep(0.5); return True  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
    except Exception:
        try: pg.locator(".message.assistant").last.scroll_into_view_if_needed(); pg.locator(".message.assistant").last.hover(); time.sleep(0.5); return True  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        except Exception: return False

# 实测消息操作栏：user=[Copy,Reply in thread,Edit message] assistant=[Agent actions,Copy,Reply in thread,Add reaction]
def _act_in(pg, sel, label):
    """在指定消息气泡内点操作按钮(用 JS click 规避 hover 丢失)。"""
    return pg.locator(sel).last.evaluate(
        f"""el=>{{const b=[...el.querySelectorAll('button')].find(x=>(x.getAttribute('aria-label')||'').includes({label!r}));if(b){{b.click();return true;}}return false;}}""")

def msg_copy():
    pw,b,pg=_page()
    try: print("✓ 已复制最后一条回复" if _act_in(pg,".message.assistant","Copy") else "✗ 未找到")
    finally: b.close();pw.stop()

def msg_react():
    pw,b,pg=_page()
    try: print("✓ 已打开表情反应" if _act_in(pg,".message.assistant","Add reaction") else "✗ 未找到"); time.sleep(0.4)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
    finally: b.close();pw.stop()

def msg_reply():
    pw,b,pg=_page()
    try: print("✓ 已在线程回复最后一条" if _act_in(pg,".message.assistant","Reply in thread") else "✗ 未找到"); time.sleep(0.4)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
    finally: b.close();pw.stop()

def msg_edit():
    """编辑用户自己最后一条消息(进入可编辑态)。"""
    pw,b,pg=_page()
    try:
        ok=_act_in(pg,".message.user","Edit message"); time.sleep(0.5)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        print("✓ 已进入编辑态" if ok else "✗ 未找到 Edit message")
    finally: b.close();pw.stop()

def msg_more():
    """assistant 消息的 Agent actions 菜单(重生成/分享等)。"""
    pw,b,pg=_page()
    try:
        _act_in(pg,".message.assistant","Agent actions"); time.sleep(0.6)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        items=pg.evaluate("""()=>[...document.querySelectorAll('[role=menuitem]')].map(e=>(e.innerText||'').trim()).filter(Boolean)""")
        print("Agent actions 菜单:", items if items else "(无弹出，可能需重试)")
    finally: b.close();pw.stop()

# ───────── 顶栏：任务列表 / 会话标签 ─────────
def task_list():
    pw,b,pg=_page()
    try: pg.get_by_role("button",name="Task list").first.click(); time.sleep(0.8); print(_txt(pg)[:1500])  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
    finally: b.close();pw.stop()

def session_tabs():
    pw,b,pg=_page()
    try:
        pg.get_by_role("button",name="Session tabs").first.click(); time.sleep(0.6)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        print(_txt(pg)[:1200])
    finally: b.close();pw.stop()

# ───────── My computer：本地文件夹 ─────────
def list_folders():
    pw,b,pg=_page()
    try:
        _click_setting(pg,"My computer")
        print(_txt(pg)[:1500])
    finally: b.close();pw.stop()

def add_folder_dialog():
    pw,b,pg=_page()
    try:
        _click_setting(pg,"My computer")
        pg.get_by_role("button",name="Add Folder").first.click(); time.sleep(0.8)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        print("✓ 已触发 Add Folder（系统文件夹选择器已弹出，需手动选或用 folder-pick）")
    finally: b.close();pw.stop()

def remove_folder():
    pw,b,pg=_page()
    try:
        _click_setting(pg,"My computer")
        pg.get_by_role("button",name="Remove folder").first.click(); time.sleep(0.5); print("✓ 已移除第一个文件夹")  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
    finally: b.close();pw.stop()

# ───────── Capabilities：连接器 ─────────
def refresh_connections():
    pw,b,pg=_page()
    try:
        _click_setting(pg,"Capabilities")
        pg.get_by_role("button",name="Refresh connections").first.click(); time.sleep(1); print("✓ 已刷新连接")  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
    finally: b.close();pw.stop()

# ───────── My context：知识图谱 / 记忆 ─────────
def context_graph(search=None):
    pw,b,pg=_page()
    try:
        _click_setting(pg,"My context")
        if search:
            pg.get_by_placeholder("Search entities",exact=False).first.fill(search); time.sleep(1)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        print(_txt(pg)[:1500])
    finally: b.close();pw.stop()

def context_memory():
    pw,b,pg=_page()
    try:
        _click_setting(pg,"My context")
        pg.get_by_role("tab",name="Memory").first.click(); time.sleep(1)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        print(_txt(pg)[:1500])
    finally: b.close();pw.stop()

def refresh_graph():
    pw,b,pg=_page()
    try:
        _click_setting(pg,"My context")
        # graph 标签下是 "Refresh graph"，Memory 标签下是 "Refresh memories"
        for name in ("Refresh graph","Refresh memories"):
            if pg.get_by_role("button",name=name).count()>0:
                pg.get_by_role("button",name=name).first.click(); time.sleep(1); print(f"✓ {name}"); return  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        print("(未找到刷新按钮，可能当前标签无此操作)")
    finally: b.close();pw.stop()

# ───────── Customization：主题 / feed / 偏好 ─────────
def set_theme(name):
    pw,b,pg=_page()
    try:
        _click_setting(pg,"Customization")
        pg.get_by_role("button",name=name,exact=False).first.click(); time.sleep(0.5); print(f"✓ 主题 → {name}")  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
    finally: b.close();pw.stop()

def set_feed_interval(val):
    pw,b,pg=_page()
    try:
        _click_setting(pg,"Customization")
        pg.locator("select").filter(has_text="Every").first.select_option(label=val); time.sleep(0.4); print(f"✓ feed 频率 → {val}")  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
    finally: b.close();pw.stop()

def set_send_key(val):
    pw,b,pg=_page()
    try:
        _click_setting(pg,"Customization")
        pg.locator("select").filter(has_text="Enter").first.select_option(label=val); time.sleep(0.4); print(f"✓ 发送键 → {val}")  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
    finally: b.close();pw.stop()

def set_browser(name):
    pw,b,pg=_page()
    try:
        _click_setting(pg,"Customization")
        pg.get_by_role("radio",name=name,exact=False).first.click(); time.sleep(0.4); print(f"✓ 自动化浏览器 → {name}")  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
    finally: b.close();pw.stop()

def set_response_pref(text):
    pw,b,pg=_page()
    try:
        _click_setting(pg,"Customization")
        ta=pg.get_by_placeholder("Response preferences",exact=False).first
        ta.click(); ta.fill(text)
        pg.get_by_role("button",name="Save preferences").first.click(); time.sleep(0.5); print("✓ 已保存回复偏好")  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
    finally: b.close();pw.stop()

def toggle_feed_source(name):
    pw,b,pg=_page()
    try:
        _click_setting(pg,"Customization")
        pg.get_by_role("button",name=name,exact=False).first.click(); time.sleep(0.4); print(f"✓ 已切换 feed 源: {name}")  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
    finally: b.close();pw.stop()

def clear_all_data(yes=False):
    if not yes: print("⚠ Clear all data 不可逆(清空所有会话/知识图谱/凭证)，需加 --yes",file=sys.stderr); sys.exit(1)
    pw,b,pg=_page()
    try:
        _click_setting(pg,"Customization")
        pg.get_by_role("button",name="Clear all data").first.click(); time.sleep(0.5)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        print("✓ 已触发 Clear all data（如有确认弹窗需再确认）")
    finally: b.close();pw.stop()

def do_eval(js):
    pw,b,pg=_page()
    try: print(json.dumps(pg.evaluate(js),ensure_ascii=False,default=str))
    finally: b.close();pw.stop()

def wait_idle(timeout=180):
    pw,b,pg=_page()
    try: _wait_idle(pg,0,int(timeout)); print("✓ 生成结束/空闲")
    finally: b.close();pw.stop()

def _chats_arg(a):
    """解析 status-all 的多值 --chats:缺省返回 None(报告全部);否则取 --chats 之后、
    到下一个以 -- 开头的 token 或列表末尾为止的所有名字。纯列表切片,死端口下不会抛异常。"""
    if "--chats" not in a: return None
    i=a.index("--chats")+1; names=[]
    while i<len(a) and not a[i].startswith("--"): names.append(a[i]); i+=1
    return names

def main():
    if len(sys.argv)<2: print(__doc__); return
    c=sys.argv[1]; a=sys.argv[2:]
    def opt(flag): return flag in a
    def val(flag,d=None):
        return a[a.index(flag)+1] if flag in a and a.index(flag)+1<len(a) else d
    if c=="ensure": ensure()
    elif c=="focus": focus()
    elif c=="status": status()
    elif c=="status-all": status_all(_chats_arg(a))
    elif c=="screenshot": screenshot(a[0] if a and not a[0].startswith("-") else _out("quick.png"))
    elif c=="map": do_map(a[0] if a else _out("quick_screen.json"))
    elif c in ("send","ask"): send(a[0], wait=not opt("--no-wait"))
    elif c=="type": type_only(a[0])
    elif c=="clear-input": clear_input()
    elif c=="read": read(full=opt("--full"))
    elif c=="stop": stop()
    elif c=="new-chat": new_chat()
    elif c=="regenerate": regenerate()
    elif c=="list-chats": list_chats()
    elif c=="open-chat" and ("--next" in a or "--prev" in a): open_chat_cycle("next" if "--next" in a else "prev")
    elif c=="open-chat": open_chat(a[0])
    elif c=="delete-chat": delete_chat(a[0], yes=opt("--yes"))
    elif c=="search-chats": search_chats(a[0])
    elif c=="export": export()
    elif c=="set-model": set_model(a[0])
    elif c=="set-effort": set_effort(a[0])
    elif c=="set-mode": set_mode(a[0])
    elif c=="attach": attach(a[0])
    elif c=="add-folder": add_context_item("Choose a folder")
    elif c=="add-space": add_context_item("Spaces")
    elif c=="web-search-toggle": add_context_item("Web search")
    elif c=="nav": nav(a[0])
    elif c=="settings": settings(a[0])
    elif c=="click": click(a[0])
    elif c=="click-role": click_role(a[0])
    elif c=="feed": feed(ask=val("--ask"))
    elif c=="feed-done": feed_done(a[0])
    elif c=="agents": agents(search=val("--search"))
    elif c=="run-agent": run_agent(a[0])
    elif c=="mission": mission(flt=val("--filter"))
    elif c=="connectors": connectors(search=val("--search"))
    elif c=="artifacts": artifacts()
    # 消息操作
    elif c=="msg-copy": msg_copy()
    elif c=="msg-reply": msg_reply()
    elif c=="msg-edit": msg_edit()
    elif c=="msg-react": msg_react()
    elif c=="msg-more": msg_more()
    # 顶栏
    elif c=="task-list": task_list()
    elif c=="session-tabs": session_tabs()
    # My computer 本地文件夹
    elif c=="list-folders": list_folders()
    elif c=="add-folder-dialog": add_folder_dialog()
    elif c=="remove-folder": remove_folder()
    # Capabilities
    elif c=="refresh-connections": refresh_connections()
    # My context
    elif c=="context-graph": context_graph(search=val("--search"))
    elif c=="context-memory": context_memory()
    elif c=="refresh-graph": refresh_graph()
    # Customization
    elif c=="set-theme": set_theme(a[0])
    elif c=="set-feed-interval": set_feed_interval(a[0])
    elif c=="set-send-key": set_send_key(a[0])
    elif c=="set-browser": set_browser(a[0])
    elif c=="set-response-pref": set_response_pref(a[0])
    elif c=="toggle-feed-source": toggle_feed_source(a[0])
    elif c=="clear-all-data": clear_all_data(yes=opt("--yes"))
    elif c=="eval": do_eval(a[0])
    elif c=="wait-idle": wait_idle(a[0] if a else 180)
    elif c=="wait-done": wait_done(int(a[0]) if a else 300)
    else: print(f"未知命令: {c}\n{__doc__}",file=sys.stderr); sys.exit(1)

if __name__=="__main__": main()
