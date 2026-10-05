"""单元测试:纯函数逻辑,不需要真机在跑。
覆盖 chrome_as.py 的映射表/常量与 web_ensure.py 的路径推导。
演示剧本测试已随 demo.py 迁到 PPT repo。"""
import os
import sys

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPTS)

import chrome_as  # noqa: E402
import quick_ctl  # noqa: E402
import web_ensure  # noqa: E402


# ---------- quick_ctl:状态推导纯函数 + 需输入词表 ----------

def test_derive_state_precedence():
    """优先级:需输入 > 生成中 > 完成。needs_input 永远压过 generating。"""
    assert quick_ctl._derive_state(True, True) == "needs_input"
    assert quick_ctl._derive_state(True, False) == "thinking"
    assert quick_ctl._derive_state(False, True) == "needs_input"
    assert quick_ctl._derive_state(False, False) == "done"


def test_needs_input_tokens():
    """英文审批词必须以小写存储(扫描时统一转小写才能命中),中文词原样在列表里。"""
    for t in ("allow", "approve", "continue", "grant"):
        assert t in quick_ctl.NEEDS_INPUT_TOKENS
        assert t == t.lower()
    for t in ("允许", "授权", "继续", "同意", "确认"):
        assert t in quick_ctl.NEEDS_INPUT_TOKENS


def test_choice_card_skip_tokens():
    """选项卡等待态词表:英文 skip 小写存储,中文"跳过"原样;_needs_input 第二条判据靠它。

    真机确认:agent 等待时渲染为一组可用 button[role=radio] + Skip 按钮(无 Allow/Approve),
    仅靠审批词会漏判成 done,故需这组 Skip 词支撑选项卡判据。
    """
    assert "skip" in quick_ctl.SKIP_TOKENS and "skip" == "skip".lower()
    assert "跳过" in quick_ctl.SKIP_TOKENS


def test_derive_state_needs_input_from_choice_card():
    """选项卡等待态下 _needs_input 为真(generating 为假)时,状态仍应是 needs_input。"""
    assert quick_ctl._derive_state(False, True) == "needs_input"


# ---------- quick_ctl:status-all 纯逻辑(无浏览器) ----------

def test_chat_state_truth_table():
    """单行状态真值表:非激活行 dot→attention 否则 idle;激活行原样返回 active_state。"""
    assert quick_ctl._chat_state(True, False, "done") == "attention"
    assert quick_ctl._chat_state(False, False, "done") == "idle"
    # 激活行:不论 dot,返回传入的 active_state
    for st in ("thinking", "needs_input", "done"):
        assert quick_ctl._chat_state(True, True, st) == st
        assert quick_ctl._chat_state(False, True, st) == st


def test_active_index():
    """_active_index:精确 slug 命中 / 截断 slug 的 startswith 容错 / 无匹配 → -1。"""
    names = ["Checking email reply status", "AI integration strategy at T. Rowe Price"]
    # 精确:URL 末段恰为完整 slug
    assert quick_ctl._active_index(names, "file:///chat/d01da364/checking-email-reply-status") == 0
    # 截断容错:URL slug 是标题 slug 的前缀
    assert quick_ctl._active_index(names, "file:///chat/x/ai-integration-strategy") == 1
    # 无匹配
    assert quick_ctl._active_index(names, "file:///chat/x/something-else-entirely") == -1
    # 空 URL 末段
    assert quick_ctl._active_index(names, "") == -1


def test_assemble_chats_all():
    """chats=None:按侧栏顺序全量输出,全部 found=True,仅 active_idx 行 active=True 且状态正确。"""
    rows = [{"name": "A", "dot": False}, {"name": "B", "dot": True}, {"name": "C", "dot": False}]
    out = quick_ctl._assemble_chats(rows, active_idx=0, active_state="thinking", chats=None)
    assert [c["name"] for c in out] == ["A", "B", "C"]
    assert all(c["found"] for c in out)
    assert [c["active"] for c in out] == [True, False, False]
    assert [c["state"] for c in out] == ["thinking", "attention", "idle"]


def test_assemble_chats_selection_order_and_missing():
    """chats 给定:保序、精确匹配(非子串)、缺失名字 found=False/state idle/active False。"""
    rows = [{"name": "Chat A", "dot": False},
            {"name": "Chat AA", "dot": True},
            {"name": "Chat B", "dot": True}]
    out = quick_ctl._assemble_chats(rows, active_idx=0, active_state="done",
                                    chats=["Chat B", "Nope", "Chat A"])
    assert [c["name"] for c in out] == ["Chat B", "Nope", "Chat A"]
    # 顺序保持;缺失项
    assert out[1] == {"name": "Nope", "state": "idle", "active": False, "found": False}
    # "Chat A" 精确匹配到下标 0(active),不会误配 "Chat AA"
    assert out[2]["found"] is True and out[2]["active"] is True and out[2]["state"] == "done"
    # "Chat B" 有 dot 但非激活 → attention
    assert out[0]["found"] is True and out[0]["active"] is False and out[0]["state"] == "attention"


