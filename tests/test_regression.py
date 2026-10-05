"""回归测试:确保通用能力(chrome_as/quick_ctl/web_ensure)不退化。

v2.0 起 chrome_as.py 底层是 CDP(不再 AppleScript),故本文件同时守两件事:
1. CLI 契约不被误删(命令名清单) —— 调用方用 subprocess 调,少一个命令就挂
2. AppleScript 实现不"回归" —— 那套三层转义/剪贴板 hack 已被 CDP 取代
"""
import ast
import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
TESTS = os.path.join(ROOT, "tests")


def _min_python() -> tuple[int, int]:
    """从 pyproject.toml 的 requires-python 读最低版本,避免与测试里硬编码漂移。"""
    with open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8") as f:
        m = re.search(r'requires-python\s*=\s*"[^0-9]*(\d+)\.(\d+)', f.read())
    assert m, "pyproject.toml 里读不到 requires-python"
    return int(m.group(1)), int(m.group(2))


MIN_PY = _min_python()

ALL_SCRIPTS = ["chrome_as.py", "quick_ctl.py", "web_ensure.py",
               "crawl_all.py", "crawl_web_deep.py", "map_screen.py",
               "probe_settings.py", "probe_web_areas.py", "verify_all.py"]

# chrome_as.py 的完整 CLI 契约(v1.x 冻结,CDP 改造后逐字保留)。
# screenshot 是 v2.0 新增(CDP 带来的能力)。
CHROME_AS_COMMANDS = [
    # 通用原语
    "tabs", "find", "state", "buttons", "click", "fill", "eval", "evalf", "screenshot",
    # 读命令层
    "goto", "wait-text", "dump", "list", "view", "tab", "filter", "sort", "page",
    "search", "open", "open-menu", "dismiss-banner",
    "help", "user-menu", "toggle-nav", "open-chat", "chat-search", "more-menu",
    # 写命令层
    "create-space", "delete-space", "create-app", "approve-prompts", "app-edit",
    "publish-app", "share-app",
]


def _src(name: str) -> str:
    with open(os.path.join(SCRIPTS, name), encoding="utf-8") as f:
        return f.read()


def _dispatch_literals(name: str) -> set[str]:
    """从 main() 的 AST 里收集所有与命令变量比较的字符串字面量。

    不绑死 `c == "x"` 的写法(用 in 元组、match 语句都能被收到),
    这样重构 dispatch 结构不会假红,但真删掉一个命令会红。
    """
    tree = ast.parse(_src(name))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for side in [node.left, *node.comparators]:
                if isinstance(side, ast.Constant) and isinstance(side.value, str):
                    out.add(side.value)
                elif isinstance(side, (ast.Tuple, ast.List, ast.Set)):
                    for el in side.elts:
                        if isinstance(el, ast.Constant) and isinstance(el.value, str):
                            out.add(el.value)
    return out


@pytest.mark.parametrize("script", ALL_SCRIPTS)
def test_script_syntax_ok(script):
    """所有脚本必须在 requires-python 声明的最低版本语法下可解析。

    不能用裸 ast.parse —— 它按当前解释器(本机 3.13)判定,会漏掉 3.12 才放开的
    PEP 701 f-string 语法。feature_version 把断言对齐到项目声明的最低版本。
    注意它仍有盲区(纯引号复用查不出),故另有 test_min_python_syntax_gate 兜底。
    """
    ast.parse(_src(script), feature_version=MIN_PY)


