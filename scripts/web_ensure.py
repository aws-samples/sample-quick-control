#!/usr/bin/env python3
"""web_ensure.py — 确保网页版 CDP 通道就绪（持久 profile Chrome + 登录态）。

一律用: uv run python web_ensure.py <命令>

━━━ 命令 ━━━
  ensure     幂等确保带 CDP 的持久 profile Chrome 在跑
  status     JSON 输出 {cdp_ok, signed_in, url, tabs, port, profile}
  login      打开 Amazon Quick 网页版并等你在该窗口里手动完成登录（不自动登录）
  doctor     逐项体检 + 人类可读修复建议
  restart    重启该 profile 的 Chrome 实例（改端口/清状态后用）

━━━ 为什么用独立的持久 profile ━━━
CDP 需要 --remote-debugging-port，而多数 Chrome 不会给日常主 profile 开这个端口。
独立的 --user-data-dir 让调试实例与主浏览器互不干扰，同时把登录 cookie 持久化在
该目录里 —— 只需首次人工登录一次，后续 ensure 都是幂等的。

━━━ 环境变量 ━━━
  QUICK_WEB_CDP_PORT     CDP 端口（默认 9445）
  QUICK_WEB_PROFILE      持久 profile 目录（默认 ~/.chrome-cdp-profile）
  QUICK_WEB_REGION       Quick 所在区域（默认 us-east-1）
  QUICK_WEB_ACCOUNT      你的 Quick 账户名（默认为占位符，必须按需设置）
  QUICK_WEB_BASE         直接整体覆盖起始 URL 前缀（设了则忽略上面两项）
  QUICK_UNAUTH_MARKERS   未登录页 URL 特征，逗号分隔（默认见 DEFAULT_UNAUTH_MARKERS）
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

PORT = os.environ.get("QUICK_WEB_CDP_PORT", "9445")
PROFILE = Path(os.environ.get("QUICK_WEB_PROFILE", str(Path.home() / ".chrome-cdp-profile")))
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# 起始 URL 前缀。故意只给占位账户名：账户名因人/因组织而异，代码里不内置任何具体账户。
# rstrip+"/" 保证结尾一定有斜杠，后面可以直接拼 slug。
# 注意：这几行与 chrome_as.py 里的同名常量是**有意重复**的（两个脚本都要能单独跑，
# 且回归测试要求端口/URL 约定在各自文件里可见）；权威来源是环境变量名本身。
WEB_BASE = os.environ.get(
    "QUICK_WEB_BASE",
    "https://{}.quicksight.aws.amazon.com/sn/account/{}/start/".format(
        os.environ.get("QUICK_WEB_REGION", "us-east-1"),
        os.environ.get("QUICK_WEB_ACCOUNT", "your-quick-account"),
    ),
).rstrip("/") + "/"
START_URL = WEB_BASE + "spaces"

# 未登录页的 URL 特征：命中任一即视为未登录。默认是通用的登录/授权路径关键词，
# 不绑定任何具体身份提供方 —— 各组织的 IdP 域名不同，用 QUICK_UNAUTH_MARKERS 覆盖即可。
DEFAULT_UNAUTH_MARKERS = ("signin", "login", "authorize", "oauth", "sso")


def unauth_markers() -> tuple[str, ...]:
    """返回当前生效的未登录页特征（小写）。每次现读环境变量，便于按环境覆盖。"""
    raw = os.environ.get("QUICK_UNAUTH_MARKERS", "")
    items = tuple(m.strip().lower() for m in raw.split(",") if m.strip())
    return items or DEFAULT_UNAUTH_MARKERS


def _cdp(path: str) -> object | None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}{path}", timeout=3) as r:
            return json.loads(r.read())
    except Exception:
        return None


def cdp_ok() -> bool:
    return _cdp("/json/version") is not None


def _pages() -> list[dict]:
    targets = _cdp("/json/list") or []
    return [t for t in targets if isinstance(t, dict) and t.get("type") == "page"]


def _qs_page() -> dict | None:
    return next((p for p in _pages() if "quicksight" in (p.get("url") or "")), None)


def signed_in() -> bool:
    p = _qs_page()
    if p is None:
        return False
    url = (p.get("url") or "").lower()
    return not any(m in url for m in unauth_markers())


def _launch() -> None:
    PROFILE.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(
        [
            CHROME,
            f"--user-data-dir={PROFILE}",
            f"--remote-debugging-port={PORT}",
            "--no-first-run",
            "--no-default-browser-check",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def open_tab(url: str) -> bool:
    """经 CDP HTTP 端点开标签。不用 playwright new_page（那会报 context management 不支持）。"""
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{PORT}/json/new?{url}", method="PUT"
        )
        urllib.request.urlopen(req, timeout=8).read()
        return True
    except Exception:
        return False


def ensure() -> None:
    if cdp_ok():
        print(f"✓ CDP 已就绪 (port {PORT})")
        return

    if not Path(CHROME).is_file():
        print(f"✗ 未找到 Chrome: {CHROME}", file=sys.stderr)
        sys.exit(1)

    print(f"启动 Chrome (profile={PROFILE}, port={PORT})...")
    _launch()
    for _ in range(30):
        time.sleep(1)
        if cdp_ok():
            print(f"✓ CDP 已就绪 (port {PORT})")
            if not signed_in():
                print("⚠ 尚未登录 —— 跑 `web_ensure.py login`，然后在打开的窗口里登录")
            return
    print(f"✗ 启动后 {PORT} 仍不可用", file=sys.stderr)
    sys.exit(1)


def status() -> None:
    p = _qs_page()
    print(
        json.dumps(
            {
                "cdp_ok": cdp_ok(),
                "signed_in": signed_in(),
                "url": (p or {}).get("url", "")[:120],
                "tabs": len(_pages()),
                "port": PORT,
                "profile": str(PROFILE),
            },
            ensure_ascii=False,
            indent=1,
        )
    )


def login(timeout: int = 300) -> None:
    if not cdp_ok():
        print("✗ CDP 未就绪，先跑 ensure", file=sys.stderr)
        sys.exit(1)
    if signed_in():
        print("✓ 已登录")
        return
    if _qs_page() is None:
        open_tab(START_URL)
    print("→ 已打开 Amazon Quick 网页版。请在该 Chrome 窗口里手动完成登录。")
    print("  登录状态会存在这个持久 profile 里，之后不必重复登录。")
    print(f"  等待中（最多 {timeout}s）...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(3)
        if signed_in():
            print("✓ 登录成功")
            return
    print("✗ 等待超时 —— 未检测到登录成功", file=sys.stderr)
    sys.exit(1)


def doctor() -> None:
    print("═══ 网页版 CDP 通道体检 ═══")
    ok = True

    print(f"\n[1] CDP 端口 {PORT}")
    if cdp_ok():
        v = _cdp("/json/version") or {}
        print(f"  ✓ 可用 — {v.get('Browser', '?')}")
    else:
        ok = False
        print("  ✗ 不可用")
        print(f"  → 修复: uv run python {Path(__file__).name} ensure")

    print("\n[2] 登录态")
    if signed_in():
        p = _qs_page() or {}
        print(f"  ✓ 已登录 — {(p.get('url') or '')[:80]}")
    else:
        ok = False
        p = _qs_page()
        print(f"  ✗ 未登录 — 当前: {((p or {}).get('url') or '(无 quicksight 标签)')[:80]}")
        print(f"  → 修复: uv run python {Path(__file__).name} login（在打开的窗口里登录）")
        print(f"  → 未登录判据: URL 命中 {list(unauth_markers())}（QUICK_UNAUTH_MARKERS 可覆盖）")

    print(f"\n═══ {'全部就绪' if ok else '存在问题，见上方修复建议'} ═══")
    if not ok:
        sys.exit(1)


def restart() -> None:
    subprocess.run(["pkill", "-f", f"user-data-dir={PROFILE}"], capture_output=True)
    time.sleep(3)
    _launch()
    for _ in range(30):
        time.sleep(1)
        if cdp_ok():
            print(f"✓ 已重启 (port {PORT})")
            return
    print("✗ 重启后 CDP 不可用", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1]
    if cmd == "ensure":
        ensure()
    elif cmd == "status":
        status()
    elif cmd == "login":
        login(int(sys.argv[2]) if len(sys.argv) > 2 else 300)
    elif cmd == "doctor":
        doctor()
    elif cmd == "restart":
        restart()
    else:
        print(f"未知命令: {cmd}\n{__doc__}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