def test_dom_active_index():
    """_dom_active_index:恰一行 sel=True → 该下标;零行 sel → -1;多于一行 sel=True → -1(歧义交回 URL-slug)。"""
    rows = [{"name": "A", "dot": False, "sel": False},
            {"name": "B", "dot": False, "sel": True},
            {"name": "C", "dot": False, "sel": False}]
    assert quick_ctl._dom_active_index(rows) == 1
    # 零行报告 sel → -1
    none_sel = [{"name": "A", "dot": False, "sel": False},
                {"name": "B", "dot": True, "sel": False}]
    assert quick_ctl._dom_active_index(none_sel) == -1
    # 两行 sel=True → 歧义 → -1
    two_sel = [{"name": "A", "dot": False, "sel": True},
               {"name": "B", "dot": False, "sel": True}]
    assert quick_ctl._dom_active_index(two_sel) == -1
    # sel 键缺省按假处理
    assert quick_ctl._dom_active_index([{"name": "A", "dot": False}]) == -1


def test_chats_arg_parsing():
    """--chats 多值解析:缺省 None;收集到下一个 -- 开头 token 或末尾为止。"""
    assert quick_ctl._chats_arg([]) is None
    assert quick_ctl._chats_arg(["--other"]) is None
    assert quick_ctl._chats_arg(["--chats", "A", "B", "C"]) == ["A", "B", "C"]
    assert quick_ctl._chats_arg(["--chats", "A", "--flag", "B"]) == ["A"]
    assert quick_ctl._chats_arg(["--chats"]) == []


# ---------- quick_ctl:focus(OS 级前置,全程 mock subprocess.run,绝不 spawn) ----------

def test_focus_invokes_open_a(monkeypatch):
    """focus() 必须用 open -a 'Amazon Quick' 前置,且不真正 spawn。"""
    calls = []
    class _R: returncode = 0
    def fake_run(argv, *a, **k):
        calls.append(argv); return _R()
    monkeypatch.setattr(quick_ctl.subprocess, "run", fake_run)
    quick_ctl.focus()
    assert calls == [["open", "-a", "Amazon Quick"]]


def test_focus_nonzero_exits(monkeypatch):
    """open 返回非零时 focus() 必须 sys.exit(1)。"""
    import pytest
    class _R: returncode = 1
    monkeypatch.setattr(quick_ctl.subprocess, "run", lambda *a, **k: _R())
    with pytest.raises(SystemExit) as ei:
        quick_ctl.focus()
    assert ei.value.code == 1


# ---------- chrome_as:_as_string 是 v1.x AppleScript 遗留纯函数 ----------
# CDP 实现不再调用它,保留是为了这几项断言(以及记录当年的转义规则)。

def test_as_string_escapes_quotes():
    assert chrome_as._as_string('say "hi"') == '"say \\"hi\\""'

def test_as_string_escapes_backslash():
    assert chrome_as._as_string('a\\b') == '"a\\\\b"'

def test_as_string_wraps_plain():
    assert chrome_as._as_string("库") == '"库"'


# ---------- chrome_as:网页版 11 区别名映射 ----------

def test_area_alias_english():
    assert chrome_as.AREA_ALIAS["spaces"] == "spaces"
    assert chrome_as.AREA_ALIAS["dashboards"] == "dashboards"

def test_area_alias_chinese():
    assert chrome_as.AREA_ALIAS["空间"] == "spaces"
    assert chrome_as.AREA_ALIAS["控制面板"] == "dashboards"
    assert chrome_as.AREA_ALIAS["流程"] == "flows"

def test_area_alias_covers_all_11():
    # 11 个区都要能解析到 5 个不同 slug 前缀
    slugs = {chrome_as.AREA_ALIAS[k] for k in
             ["mystuff", "spaces", "research", "agents", "apps", "flows",
              "analyses", "dashboards", "data", "personal", "shared"]}
    assert len(slugs) == 11


# ---------- chrome_as:视图/筛选/分页 映射表存在且非空 ----------

def test_view_map_has_modes():
    for m in ("grid", "list", "table", "card"):
        assert m in chrome_as._VIEW_MAP and chrome_as._VIEW_MAP[m]

def test_filter_map_scopes():
    assert chrome_as._FILTER_MAP["mine"] == "由我创建"
    assert chrome_as._FILTER_MAP["all"] == "全部"

def test_page_map_directions():
    for d in ("first", "prev", "next", "last"):
        assert d in chrome_as._PAGE_MAP


# ---------- chrome_as:CDP 相关常量与 URL 拼装 ----------

def test_web_base_is_quicksight():
    """WEB_BASE 必须是 https 的 Quick 网页版地址,且以 / 结尾。

    QUICK_WEB_BASE 允许整体覆盖(自建代理/私有域),那种情况下只校验形状 ——
    "默认值指向 quicksight 公开域"这条由下面的源码断言守。
    """
    assert chrome_as.WEB_BASE.startswith("https://")
    assert chrome_as.WEB_BASE.endswith("/"), "WEB_BASE 需以 / 结尾才能直接拼 slug"
    if not os.environ.get("QUICK_WEB_BASE"):
        assert "quicksight.aws.amazon.com" in chrome_as.WEB_BASE


