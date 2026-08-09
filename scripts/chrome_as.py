#!/usr/bin/env python3
"""chrome_as.py — 控制 Amazon Quick 网页版（quicksight.aws.amazon.com）。

自 v2.0 起底层是 **CDP/playwright**（连持久 profile Chrome 的 :9445），不再走
AppleScript。命令名与 stdout 格式与 v1.x 完全兼容——调用方（PPT repo 的 demo.py）
用 subprocess 调用并可能解析输出，故契约不变。

一律用: uv run --with playwright python chrome_as.py <命令> [参数]
前置: uv run python web_ensure.py ensure   （起带 CDP 的持久 profile Chrome 实例）
      uv run python web_ensure.py login    （在打开的窗口里手动登录一次）

━━━ 通用原语 ━━━
  tabs                        列出所有标签(编号+标题+URL)
  find <urlsub>               找含该 URL 子串的标签
  state <urlsub>              读 url/title/signedIn/h1
  buttons <urlsub>            感知:扫全页可点元素(索引+文字)
  click <urlsub> <文字>       按文字点击
  fill <urlsub> <label> <值>  按 label/placeholder/aria 填输入框
  eval <urlsub> <js>          注入任意 JS(也可从 stdin)
  evalf <urlsub> <jsfile>     从文件读 JS 执行
  screenshot [路径]           截图(v2.0 新增,CDP 带来的能力)

━━━ 读命令层(零副作用) ━━━
  goto <区>                   导航到 11 区之一(支持中文别名)
  wait-text <文字> [超时]     轮询等文字出现
  dump [urlsub] [selector]    读主内容区文本
  list [urlsub]               粗读当前区列表
  view <grid|list|table|card> 视图切换
  filter <recent|mine|favorites|shared|all>
  search <词>                 区内搜索框
  sort [列名]                 列排序
  page <first|prev|next|last|页码>
  tab <名>                    区内标签切换
  open <资产名>               打开列表项
  open-menu <资产名>          打开行级菜单(只展开)
  help / user-menu / toggle-nav / open-chat / chat-search / more-menu / dismiss-banner

━━━ 写命令层 ━━━
  create-space <名>                建空间
  delete-space <名> --confirm      删空间(高危,需 --confirm)
  create-app <描述>                建 App
  approve-prompts                  自动点构建期授权框
  app-edit <修改指令>              对话式改 App
  publish-app                      发布 App 到库
  share-app <alias>                共享 App(候选选中需人工)

━━━ 环境变量 ━━━
  QUICK_WEB_CDP_PORT   CDP 端口（默认 9445，须与 web_ensure.py 一致）
  QUICK_WEB_REGION     Quick 所在区域（默认 us-east-1）
  QUICK_WEB_ACCOUNT    你的 Quick 账户名（默认为占位符，必须按需设置）
  QUICK_WEB_BASE       直接整体覆盖起始 URL 前缀（设了则忽略上面两项）
"""
from __future__ import annotations

import json
import os
import sys
import time

PORT = os.environ.get("QUICK_WEB_CDP_PORT", "9445")
CDP = f"http://127.0.0.1:{PORT}"

# 起始 URL 前缀。账户名因人/因组织而异，代码里只留占位符，靠环境变量注入。
# 与 web_ensure.py 的同名常量是**有意重复**的（两个脚本都要能单独跑；回归测试也要求
# 端口/URL 约定在各自文件里直接可见），权威来源是这几个环境变量名。
WEB_BASE = os.environ.get(
    "QUICK_WEB_BASE",
    "https://{}.quicksight.aws.amazon.com/sn/account/{}/start/".format(
        os.environ.get("QUICK_WEB_REGION", "us-east-1"),
        os.environ.get("QUICK_WEB_ACCOUNT", "your-quick-account"),
    ),
).rstrip("/") + "/"

