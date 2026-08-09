"""E2E 测试:真机操作 Amazon Quick。

两条通道:桌面端 Electron(CDP:9333)、网页版 Chrome(CDP:9445)。
通道未就绪时对应测试自动 skip(见 conftest 的 quick_available / web_available)。
⚠️ 只做只读/无副作用操作 —— 绝不建/删/共享任何资产。"""
import json
import os
import subprocess
import time

import pytest

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")


def _run(script, *args, timeout=60):
    cmd = ["uv", "run", "--with", "playwright", "python",
           os.path.join(SCRIPTS, script), *args]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return (r.stdout or "") + (r.stderr or "")


def _run_json(script, *args, timeout=60):
    """只取 stdout 并解析 JSON —— uv 会往 stderr 写安装进度,混入会破坏解析。"""
    cmd = ["uv", "run", "--with", "playwright", "python",
           os.path.join(SCRIPTS, script), *args]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return json.loads(r.stdout)


def _settled_state(tries=4):
    """轮询 chrome_as state 直到不在重定向中途。

    E2E 各项共享同一个浏览器标签,前序测试的 goto 若正处于 SPA 重定向瞬间,
    URL 会短暂落在登录/授权路径(signin/login/authorize…),导致 signedIn 瞬时为 False。
    只在【已登录】这一真实前提下重试;真的掉线会重试到底仍 False,不会掩盖问题。
    """
    d = {}
    for _ in range(tries):
        d = _run_json("chrome_as.py", "state", timeout=40)
        if d.get("signedIn") is True:
            return d
        time.sleep(2)  # nosemgrep: arbitrary-sleep -- 浏览器/应用自动化必须等渲染或 CDP 响应,非忙等
    return d


@pytest.mark.realmachine
def test_quick_ctl_status(quick_available):
    """quick_ctl status 能连上桌面端 Quick。"""
    out = _run("quick_ctl.py", "status")
    assert '"connected": true' in out, f"status 未连上: {out[:200]}"


@pytest.mark.realmachine
def test_quick_ctl_port_9333(quick_available):
    """状态里报告的是 9333 端口(桌面端专用)。"""
    out = _run("quick_ctl.py", "status")
    assert "9333" in out


@pytest.mark.realmachine
def test_quick_ctl_read(quick_available):
    """能读到当前对话文本(基础读通路)。"""
    out = _run("quick_ctl.py", "read", timeout=40)
    # 读到东西即可(内容随对话变)
    assert len(out.strip()) > 0


# ───────── 网页版 CDP 通道(:9445),v2.0 新增。全部只读 ─────────

@pytest.mark.realmachine
def test_web_ensure_status(web_available):
    """web_ensure status 输出合法 JSON 且通道就绪。"""
    d = _run_json("web_ensure.py", "status", timeout=30)
    assert d["cdp_ok"] is True
    assert d["signed_in"] is True


@pytest.mark.realmachine
def test_web_state_signed_in(web_available):
    """chrome_as state 返回契约格式 JSON 且已登录。"""
    d = _settled_state()
    assert d["signedIn"] is True, f"未登录或重定向未收敛: {d.get('url', '')[:100]}"
    assert "quicksight" in d["url"]


@pytest.mark.realmachine
def test_web_goto_and_list(web_available):
    """goto 到 spaces 后能读到列表(读通路端到端)。"""
    out = _run("chrome_as.py", "goto", "spaces", timeout=60)
    assert "→ goto spaces" in out
    listed = _run("chrome_as.py", "list", timeout=60)
    assert listed.startswith("共") and "行:" in listed


@pytest.mark.realmachine
def test_web_screenshot(web_available, tmp_path):
    """CDP 原生截图可用(v1.x AppleScript 时代做不到)。"""
    png = tmp_path / "web.png"
    out = _run("chrome_as.py", "screenshot", str(png), timeout=60)
    assert "✓ 截图" in out
    assert png.is_file() and png.stat().st_size > 10_000


@pytest.mark.realmachine
def test_web_soft_failure_exits_zero(web_available):
    """契约:软失败(NOTFOUND)打印到 stdout 且退出码 0 —— 调用方可能用 set -e。"""
    cmd = ["uv", "run", "--with", "playwright", "python",
           os.path.join(SCRIPTS, "chrome_as.py"), "click", "quicksight", "不存在按钮ZZZ"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "软失败不应非零退出"
    assert "NOTFOUND:" in r.stdout


def test_web_delete_space_requires_confirm():
    """契约:delete-space 缺 --confirm 必须 exit 2(不需真机,不会碰到资产)。"""
    cmd = ["uv", "run", "--with", "playwright", "python",
           os.path.join(SCRIPTS, "chrome_as.py"), "delete-space", "任意不存在的空间"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    assert r.returncode == 2, "缺 --confirm 时必须拒绝执行并 exit 2"
