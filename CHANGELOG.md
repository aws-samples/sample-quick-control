# Changelog

本项目所有重要变更记录于此。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，
版本遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [2.0.0] - 2026-07-27

**架构收敛：双目标 · 单协议。** 网页版通道底层从 AppleScript 换成 CDP，两条通道（桌面端 Electron `:9333` / 网页版 Chrome `:9445`）从此说同一种协议。触发这次迁移的不是新需求，而是**发现 v1.x 把网页通道锁在 AppleScript 上的那条技术结论是误判**（见 Fixed）。

### Breaking
- **网页版通道底层由 AppleScript 改为 CDP/playwright**：`chrome_as.py` 不再走 macOS Apple Events + `execute javascript`，而是连持久 profile Chrome（`~/.chrome-cdp-profile`，`--remote-debugging-port=9445`）。脚本名保留是刻意的——**CLI 契约完全未变**：35 个命令名、stdout 逐字格式、退出码语义（`0` 成功/软失败 · `1` 硬错 · `2` 用法错）一字不改。**既有剧本（PPT repo 的 `demo/demo.py`）用 `subprocess` 调用并解析 stdout，无需改动一行。**
- **新增前置步骤 `web_ensure.py`**：v1.x 借用你已登录的主 Chrome，无前置；CDP 通道跑在自己的 profile 里，**首次必须** `uv run python web_ensure.py ensure`（起实例）+ `login`（在打开的窗口里人工完成登录）。之后登录态**持久**在该 profile 目录里，重启该 CDP 实例无需重新认证，日常只需 `ensure`（幂等）。这是把"能不能连上"从每次调用的隐式赌注，变成一次显式、可体检的准备动作。

### Added
- **`web_ensure.py`** —— 网页通道的就绪层：`ensure`（幂等起带 CDP 的持久 profile Chrome）/ `status`（JSON 吐 `cdp_ok`/`signed_in`/`url`/`tabs`）/ `login`（打开网页版等人工登录，不自动登录、不代填凭证）/ `doctor`（逐项体检 + 人类可读修复建议）/ `restart`。
- **登录判据与起始 URL 全部可配置**：未登录页特征走 `QUICK_UNAUTH_MARKERS`（逗号分隔，默认 `signin,login,authorize,oauth,sso`），起始 URL 走 `QUICK_WEB_REGION`/`QUICK_WEB_ACCOUNT`（或 `QUICK_WEB_BASE` 整体覆盖）。代码里不内置任何具体账户名或身份提供方域名。
- **`chrome_as.py screenshot [路径]`** —— CDP 原生截图。v1.x 做不到：AppleScript 通道要靠 `screencapture`，而终端进程没有屏幕录制权限，现场只能靠肉眼确认。现在截图走浏览器自己，**不需要任何系统权限，也不需要窗口在前台**。
- **测试 25 → 82 项**（单元 19 + E2E 9 + 回归 54）。核心是回归层的 **35 个命令逐个契约护栏**：用 AST 解析 dispatch 收集命令字面量，**不绑死 `if/elif` 写法**，重构 dispatch 结构不会假红、少一个命令一定报红。护栏本身做过**突变测试验证**：删掉一个命令分支 → 对应契约项精确报红；把 `run_osa` 加回去 → AppleScript 回归项报红；两次突变后 `diff` 确认逐字还原。

### Changed
- **`chrome_as.py` 底层实现重写**（约 1400 行 diff），命令层与 UI 映射沿用 v1.x 真机验证结果——**已验证过的 UI 知识是资产，不因换协议重新探测一遍**。
- **`tests/conftest.py` 的通道探测改为验发现层真响应**（请求 `/json/version`）而非只探端口 LISTEN，且端口从 `QUICK_WEB_CDP_PORT`/`QUICK_CDP_PORT` 读、与被测脚本同源。理由直接来自本次纠错：`:9222` 端口开着但上面**不是** DevTools，只探 LISTEN 正是 v1.x 那个误判的成因；端口写死则改端口就假红。
- **文档架构表改为「双目标 · 单协议（CDP）」**，并显式登记端口分工：`:9333` Quick Electron · `:9445` CDP Chrome · **`:9222` 与 DevTools 无关的其他服务，勿连**。把踩过的坑写进架构表，比写进 troubleshooting 更难被忽略。