AREA_ALIAS = {
    "mystuff": "mystuff", "我的内容": "mystuff",
    "spaces": "spaces", "空间": "spaces",
    "research": "research", "研究": "research",
    "agents": "agents", "聊天代理": "agents", "座席": "agents",
    "apps": "apps", "应用程序": "apps",
    "flows": "flows", "流程": "flows", "流": "flows",
    "analyses": "analyses", "分析": "analyses",
    "dashboards": "dashboards", "控制面板": "dashboards", "仪表盘": "dashboards",
    "data": "data", "数据": "data",
    "personal": "folders/personal", "我的文件夹": "folders/personal",
    "shared": "folders/shared", "共享文件夹": "folders/shared",
}

# 各区文字/aria 不统一,故一个模式对多个候选。均为 v1.x 真机验证过的文案。
_VIEW_MAP = {
    "grid": ["网格视图", "流列表网格视图", "Grid view"],
    "list": ["列表视图", "List view"],
    "table": ["表格视图", "流列表表视图"],
    "card": ["卡片视图"],
}
_FILTER_MAP = {
    "recent": "最近使用", "mine": "由我创建", "favorites": "收藏夹",
    "shared": "与我共享", "all": "全部",
}
_PAGE_MAP = {
    "first": ["Go to first page", "First"],
    "prev": ["Go to previous page", "Previous page", "Previous"],
    "next": ["Go to next page", "Next page", "Next"],
    "last": ["Go to last page", "Last"],
}

CLICK_SEL = "button,[role=button],a[href],[role=tab],[role=menuitem],[role=menuitemcheckbox]"


def _as_string(py: str) -> str:
    """把 Python 字符串变成 AppleScript 字面量（转义反斜杠与双引号）。

    AppleScript 时代(v1.x)遗留：CDP 实现不再使用它，保留以兼容既有单元测试。
    """
    return '"' + py.replace("\\", "\\\\").replace('"', '\\"') + '"'


# ───────────────────────── CDP 连接底座 ─────────────────────────

def _connect():
    """连上持久 profile Chrome。返回 (pw, browser)。"""
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    try:
        b = pw.chromium.connect_over_cdp(CDP)
    except Exception as e:
        pw.stop()
        print(
            f"✗ 连不上 CDP {CDP}: {str(e)[:120]}\n"
            f"  先跑: uv run python web_ensure.py ensure",
            file=sys.stderr,
        )
        sys.exit(1)
    return pw, b


def _page(urlsub: str = "quicksight"):
    """取 url 含 urlsub 的标签。返回 (pw, browser, page)。

    不用 browser.new_page()——该实例不支持 Browser context management。
    """
    pw, b = _connect()
    for c in b.contexts:
        for p in c.pages:
            try:
                if urlsub in (p.url or ""):
                    return pw, b, p
            except Exception:
                pass
    b.close()
    pw.stop()
    print(f"未找到匹配标签: {urlsub}")
    sys.exit(0)  # 软失败 exit 0(契约)


def _close(pw, b) -> None:
    try:
        b.close()
    finally:
        pw.stop()


# ───────────────────────── 通用原语 ─────────────────────────

def tabs() -> None:
    pw, b = _connect()
    try:
        out = []
        for wi, c in enumerate(b.contexts, 1):
            for ti, p in enumerate(c.pages, 1):
                try:
                    out.append(f"{wi}-{ti} | {p.title()} :: {p.url}")
                except Exception:
                    pass
        print("\n".join(out))
    finally:
        _close(pw, b)


def find(urlsub: str) -> None:
    pw, b = _connect()
    try:
        for wi, c in enumerate(b.contexts, 1):
            for ti, p in enumerate(c.pages, 1):
                if urlsub in (p.url or ""):
                    print(f"窗口{wi} 标签{ti} :: {p.url}")
                    return
        print(f"未找到匹配标签: {urlsub}")
    finally:
        _close(pw, b)


def state(urlsub: str = "quicksight") -> None:
    pw, b, pg = _page(urlsub)
    try:
        # signedIn 判据沿用 v1.x 正则(契约的一部分),不擅自"改进"
        print(
            pg.evaluate(
                "()=>JSON.stringify({url:location.href,title:document.title,"
                "signedIn:!/signin|auth|login/i.test(location.href),"
                "h1:(document.querySelector('h1')||{}).innerText||''})"
            )
        )
    finally:
        _close(pw, b)