@pytest.mark.skipif(shutil.which("ruff") is None, reason="ruff 未安装(CI 里必须装)")
def test_min_python_syntax_gate():
    """ruff 按最低 Python 版本做语法校验,覆盖 ast.parse(feature_version) 的盲区。

    实测:`f"{d["a"]} t"`(PEP 701 引号复用)在 feature_version=(3,10) 下仍能解析通过,
    而 ruff --target-version py310 能准确报 "Cannot reuse outer quote character"。
    用 --isolated + --select E9 只跑语法层,与 pyproject 的风格 ignore 解耦 ——
    即使有人调 [tool.ruff.lint].ignore,这道门也不会被绕过。
    """
    target = "py{}{}".format(*MIN_PY)
    r = subprocess.run(
        ["ruff", "check", "--isolated", "--target-version", target,
         "--select", "E9", "--output-format", "concise", SCRIPTS, TESTS],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, f"存在 {target} 语法不兼容:\n{r.stdout}{r.stderr}"


@pytest.mark.parametrize("cmd", CHROME_AS_COMMANDS)
def test_chrome_as_command_in_dispatch(cmd):
    """CLI 契约护栏:每个命令都必须还在 dispatch 里。

    PPT repo 的 demo.py 通过 subprocess 调这些命令名,删一个就破坏现场演示。
    """
    assert cmd in _dispatch_literals("chrome_as.py"), \
        f"命令 {cmd!r} 从 chrome_as.py 的 dispatch 中消失 —— 破坏 CLI 契约"


def test_chrome_as_delete_space_guarded():
    """delete-space 必须真的被 --confirm 把关(不只是两个字符串各自存在)。"""
    tree = ast.parse(_src("chrome_as.py"))
    guarded = False
    for node in ast.walk(tree):
        # 找 if "--confirm" not in a: ... sys.exit(2)
        if isinstance(node, ast.If):
            seg = ast.dump(node)
            if "--confirm" in seg and "exit" in seg:
                guarded = True
                break
    assert guarded, "delete-space 的 --confirm 把关(缺失即 sys.exit)不见了"


def test_chrome_as_is_cdp_based():
    """chrome_as.py 必须是 CDP 实现。"""
    src = _src("chrome_as.py")
    assert "connect_over_cdp" in src, "chrome_as.py 不再是 CDP 实现?"


def test_applescript_implementation_not_resurrected():
    """AppleScript 实现不应回归。

    v1.x 靠 osascript 注入 JS,代价是 shell/AppleScript/JS 三层转义、JS 被迫 ES5、
    写操作需 pbcopy+提标签前台+Cmd+V。CDP 迁移后这些全不需要。
    例外:_as_string 作为纯函数保留(兼容既有单元测试),但不得再有实际调用路径。
    """
    tree = ast.parse(_src("chrome_as.py"))
    banned = {"run_osa", "_bring_front_and_type"}
    defined = {
        n.name for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert not (banned & defined), f"AppleScript 实现回归: {banned & defined}"

    # osascript / pbcopy 不得作为 subprocess 参数出现(注释里提及历史无妨)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert node.value not in ("osascript", "pbcopy"), \
                f"仍在调用 {node.value} —— AppleScript 时代的实现回归了"


def test_as_string_kept_for_unit_tests():
    """_as_string 是 v1.x 遗留纯函数,单元测试依赖它,不得删除。"""
    tree = ast.parse(_src("chrome_as.py"))
    fns = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert "_as_string" in fns, "_as_string 被删了 —— tests/test_unit.py 会挂"


def test_web_ensure_commands_present():
    """网页版 CDP 通道的启动/自愈命令齐全。"""
    lits = _dispatch_literals("web_ensure.py")
    for cmd in ("ensure", "status", "login", "doctor", "restart"):
        assert cmd in lits, f"web_ensure.py 缺命令 {cmd!r}"


def test_port_convention_consistent():
    """chrome_as.py 与 web_ensure.py 必须用同一个环境变量与默认端口。"""
    for name in ("chrome_as.py", "web_ensure.py"):
        src = _src(name)
        assert "QUICK_WEB_CDP_PORT" in src, f"{name} 未用统一环境变量"
        assert "9445" in src, f"{name} 默认端口不是 9445"


def test_quick_ctl_wait_done_present():
    """quick_ctl 的 wait-done(可靠完成检测)命令在。"""
    assert "wait-done" in _dispatch_literals("quick_ctl.py")


def test_quick_ctl_status_all_present():
    """status-all(Stream Deck 看板:每个对话状态)命令必须在 dispatch 里。"""
    assert "status-all" in _dispatch_literals("quick_ctl.py")


def test_quick_ctl_focus_present():
    """focus(OS 级前置当前 Quick 窗口)命令必须在 dispatch 里。"""
    assert "focus" in _dispatch_literals("quick_ctl.py")


def _func_def(name: str, fn: str) -> ast.FunctionDef:
    """从源码里取出指定名字的顶层(或任意层)FunctionDef 节点(精确名匹配)。"""
    tree = ast.parse(_src(name))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == fn:
            return node
    raise AssertionError(f"{name} 里找不到函数 {fn!r}")


def test_open_chat_no_or_across_locators():
    """open_chat 不得再用 `.or_(` 跨定位器合并 —— 那是触发 Playwright strict-mode 崩溃的根因。

    精确取 open_chat 的 FunctionDef(排除 open_chat_cycle),遍历其内所有 ast.Call,
    断言没有任何属性调用名为 or_(即 `xxx.or_(...)`)。strict-mode 下 a.or_(b) 会解析到
    多个元素,.first 不能约束合并集 —— 故改为三个独立 .count() 判定的候选依次点击。
    """
    fn = _func_def("quick_ctl.py", "open_chat")
    assert fn.name == "open_chat"  # 不是 open_chat_cycle
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr != "or_", "open_chat 仍在用 .or_() 跨定位器合并(会触发 strict-mode 崩溃)"


def test_open_chat_targets_option_role():
    """open_chat 必须点行([role=option]),不点标题 span —— 用源码片段断言 role/option 策略被钉住。"""
    fn = _func_def("quick_ctl.py", "open_chat")
    seg = ast.get_source_segment(_src("quick_ctl.py"), fn)
    assert seg is not None
    assert "option" in seg, "open_chat 不再定位 role=option 行"
    assert "role" in seg, "open_chat 不再按 role 定位"


def test_open_chat_cycle_no_or_across_locators():
    """open_chat_cycle 不得再用 `.or_(` 跨定位器合并 —— 与 open_chat 同根因的 strict-mode 崩溃。

    精确取 open_chat_cycle 的 FunctionDef,遍历其内所有 ast.Call,断言没有任何
    属性调用名为 or_(即 `xxx.or_(...)`)。切换对话的点击改为三个独立 .count() 判定的候选依次点行。
    """
    fn = _func_def("quick_ctl.py", "open_chat_cycle")
    assert fn.name == "open_chat_cycle"
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr != "or_", "open_chat_cycle 仍在用 .or_() 跨定位器合并(会触发 strict-mode 崩溃)"


def test_open_chat_cycle_targets_option_role():
    """open_chat_cycle 必须点行([role=option]),不点标题 span —— 源码片段断言 role/option 策略被钉住。"""
    fn = _func_def("quick_ctl.py", "open_chat_cycle")
    seg = ast.get_source_segment(_src("quick_ctl.py"), fn)
    assert seg is not None
    assert "option" in seg, "open_chat_cycle 不再定位 role=option 行"
    assert "role" in seg, "open_chat_cycle 不再按 role 定位"


def test_new_chat_targets_nav_home():
    """new_chat 必须改点主导航 "Chat"(data-testid=nav-home),不得再用裸 name="New chat" 选择器。

    真机确认此构建无全局 "New chat" 按钮,name="New chat" 只命中每文件夹的 "New chat in folder",
    会误把焦点落到顶部文件夹。精确取 new_chat 的源码片段断言:
      (a) 新选择器字面量 nav-home 已就位;
      (b) 旧的 name="New chat" 选择器已消失。
    """
    fn = _func_def("quick_ctl.py", "new_chat")
    seg = ast.get_source_segment(_src("quick_ctl.py"), fn)
    assert seg is not None
    assert "nav-home" in seg, "new_chat 未改用 data-testid=nav-home 选择器"
    assert 'name="New chat"' not in seg, "new_chat 仍在用裸 name=\"New chat\" 选择器(会误点每文件夹的 New chat in folder)"


@pytest.mark.parametrize("flag", ["--next", "--prev"])
def test_quick_ctl_open_chat_cycle_flags_present(flag):
    """open-chat 的循环切换标志必须作为 Compare 字面量出现在 dispatch 里。

    守护 open-chat --next/--prev 路由不被误删 —— Stream Deck 轮换按钮靠它。
    """
    assert flag in _dispatch_literals("quick_ctl.py"), \
        f"open-chat 循环标志 {flag!r} 从 quick_ctl.py 的 dispatch 中消失"


def test_quick_web_py_absent():
    """quick_web.py 不应存在。

    v1.x 一度认为"网页版控不了"而想另起一个脚本,后来证明是浏览器 profile 配置问题,
    不是能力问题。本断言现在的理由是【职责重复】:CDP 网页通道已由
    chrome_as.py + web_ensure.py 承担,不需要第三个脚本。
    """
    assert not os.path.isfile(os.path.join(SCRIPTS, "quick_web.py"))


def test_demo_py_relocated_to_ppt_repo():
    """剧本调度器 demo.py 已迁出 skill(回归纯能力),不应再在 skill 里。"""
    assert not os.path.isfile(os.path.join(SCRIPTS, "demo.py")), \
        "demo.py 是剧本,应住在 PPT repo 的 demo/,不在能力 skill 里"