def test_area_url_composition():
    """goto 的 URL = WEB_BASE + slug,别名解析后拼装必须合法。"""
    for alias, slug in (("空间", "spaces"), ("dashboards", "dashboards"),
                        ("shared", "folders/shared")):
        assert chrome_as.AREA_ALIAS[alias] == slug
        assert chrome_as.WEB_BASE + slug == f"{chrome_as.WEB_BASE}{slug}"


def test_cdp_endpoint_uses_loopback():
    """CDP 只连本机回环 —— 不应向外暴露/连接远端调试端口。"""
    assert chrome_as.CDP.startswith("http://127.0.0.1:")
    assert chrome_as.PORT == os.environ.get("QUICK_WEB_CDP_PORT", "9445")


def test_click_selector_covers_interactive_roles():
    sel = chrome_as.CLICK_SEL
    for part in ("button", "[role=button]", "a[href]", "[role=tab]", "[role=menuitem]"):
        assert part in sel


# ---------- web_ensure:路径与端口推导 ----------

def test_web_ensure_default_port():
    assert web_ensure.PORT == os.environ.get("QUICK_WEB_CDP_PORT", "9445")


def test_web_ensure_shares_port_env_with_chrome_as():
    """两个脚本必须用同一端口,否则一个起实例、另一个连不上。"""
    assert web_ensure.PORT == chrome_as.PORT


def test_web_ensure_profile_is_dedicated_dir():
    """CDP 实例必须用独立的持久 profile,不能落在日常主 profile 上。

    主 profile 通常不开 --remote-debugging-port,且拿它当调试目标会干扰日常浏览。
    """
    prof = str(web_ensure.PROFILE)
    assert prof, "PROFILE 不能为空"
    assert "Library/Application Support/Google/Chrome" not in prof, \
        "不得把主 Chrome 的 user-data-dir 当 CDP profile"


def test_status_json_contract():
    """status 的 JSON 契约:四个必需键在,且不含已下线的键。"""
    import io
    import json as _json
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        web_ensure.status()
    d = _json.loads(buf.getvalue())
    for k in ("cdp_ok", "signed_in", "url", "tabs"):
        assert k in d, f"status JSON 缺键 {k!r}"
    assert "manifest_ok" not in d, "manifest_ok 是已下线的键,不应回归到 status 契约里"


def test_unauth_markers_catch_login_urls(monkeypatch):
    """登录页判据:通用的 signin / login / authorize / oauth / sso 路径都要判为未登录。

    默认值故意不绑定任何具体身份提供方 —— 断言用 example.com 占位域,证明的是
    "URL 里出现登录/授权路径关键词即视为未登录"这条逻辑本身。
    delenv:本项测的是【默认】判据,不能被开发机上已 export 的覆盖值搅成假红。
    """
    monkeypatch.delenv("QUICK_UNAUTH_MARKERS", raising=False)
    for url in (
        "https://auth.example.com/login?next=x",
        "https://idp.example.com/oauth2/authorize?a=b",
        "https://sso.example.org/saml/start",
        "https://us-east-1.quicksight.aws.amazon.com/sn/auth/signin?redirect_uri=x",
    ):
        assert any(m in url.lower() for m in web_ensure.unauth_markers()), url


def test_unauth_markers_pass_real_app_url(monkeypatch):
    monkeypatch.delenv("QUICK_UNAUTH_MARKERS", raising=False)
    url = "https://us-east-1.quicksight.aws.amazon.com/sn/account/your-quick-account/start/spaces"
    assert not any(m in url.lower() for m in web_ensure.unauth_markers())


def test_unauth_markers_env_override(monkeypatch):
    """QUICK_UNAUTH_MARKERS 可整体覆盖判据 —— 内部 IdP 域名靠配置注入,不进代码。"""
    monkeypatch.setenv("QUICK_UNAUTH_MARKERS", "my-idp, corp-auth ")
    assert web_ensure.unauth_markers() == ("my-idp", "corp-auth")
    # 空/全空白视为未设置 → 回落默认,避免"配错就等于关掉判据"
    monkeypatch.setenv("QUICK_UNAUTH_MARKERS", "  ,  ")
    assert web_ensure.unauth_markers() == web_ensure.DEFAULT_UNAUTH_MARKERS


def test_web_base_account_comes_from_env():
    """起始 URL 的账户名必须来自环境变量,源码里只留占位符 —— 不内置任何具体账户。

    断言打在**源码**上而不是 WEB_BASE 的值上:值会随本机 env 变化,
    "代码里没有硬编码账户"这件事才是要守住的不变量。
    """
    for name in ("web_ensure.py", "chrome_as.py"):
        with open(os.path.join(SCRIPTS, name), encoding="utf-8") as f:
            src = f.read()
        assert "QUICK_WEB_ACCOUNT" in src, f"{name} 未把账户名做成可配置"
        assert "your-quick-account" in src, f"{name} 的默认账户名不是占位符"
    # 拼接结果必须以 / 结尾,否则 WEB_BASE + slug 会粘成一段
    for mod in (web_ensure, chrome_as):
        assert mod.WEB_BASE.endswith("/")