def buttons(urlsub: str = "quicksight") -> None:
    pw, b, pg = _page(urlsub)
    try:
        print(
            pg.evaluate(
                """() => {
  const ns = document.querySelectorAll('button,[role=button],a[href],[role=tab],[role=menuitem]');
  const out = [];
  ns.forEach((e, i) => {
    const r = e.getBoundingClientRect();
    if (r.width > 0 && r.height > 0) {
      const t = (e.getAttribute('aria-label') || e.innerText || '').replace(/\\s+/g, ' ').trim();
      if (t) out.push(i + ':' + t.slice(0, 28));
    }
  });
  return 'URL=' + location.href + '\\n共' + out.length + '个:\\n' + out.join('\\n');
}"""
            )
        )
    finally:
        _close(pw, b)


def _click_on(pg, text: str) -> str:
    """在页面上点含该文字(innerText 或 aria-label)的元素。返回契约格式字符串。"""
    return pg.evaluate(
        """(kw) => {
  const ns = document.querySelectorAll('%s');
  for (const e of ns) {
    const lab = e.getAttribute('aria-label') || e.innerText || '';
    if (lab.includes(kw)) {
      e.click();
      return 'CLICKED:' + lab.replace(/\\s+/g, ' ').trim().slice(0, 40);
    }
  }
  return 'NOTFOUND:' + kw;
}""" % CLICK_SEL,
        text,
    )


def click(urlsub: str, text: str) -> None:
    pw, b, pg = _page(urlsub)
    try:
        print(_click_on(pg, text))
    finally:
        _close(pw, b)


def fill(urlsub: str, label: str, value: str) -> None:
    pw, b, pg = _page(urlsub)
    try:
        print(
            pg.evaluate(
                """([kw, v]) => {
  const ns = document.querySelectorAll('input,textarea,[contenteditable=true]');
  for (const e of ns) {
    const m = e.getAttribute('aria-label') || e.getAttribute('placeholder') || e.name || '';
    if (m.includes(kw)) {
      e.focus();
      if (e.isContentEditable) { e.innerText = v; }
      else {
        const d = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')
               || Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value');
        if (d && d.set) d.set.call(e, v); else e.value = v;
      }
      e.dispatchEvent(new Event('input', {bubbles: true}));
      e.dispatchEvent(new Event('change', {bubbles: true}));
      return 'FILLED[' + m.slice(0, 20) + ']=' + v;
    }
  }
  return 'NOFIELD:' + kw;
}""",
                [label, value],
            )
        )
    finally:
        _close(pw, b)


def eval_js(urlsub: str, js: str) -> None:
    pw, b, pg = _page(urlsub)
    try:
        r = pg.evaluate(js)
        print(r if isinstance(r, str) else json.dumps(r, ensure_ascii=False, default=str))
    finally:
        _close(pw, b)


def screenshot(path: str = "/tmp/quickweb.png") -> None:
    """CDP 带来的新能力：AppleScript 时代因终端无屏幕录制权限做不到。"""
    pw, b, pg = _page("quicksight")
    try:
        pg.screenshot(path=path)
        print(f"✓ 截图 → {path}")
    finally:
        _close(pw, b)


# ───────────────────────── 读命令层 ─────────────────────────

def goto(area: str) -> None:
    slug = AREA_ALIAS.get(area, area)
    pw, b, pg = _page("quicksight")
    try:
        pg.goto(WEB_BASE + slug, wait_until="domcontentloaded")
        print(f"→ goto {slug}")
    finally:
        _close(pw, b)


def wait_text(text: str, timeout: float = 20) -> None:
    pw, b, pg = _page("quicksight")
    try:
        deadline = time.time() + float(timeout)
        while time.time() < deadline:
            if text in pg.evaluate("()=>document.body.innerText"):
                print(f"OK: 出现 {text}")
                return
            time.sleep(1)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        print(f"TIMEOUT: 未等到 {text}")
    finally:
        _close(pw, b)


