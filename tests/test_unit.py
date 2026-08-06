"""单元测试:纯函数逻辑,不需要真机在跑。
覆盖 chrome_as.py 的映射表/常量与 web_ensure.py 的路径推导。
演示剧本测试已随 demo.py 迁到 PPT repo。"""
import os
import sys

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPTS)

import chrome_as  # noqa: E402
import web_ensure  # noqa: E402


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