### Fixed
- **v1.x「CDP 走不通」是归因错误，不是新发现。** 必须如实记账：v0.3.0 写下的"CDP-主 profile ❌：主 Chrome 带 `:9222` 但 `/json/*` 全 404，DevTools 发现层被策略掐死"——**现象对、归因全错**。主 Chrome **根本没带** `--remote-debugging-port`，`:9222` 上监听的是与 DevTools 无关的另一个服务，所以 `/json/*` 返回 404 完全正常，playwright 那句 `This does not look like a DevTools server` 是**字面为真**的正确报错。一个可修的本地配置缺失，被写成了不可逾越的红线，并据此把整条网页通道锁在 AppleScript 上将近一个版本周期。
  - **真正的教训：先验证目标进程的启动参数，再谈环境限制。** 端口监听 ≠ 该端口是你要的服务。v1.x 跳过了第一步，直接跳到最不可证伪的解释（"就是被策略封了"）——这类解释一旦写进文档就没人再挑战它。
- **同时纠正 v1.x「CDP-独立 profile 起不来」的结论。** 独立 `--user-data-dir` + `--remote-debugging-port` 的组合实测可用，当年遇到的是本机 profile 层面的一处配置缺失，不是协议或平台的硬限制。现在这条就是默认通道：`web_ensure.py ensure` 幂等起实例，登录态持久化在该 profile 目录里。
  - **边界（不可含糊）**：本项目**不自动化身份认证**——`login` 只打开页面并等你在那个窗口里亲手登录，工具不代填凭证、不代过 MFA，无人值守拿不到会话。它拿到的权限就是你自己登录出来的会话权限，不提权、不绕过任何访问控制。

### Removed
- **三层转义（shell → AppleScript → JS）**。v1.x 每个命令都要穿三层引号，加个选择器就得数反斜杠；CDP 直接传 Python 字符串。
- **JS 强制 ES5**。AppleScript 注入的 JS 受宿主限制不能用箭头函数/模板串/`const`；CDP 下用 playwright locator API，多数场景连 JS 都不用写。
- **写输入框的 `pbcopy` + 提标签到前台 + `Cmd+V` 粘贴 hack**（v1.0.0 为绕 MUI/Vega 反自动化引入）。CDP 下 `locator.fill()` 直接生效，**写操作变成静默后台执行**——不再抢用户焦点、不再劫持剪贴板，现场演示时你可以同时用别的窗口。

## [1.1.0] - 2026-07-24

**架构分层：演员与剧本分离。** skill 回归纯通用能力，具体演示剧本归位到各 PPT repo。

### Changed
- **`demo.py` 剧本调度器迁出本 skill** → 到各自的演示 repo 的 `demo/` 目录。理由：`demo.py` 含场景专用 prompt/暗号/埋点，是"这一场的剧本"，不该焊死在通用能力 skill 里（机制 vs 策略分层）。换场景 → 新演示 repo 写自己的剧本，复用本 skill。
- README / SKILL.md 的"现场演示"章节改为"被剧本调用"，示例指向演示 repo 的 `demo/demo.py`。

### Removed
- `scripts/demo.py`、`docs/signals.md`（暗号协议详解，随剧本迁到 PPT repo）。
- 测试中的剧本断言（暗号 dispatch / flow1 三关 / prep 真机）随之迁到 PPT repo 的 `tests/test_demo.py`。

### Kept
- 通用能力全保留：`quick_ctl.py`（桌面 CDP）、`chrome_as.py`（网页 AppleScript，v2.0.0 起改为 CDP）及其全部命令与测试（25 项）。