def dump(urlsub: str = "quicksight", sel: str | None = None) -> None:
    pw, b, pg = _page(urlsub)
    try:
        if sel:
            r = pg.evaluate(
                "(s)=>{const e=document.querySelector(s);return e?e.innerText.slice(0,2000):'NOEL';}",
                sel,
            )
        else:
            r = pg.evaluate(
                "()=>{const m=document.querySelector('main')||document.body;"
                "return m.innerText.replace(/\\n{2,}/g,'\\n').slice(0,2000);}"
            )
        print(r)
    finally:
        _close(pw, b)


def list_area(urlsub: str = "quicksight") -> None:
    """quicksight 列表非标准 table,故读 main.innerText 逐行过滤。"""
    pw, b, pg = _page(urlsub)
    try:
        print(
            pg.evaluate(
                r"""() => {
  const m = document.querySelector('main') || document.body;
  const skip = /^(名称|描述|创建者|上次修改时间|上次更新时间|操作|全部|由我创建|收藏夹|与我共享|最近使用|表格视图|卡片视图|Items per page|\d+|First|Previous|Next|Last|Page \d+|\s*)$/;
  const seen = new Set(), out = [];
  for (const line of m.innerText.split('\n')) {
    const t = line.replace(/\s+/g, ' ').trim();
    if (t && t.length > 1 && t.length < 100 && !skip.test(t) && !seen.has(t)) {
      seen.add(t); out.push(t.slice(0, 80));
    }
  }
  return '共' + out.length + '行:\n' + out.slice(0, 50).join('\n');
}"""
            )
        )
    finally:
        _close(pw, b)


def _click_retry(pg, text: str, tries: int = 8) -> str:
    """薄重试兜底 SPA 懒加载(playwright 的自动等待只覆盖 locator API,不覆盖注入式点击)。"""
    r = "NOTFOUND"
    for _ in range(tries):
        r = _click_on(pg, text)
        if r.startswith("CLICKED"):
            return r
        time.sleep(1)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
    return r


def view(mode: str) -> None:
    pw, b, pg = _page("quicksight")
    try:
        for cand in _VIEW_MAP.get(mode, [mode]):
            r = _click_on(pg, cand)
            if r.startswith("CLICKED"):
                print(f"view {mode}: {r}")
                return
        print(f"view {mode}: 未命中任何候选 {_VIEW_MAP.get(mode, [mode])}")
    finally:
        _close(pw, b)


def filter_area(scope: str) -> None:
    pw, b, pg = _page("quicksight")
    try:
        print(f"filter {scope}: {_click_on(pg, _FILTER_MAP.get(scope, scope))}")
    finally:
        _close(pw, b)


def tab(name: str) -> None:
    pw, b, pg = _page("quicksight")
    try:
        print(f"tab {name}: {_click_on(pg, name)}")
    finally:
        _close(pw, b)


def sort_area(col: str | None = None) -> None:
    pw, b, pg = _page("quicksight")
    try:
        if col:
            print(f"sort {col}: {_click_on(pg, col)}")
            return
        for cand in ("排序", "Column actions", "Not sorted", "Clear sort"):
            r = _click_on(pg, cand)
            if r.startswith("CLICKED"):
                print(f"sort: {r}")
                return
        print("sort: 未找到排序控件")
    finally:
        _close(pw, b)


def page(direction: str) -> None:
    pw, b, pg = _page("quicksight")
    try:
        if direction.isdigit():
            print(f"page {direction}: {_click_on(pg, 'Go to page ' + direction)}")
            return
        for cand in _PAGE_MAP.get(direction, [direction]):
            r = _click_on(pg, cand)
            if r.startswith("CLICKED"):
                print(f"page {direction}: {r}")
                return
        print(f"page {direction}: 未命中 {_PAGE_MAP.get(direction, [direction])}")
    finally:
        _close(pw, b)


