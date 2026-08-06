"""pytest 共享 fixture:检测真机通道是否可用,决定真机测试 skip。

两条 CDP 通道:桌面端 Quick Electron(:9333)、网页版 Chrome(:9445)。
"""
import json
import os
import socket
import sys
import urllib.request

import pytest

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPTS)

# 未登录判据必须与被测脚本**同源**:以前这里内联抄了一份特征元组,一改就两处分叉 ——
# fixture 判"已登录"而脚本判"未登录"(或反过来),真机测试的 skip 逻辑会静默漂移。
# web_ensure 只依赖标准库,import 它是安全的(别在这里 import chrome_as —— 它要 playwright)。
import web_ensure  # noqa: E402

# 必须与 chrome_as.py / web_ensure.py 读同一个环境变量,否则改了端口后
# fixture 仍探旧端口 → 判定"可用"却让被测脚本连错端口,测试假红。
WEB_PORT = int(os.environ.get("QUICK_WEB_CDP_PORT", "9445"))
DESKTOP_PORT = int(os.environ.get("QUICK_CDP_PORT", "9333"))


def _port_open(port: int, host: str = "127.0.0.1", timeout: float = 1.0) -> bool:
    """检测本机端口是否有服务监听。"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _cdp_json(port: int, path: str, timeout: float = 3.0):
    """请求 CDP HTTP 端点。端口通 ≠ 是 DevTools —— 必须验发现层真响应。

    2026-07-27 教训::9222 端口 LISTEN 但 /json/* 全 404(上面跑的是别的服务),
    仅探端口会把"不是 DevTools"误判成"DevTools 被封"。
    """
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:
        return None


def quick_desktop_available() -> bool:
    """Amazon Quick 桌面端是否带 CDP 调试端口在跑。"""
    return _port_open(DESKTOP_PORT)


def web_cdp_available() -> bool:
    """网页版 CDP 发现层是否真可用。"""
    return _cdp_json(WEB_PORT, "/json/version") is not None


def web_signed_in() -> bool:
    """网页版是否已登录(有 quicksight 标签且不在登录页)。"""
    markers = web_ensure.unauth_markers()
    targets = _cdp_json(WEB_PORT, "/json/list") or []
    for t in targets:
        if not isinstance(t, dict) or t.get("type") != "page":
            continue
        url = (t.get("url") or "").lower()
        if "quicksight" in url:
            return not any(m in url for m in markers)
    return False


@pytest.fixture(scope="session")
def quick_available():
    """真机 fixture:Quick 桌面端不在跑则跳过依赖它的测试。"""
    if not quick_desktop_available():
        pytest.skip(
            f"Amazon Quick 桌面端(CDP:{DESKTOP_PORT})未运行 —— 真机测试跳过。启动 Quick 后重跑。"
        )
    return True


@pytest.fixture(scope="session")
def web_available():
    """真机 fixture:网页版 CDP 通道未就绪或未登录则跳过。"""
    if not web_cdp_available():
        pytest.skip(
            f"网页版 CDP(:{WEB_PORT})未就绪 —— 跑 "
            "`uv run python scripts/web_ensure.py ensure` 后重试。"
        )
    if not web_signed_in():
        pytest.skip(
            "网页版未登录 —— 跑 `uv run python scripts/web_ensure.py login` "
            "并在打开的 Chrome 窗口里完成登录后重试。"
        )
    return True