## [1.0.0] - 2026-07-23

首个稳定版：桌面端 + 网页版双通道全打通，暗号驱动现场演示系统成型。

### Added
- **暗号调度器 `demo.py`**：11 个暗号（`prep`/`open`/`r1`/`c1`/`c2`/`app1`/`flow1`/`rs1`/`rs2`/`stop`/`shot`），一个词驱动 Quick 完成一整套现场演示动作。
- **`flow1` 半自动闯三关**：创建定时任务时自动应答「数据来源选择 → 权限确认框(Always allow) → 收尾追问」，全自动建成 Flow。
- **网页版写命令**：`create-space` / `delete-space --confirm`，真机验证可复现闭环。
- **测试三件套**：单元（纯函数，无真机）+ E2E（真机，Quick 未跑自动 skip）+ 回归（暗号系统完整性），共 33 项。
- **动态架构图** `docs/architecture.svg`（SMIL 动画：marching-ants 流动线 + 请求点）。

### Changed
- 路径自包含：`demo.py` 的 `quick_ctl.py` 改为相对自身路径，可 clone 到任意机器运行。
- 总控台文件名通用化（去客户名）。

### Fixed
- **生成 artifact 的完成检测**：Quick 生成看板有长静默期（跑 Python 时 UI 不吐字），`_wait_idle` 的「文字稳定」会提前误判完成。改为 `wait-done`（看 Stop 按钮消失）+ 固定缓冲（收入 22s / 成本 30s），原则「可靠 >> 快」。
- **删除确认 i18n bug**：删除空间弹窗提示「键入 Delete」，但实际校验中文「删除」——纯 JS 注入被 MUI/Vega 反自动化挡，改用剪贴板 `pbcopy` + 提前台 + `Cmd+V` 真实粘贴。
- **SPA 时序**：所有点击/行定位改自重试轮询，不用固定 sleep。

### Removed
- 删除废方案 `quick_web.py`（CDP + 独立 profile，当时判定起不来的死代码；该判定后在 v2.0.0 被纠正）。

---

## [0.4.0] - 2026-07-22

### Added
- 网页版读命令层：`goto`（11 区导航）/ `list` / `view` / `filter` / `sort` / `page` / `search` / `wait-text` / `dump`，跨区复用。
- workflow 深度审计网页版 11 区共 122 个操作（100 读 + 22 写），产出完整能力矩阵。

### Fixed
- 结论：除 apps「附加文件」触发的原生系统文件选择器（浏览器沙箱边界）外，其余 121 操作原理上都能被 AppleScript 驱动。

## [0.3.0] - 2026-07-22

### Added
- **AppleScript 通道 `chrome_as.py`**：走 macOS Apple Events 遥控主 Chrome，复用主浏览器现成的登录态，不碰调试端口、不需重启。原语：`tabs`/`state`/`buttons`/`click`/`fill`/`eval`/`evalf`。

### Fixed
- **网页版三方案实测终局**：CDP-独立 profile ❌（起不来）；CDP-主 profile ❌（主 Chrome 带 :9222 但 `/json/*` 全 404，判为 DevTools 发现层被策略掐死）；**AppleScript ✅ 唯一可行**（零重启零打扰）。
  > ⚠️ **此条结论后被 v2.0.0 推翻**：前两条一个是本机配置缺失、一个是纯归因错误，见 v2.0.0 的 Fixed。保留原文是为了让这次误判有迹可查。

## [0.2.0] - 2026-07-22

### Added
- 桌面端穷尽 skill 化：消息操作 / 顶栏 / My computer / Capabilities / My context / Customization 全覆盖，实测 Research / Application / Flows / Chat agents 自然语言触发。

## [0.1.0] - 2026-07-22

### Added
- 桌面端 CDP 控制 `quick_ctl.py`（`--remote-debugging-port=9333`）：send/ask/read/new-chat/set-model/attach/nav 等，27 项能力真机验证。