def search_area(kw: str) -> None:
    """区内搜索框(避开左栏全局搜索)。CDP 下 fill 直接生效,不需剪贴板 hack。"""
    pw, b, pg = _page("quicksight")
    try:
        print(
            pg.evaluate(
                """(kw) => {
  const ns = document.querySelectorAll('input[type=text],input[type=search],input:not([type]),textarea');
  for (const e of ns) {
    const r = e.getBoundingClientRect();
    const ph = e.getAttribute('placeholder') || e.getAttribute('aria-label') || '';
    if (r.width > 0 && r.height > 0 && /搜索|search/i.test(ph)) {
      e.focus();
      const d = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value');
      if (d && d.set) d.set.call(e, kw); else e.value = kw;
      e.dispatchEvent(new Event('input', {bubbles: true}));
      return 'SEARCH[' + ph.slice(0, 20) + ']=' + kw;
    }
  }
  return 'NOSEARCHBOX';
}""",
                kw,
            )
        )
    finally:
        _close(pw, b)


def open_item(name: str) -> None:
    pw, b, pg = _page("quicksight")
    try:
        print(f"open {name}: {_click_on(pg, name)}")
    finally:
        _close(pw, b)


def open_menu(name: str) -> None:
    pw, b, pg = _page("quicksight")
    try:
        for cand in ("更多操作", "操作", "More actions", "更多选项", "⋮"):
            r = _click_on(pg, cand)
            if r.startswith("CLICKED"):
                print(f"open-menu near {name}: {r}")
                return
        print(f"open-menu {name}: 未找到菜单触发器")
    finally:
        _close(pw, b)


_SHELL_MAP = {
    "help": "帮助", "user-menu": "用户下拉列表", "toggle-nav": "Toggle navigation",
    "open-chat": "打开聊天", "chat-search": "搜索对话", "more-menu": "更多",
}


def shell_cmd(which: str) -> None:
    pw, b, pg = _page("quicksight")
    try:
        print(f"{which}: {_click_on(pg, _SHELL_MAP.get(which, which))}")
    finally:
        _close(pw, b)


def dismiss_banner() -> None:
    pw, b, pg = _page("quicksight")
    try:
        print(f"dismiss-banner: {_click_on(pg, '关闭')}")
    finally:
        _close(pw, b)


# ───────────────────────── 写命令层 ─────────────────────────
# v1.x 的剪贴板 hack(pbcopy + 提标签前台 + Cmd+V)已删除:CDP 下 locator.fill()
# 直接写入 MUI 输入框(2026-07-27 实测)。写操作因此变为静默后台执行。

def _fill_by(pg, pred_js: str, value: str, tries: int = 6) -> bool:
    """按 JS 谓词找输入框并 fill。pred_js 收一个 element 返回 bool。"""
    for _ in range(tries):
        ok = pg.evaluate(
            """([pred, v]) => {
  const f = new Function('e', 'return (' + pred + ')(e)');
  for (const e of document.querySelectorAll('input,textarea')) {
    if (f(e)) {
      e.focus();
      const proto = e.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement : window.HTMLInputElement;
      const d = Object.getOwnPropertyDescriptor(proto.prototype, 'value');
      if (d && d.set) d.set.call(e, v); else e.value = v;
      if (e._valueTracker) e._valueTracker.setValue('');
      e.dispatchEvent(new Event('input', {bubbles: true}));
      e.dispatchEvent(new Event('change', {bubbles: true}));
      return true;
    }
  }
  return false;
}""",
            [pred_js, value],
        )
        if ok:
            return True
        time.sleep(1)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
    return False


def _wait_text_on(pg, text: str, timeout: float = 20) -> bool:
    deadline = time.time() + float(timeout)
    while time.time() < deadline:
        if text in pg.evaluate("()=>document.body.innerText"):
            return True
        time.sleep(1)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
    return False


def _click_exact(pg, label: str, tries: int = 6) -> bool:
    """点文字精确等于 label 且未禁用的按钮/菜单项(去空白后比较)。"""
    for _ in range(tries):
        ok = pg.evaluate(
            """(lab) => {
  for (const e of document.querySelectorAll('button,[role=menuitem]')) {
    const r = e.getBoundingClientRect();
    if (r.width > 0 && r.height > 0 && !e.disabled
        && (e.innerText || '').replace(/\\s+/g, '') === lab) { e.click(); return true; }
  }
  return false;
}""",
            label,
        )
        if ok:
            return True
        time.sleep(1)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
    return False


def create_space(name: str) -> None:
    pw, b, pg = _page("quicksight")
    try:
        pg.goto(WEB_BASE + "spaces", wait_until="domcontentloaded")
        print("→ goto spaces")
        _wait_text_on(pg, "创建空间", 15)
        print(f"open: {_click_retry(pg, '创建空间')}")
        if not _wait_text_on(pg, "为空间命名", 8):
            time.sleep(2)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        ok = _fill_by(pg, "e => (e.getAttribute('aria-label')||e.placeholder||'').includes('命名')", name)
        print(f"fill: {'FILLED' if ok else 'NONAME'}")
        if not ok:
            print("中止:未找到命名框")
            return
        time.sleep(1)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        print(f"submit: {'SUBMIT' if _click_exact(pg, '创建') else 'NOCREATE'}")
        time.sleep(4)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        print(
            "state: "
            + pg.evaluate("()=>(document.querySelector('h1')||{}).innerText||location.href")
        )
    finally:
        _close(pw, b)


def delete_space(name: str) -> None:
    """高危:只删传入名字的空间。--confirm 由 dispatcher 把关。

    v1.x 的 i18n 坑仍在:确认框提示"键入 Delete"但实际校验中文"删除"。
    但 CDP 下不再需要剪贴板粘贴——fill 直接生效。
    """
    pw, b, pg = _page("quicksight")
    try:
        pg.goto(WEB_BASE + "spaces", wait_until="domcontentloaded")
        print("→ goto spaces")
        if not _wait_text_on(pg, name, 15):
            print(f"中止:列表里没等到空间 {name}(不存在或未渲染)")
            return
        # 定位该空间行的"更多操作":SPA 文本先于按钮挂载,故自重试
        menu = "NOROW"
        for _ in range(10):
            menu = pg.evaluate(
                """(name) => {
  let target = null;
  for (const e of document.querySelectorAll('td,div,li,tr')) {
    if (e.innerText && e.innerText.includes(name) && e.innerText.length < 80) { target = e; break; }
  }
  if (!target) return 'NOROW';
  for (let node = target, up = 0; node && up < 6; node = node.parentElement, up++) {
    for (const bt of node.querySelectorAll ? node.querySelectorAll('button,[role=button]') : []) {
      const lab = bt.getAttribute('aria-label') || bt.innerText || '';
      if (lab.includes('更多')) { bt.click(); return 'MENU'; }
    }
  }
  return 'NOMORE';
}""",
                name,
            )
            if menu == "MENU":
                break
            time.sleep(1)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        print(f"menu: {menu}")
        if menu != "MENU":
            print("中止:未定位到空间行(超时)")
            return
        time.sleep(1.5)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        if not _click_exact(pg, "删除"):
            print("delete-menu: NODEL")
            print("中止:菜单里没找到删除项")
            return
        print("delete-menu: DLGCLICK")
        dlg = False
        for _ in range(8):
            if pg.evaluate(
                "()=>{const d=document.querySelector('[role=dialog],[role=alertdialog]');"
                "return !!(d&&d.querySelector('input'));}"
            ):
                dlg = True
                break
            time.sleep(1)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        if not dlg:
            print("中止:删除确认弹窗未出现")
            return
        # i18n bug:提示写 Delete,实际校验中文"删除"
        _fill_by(pg, "e => e.closest('[role=dialog],[role=alertdialog]') !== null", "删除")
        print("type-confirm: pasted")
        enabled = False
        for _ in range(6):
            if pg.evaluate(
                "()=>{const d=document.querySelector('[role=dialog],[role=alertdialog]');"
                "if(!d)return false;const b=d.querySelector('[data-testid=delete-space-dialog-delete-button]');"
                "return !!(b&&!b.disabled);}"
            ):
                enabled = True
                break
            time.sleep(1)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        if not enabled:
            print("中止:确认后删除按钮仍禁用(确认词/粘贴失败)")
            return
        pg.evaluate(
            "()=>{const d=document.querySelector('[role=dialog],[role=alertdialog]');"
            "d.querySelector('[data-testid=delete-space-dialog-delete-button]').click();}"
        )
        print("final: DELETED")
        time.sleep(4)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        pg.goto(WEB_BASE + "spaces", wait_until="domcontentloaded")
        print("→ goto spaces")
        time.sleep(4)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        gone = name not in pg.evaluate("()=>document.body.innerText")
        print(f"verify: {'已删除' if gone else '仍在'}")
    finally:
        _close(pw, b)


def create_app(prompt: str) -> None:
    """描述要强约束,否则 Quick 易自作主张做成"文档浏览器/markdown 阅读器"。"""
    pw, b, pg = _page("quicksight")
    try:
        pg.goto(WEB_BASE + "apps", wait_until="domcontentloaded")
        print("→ goto apps")
        if not (_wait_text_on(pg, "创建应用程序", 12) or _wait_text_on(pg, "告诉我们", 8)):
            time.sleep(3)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        ok = _fill_by(pg, "e => e.tagName === 'TEXTAREA'", prompt)
        print(f"fill-prompt: {'pasted' if ok else 'NOFIELD'}")
        time.sleep(1)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        # 提交按钮是 aria-label='生成'(不是文字'生成')
        gen = False
        for _ in range(6):
            gen = pg.evaluate(
                """() => {
  for (const e of document.querySelectorAll('button,[role=button]')) {
    if ((e.getAttribute('aria-label') || '').trim() === '生成' && !e.disabled) { e.click(); return true; }
  }
  return false;
}"""
            )
            if gen:
                break
            time.sleep(1)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        print(f"generate: {'GEN' if gen else 'NOGEN'}")
        if not gen:
            print("中止:未找到'生成'按钮(检查是否在 apps 区、描述是否填入)")
            return
        time.sleep(5)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        print("state: " + pg.evaluate("()=>location.href"))
        print("提示:App 正在编辑器里构建(register_runtime_integration→建组件),可能数分钟+弹授权框。")
        print("     期间反复跑 `approve-prompts` 自动点授权;建完跑 `publish-app` 发布。")
        print('     要改内容:`app-edit "<自然语言修改指令>"`(编辑器\'要求应用程序进行更改\'输入框)。')
    finally:
        _close(pw, b)


def approve_prompts() -> None:
    """轮询式:建 App 的几分钟里反复跑几次。"""
    pw, b, pg = _page("quicksight")
    try:
        print(
            pg.evaluate(
                """() => {
  const re = /^(允许|授权|继续|同意|确认|Allow|Allow once|Approve|Continue|Grant|预览|Preview)$/i;
  for (const e of document.querySelectorAll('button,[role=button]')) {
    const t = (e.innerText || e.getAttribute('aria-label') || '').trim();
    if (re.test(t) && !e.disabled) { e.click(); return 'CLICKED:' + t; }
  }
  return 'no-prompt';
}"""
            )
        )
    finally:
        _close(pw, b)


def app_edit(instruction: str) -> None:
    pw, b, pg = _page("quicksight")
    try:
        ok = _fill_by(
            pg,
            "e => e.tagName === 'TEXTAREA' && ((e.placeholder||'').includes('更改') "
            "|| (e.placeholder||'').includes('要求'))",
            instruction,
        )
        if not ok:
            ok = _fill_by(pg, "e => e.tagName === 'TEXTAREA'", instruction)
        if ok:
            pg.keyboard.press("Enter")
        print(f"app-edit: {'pasted' if ok else 'NOFIELD'}")
    finally:
        _close(pw, b)


def publish_app() -> None:
    pw, b, pg = _page("quicksight")
    try:
        print(f"publish-1: {_click_retry(pg, '发布')}")
        time.sleep(3)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        r = "NODLG"
        for _ in range(6):
            r = pg.evaluate(
                """() => {
  const d = document.querySelector('[role=dialog],[role=alertdialog]');
  if (!d) return 'NODLG';
  for (const b of d.querySelectorAll('button')) {
    if ((b.innerText || '').replace(/\\s+/g, '') === '发布' && !b.disabled) { b.click(); return 'CONFIRM'; }
  }
  return 'NOCONFIRM';
}"""
            )
            if r == "CONFIRM":
                break
            time.sleep(1)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        print(f"publish-2: {r}")
        time.sleep(5)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        print(
            "URL: "
            + pg.evaluate(
                "()=>{const d=document.querySelector('[role=dialog],[role=alertdialog]');"
                "if(d){const i=d.querySelector('input');if(i&&i.value)return i.value;"
                "const a=d.querySelector('a[href]');if(a)return a.href;}return location.href;}"
            )
        )
    finally:
        _close(pw, b)


def share_app(alias: str) -> None:
    """⚠️ v1.x 结论:App 共享框的自动补全候选是自动化盲区(四种注入都不出候选)。
    CDP 下可能已解决,但【待真机验证】——行为保持保守:只填 alias,选中/定权限/点共享交人工。
    """
    pw, b, pg = _page("quicksight")
    try:
        print(f"open-share: {_click_retry(pg, '共享')}")
        time.sleep(2)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        if not pg.evaluate(
            "()=>{const d=document.querySelector('[role=dialog]');"
            "return !!(d&&d.querySelector('input'));}"
        ):
            print("中止:共享框未打开(或无输入框)")
            return
        _fill_by(pg, "e => e.closest('[role=dialog]') !== null", alias)
        print("type-alias: pasted")
        time.sleep(2)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
        print("⚠️ 已填入 alias 到 App 共享搜索框。【自动补全候选是自动化盲区】——")
        print("   请在浏览器里手动:从候选点选此人 → 选权限(查看器/共同所有者)→ 再输下一个人 → 点'共享'。")
    finally:
        _close(pw, b)


# ───────────────────────── dispatch ─────────────────────────

def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        return
    c = sys.argv[1]
    a = sys.argv[2:]

    if c == "tabs":
        tabs()
    elif c == "find":
        find(a[0])
    elif c == "state":
        state(a[0] if a else "quicksight")
    elif c == "buttons":
        buttons(a[0] if a else "quicksight")
    elif c == "click":
        click(a[0], a[1])
    elif c == "fill":
        fill(a[0], a[1], a[2])
    elif c == "eval":
        eval_js(a[0], a[1] if len(a) > 1 else sys.stdin.read())
    elif c == "evalf":
        eval_js(a[0], open(a[1]).read())
    elif c == "screenshot":
        screenshot(a[0] if a else "/tmp/quickweb.png")
    elif c == "goto":
        goto(a[0])
    elif c == "wait-text":
        wait_text(a[0], a[1] if len(a) > 1 else 20)
    elif c == "dump":
        dump(a[0] if a else "quicksight", a[1] if len(a) > 1 else None)
    elif c == "list":
        list_area(a[0] if a else "quicksight")
    elif c == "view":
        view(a[0])
    elif c == "tab":
        tab(a[0])
    elif c == "filter":
        filter_area(a[0])
    elif c == "sort":
        sort_area(a[0] if a else None)
    elif c == "page":
        page(a[0])
    elif c == "search":
        search_area(a[0])
    elif c == "open":
        open_item(a[0])
    elif c == "open-menu":
        open_menu(a[0])
    elif c == "dismiss-banner":
        dismiss_banner()
    elif c in ("help", "user-menu", "toggle-nav", "open-chat", "chat-search", "more-menu"):
        shell_cmd(c)
    elif c == "create-space":
        create_space(a[0])
    elif c == "delete-space":
        if "--confirm" not in a:
            print("⚠️ 高危:删除空间需加 --confirm。用法: delete-space <名> --confirm", file=sys.stderr)
            sys.exit(2)
        delete_space(a[0])
    elif c == "create-app":
        create_app(a[0])
    elif c == "approve-prompts":
        approve_prompts()
    elif c == "app-edit":
        app_edit(a[0])
    elif c == "publish-app":
        publish_app()
    elif c == "share-app":
        share_app(a[0])
    else:
        print(f"未知命令: {c}\n{__doc__}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
