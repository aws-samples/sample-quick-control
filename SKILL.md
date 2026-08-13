---
name: amazon-quick-control
description: 程序化控制本机 macOS 上的 Amazon Quick——桌面端（Electron，CDP :9333）发消息/收回复、开新对话、切历史、切模型/思考强度、上传文件、@agent、看 Activity feed、Mission Control、连接器、生成交付物；网页版（Chrome CDP :9445，quicksight.aws.amazon.com）11 区导航/搜索/筛选/建删空间/建发布 App。凡 Quick 界面能点的都能自动化。触发词：控制 Amazon Quick、操纵 Quick、自动化 Quick、让 Quick 做、在 Quick 里、Quick desktop 自动化、quick_ctl、Quick 网页版、quicksight 网页自动化、Quick Spaces、建空间、发布 Quick App。当用户要用 AI 自动驱动本机 Amazon Quick 桌面客户端或其网页版执行任何操作时使用。
---

# Amazon Quick 控制 skill

通过 **Chrome DevTools Protocol（CDP）** 控制本机 Amazon Quick 的**两个目标**，协议统一，差异只在进程与端口：

| 目标 | 进程 | 端口 |
|---|---|---|
| 桌面端 | Amazon Quick.app（Electron） | `:9333` |
| 网页版 | Google Chrome（持久 profile `~/.chrome-cdp-profile`）→ `quicksight.aws.amazon.com` | `:9445` |

已在真机验证：桌面端读界面 / 输入 / 发送 / 收回复 / 全 UI 导航全部打通；网页版 CDP 通道打通（含登录态持久、`locator.fill()` 直写 MUI）。

## 前提

- **本 skill 以软链接方式安装**：`~/.claude/skills/amazon-quick-control` → 仓库 clone 处（如 `~/Code/sample-quick-control`）。下文命令里的 `~/.claude/skills/amazon-quick-control/scripts` 与仓库内 `scripts/` 是同一份文件，改代码即时生效。若该软链接不存在，见 [README.zh-CN.md](./README.zh-CN.md) 的「安装」节（英文版：[README.md](./README.md)）。
- 本机已装 `/Applications/Amazon Quick.app` 且已登录。
- Quick 必须**带调试端口运行**。skill 的 `ensure` 会自动处理（未开则重启加参数）。
- 一律用 `uv run --with playwright`（用户全局铁律：Python 用 uv）。
- **首次**在新机器上需装浏览器驱动一次：`uv run --with playwright python -m playwright install chromium`（连本机 Electron 其实不需要下载 Chromium，但 playwright 包要在）。

## 快速开始

```bash
cd ~/.claude/skills/amazon-quick-control/scripts
Q="uv run --with playwright python quick_ctl.py"

$Q ensure                      # 确保带调试端口运行(未开会重启)
$Q status                      # 连接/模型状态
$Q ask "帮我分析这份收入数据的异常"   # 发送并等回复
$Q screenshot /tmp/q.png       # 截图看结果
```

## 核心铁律（踩坑固化，改脚本必读）

1. **调试端口**：Quick 默认不开 CDP。`ensure` 用 `--remote-debugging-port=9333` 启动可执行文件（`open --args` 对 Electron 不可靠，必须直接跑 `.../MacOS/Amazon Quick`）。端口可用 `QUICK_CDP_PORT` 改。
2. **连对不连错**：`:9222` 已被**与 DevTools 无关的其他服务**占用（不是 Chrome 的调试端口），所以桌面端用 `:9333`、网页 CDP 用 `:9445`。连接时按 `title=="Amazon Quick"` 选主渲染窗口，不要 `pages[0]`。<br>端口分工：`:9333` Quick Electron · `:9445` CDP Chrome（`~/.chrome-cdp-profile`）· `:9222` 无关服务，**勿连**。<br>⚠️ 这条曾是误判之源：v1.x 把 `:9222` 的 `/json/* 404` 读成"DevTools 被策略掐死"，实为那个端口上就没有 DevTools。
3. **Settings 子项必须 JS click**：`Capabilities/My computer/My context/Customization` 是 `button.settings-sub-item`，被 `chat-section-content` DIV 覆盖，普通 click 和 force click 都被遮挡打不中——**必须 `locator.evaluate("el=>el.click()")`**。已封装在 `_click_setting()`。
4. **等生成结束**：发送后用 `_wait_idle()`（文字稳定 2 轮 + 无 Stop 按钮）判定完成，别用固定 sleep。
5. **输入框**：`placeholder` 含 "Ask a question" 的 textarea；输入前先 `Meta+A`→`Backspace` 清空。
6. **每条命令独立连接**：`quick_ctl.py` 每次调用新建 CDP 连接（简单可靠）；批量操作若嫌慢，写单会话脚本参照 `crawl_all.py`。
7. **单实例（桌面端）**：Quick 只有一个窗口一个控制通道。**不要并发**多个脚本同时驱动，会抢输入框/导航状态打架。要并行只能并行"分析已 dump 的界面数据"，动作串行。
8. **单实例（网页端，同等约束）**：真机只有**一个** CDP Chrome 实例、单会话。**不要并发驱动**；**只读优先**，一次一个动作；写操作先确认。并发会互相抢导航/焦点，且在生产资产上出错代价高。

## 全部命令（对应 UI 每个可操作处）

运行 `uv run --with playwright python quick_ctl.py`（无参数）看完整帮助。分组：

| 组 | 命令 | 说明 |
|---|---|---|
| 连接 | `ensure` `status` `screenshot` `map` | map= dump 当前屏所有可点元素 |
| 对话 | `send` `ask` `type` `clear-input` `read [--full]` `stop` `new-chat` `regenerate` | `type` 只输入不发(现场演示用) |
| 历史 | `list-chats` `open-chat` `delete-chat --yes` `search-chats` `export` | delete 需 --yes |
| 模型 | `set-model Fast\|Balanced\|Smart` `set-effort Low\|Med\|High` `set-mode` | |
| 上下文 | `attach <文件>` `add-folder` `add-space` `web-search-toggle` | +号菜单：Upload files/Choose a folder/Spaces/Web search |
| 导航 | `nav <New chat\|Activity feed\|My stuff\|Agents & skills\|Mission control>` `settings <子页>` | |
| 功能区 | `feed [--ask]` `feed-done` `agents [--search]` `run-agent <名>` `mission [--filter]` `connectors [--search]` `artifacts` | |
| 消息操作 | `msg-copy` `msg-reply` `msg-edit` `msg-react` `msg-more` | 实测：assistant气泡=Agent actions/Copy/Reply/React；user气泡=Copy/Reply/Edit。用 `.message.assistant`/`.message.user` 内 JS click |
| 顶栏 | `task-list` `session-tabs` | 需在对话页(顶栏图标 x>1500) |
| 本地文件 | `list-folders` `add-folder-dialog` `remove-folder` | My computer：本地文件夹授权管理 |
| 连接器 | `refresh-connections` | Capabilities 页 |
| 知识图谱/记忆 | `context-graph [--search]` `context-memory` `refresh-graph` | My context：graph标签=Refresh graph，Memory标签=Refresh memories |
| 个性化 | `set-theme <名>` `set-feed-interval` `set-send-key` `set-browser` `set-response-pref "<偏好>"` `toggle-feed-source <名>` `clear-all-data --yes` | Customization：7主题/feed源开关/频率/自动化浏览器/发送键/回复偏好；clear需--yes |
| 逃生舱 | `click "<文字>"` `click-role "<label>"` `eval "<js>"` `wait-idle` | 任意元素兜底 |

### 穷尽核对（2026-07 实测，桌面版全覆盖）
逐屏 dump 后确认已 skill 化的完整清单：主聊天(对话/模型/思考强度/附件/+号菜单4项) · 消息操作栏(user+assistant 全部按钮) · 顶栏(Task list/Session tabs/Export/Mission control) · 历史(列/开/搜/删/导出) · Activity feed · My stuff · Agents & skills(搜索/Create/@运行) · Mission Control(过滤/运行详情) · Settings 全 4 子页(Capabilities连接器 / My computer本地文件夹 / My context知识图谱+记忆 / Customization 7主题+feed源+频率+浏览器+发送键+回复偏好+Clear all data) · 自然语言触发 Research/Application/Flows/Spaces。**桌面端 UI 能点的均已覆盖**；`More` 菜单 6 项跳网页版，其能力多数已由桌面自然语言覆盖，**且网页版本身现已可程序化打开**——用 CDP 实例的 HTTP `PUT /json/new?<url>` 开页，持久 profile 里的登录态无需重认证（见网页 CDP 通道）。

## 现场演示配合

做分享时 PPT 与 Quick 交替，可用 `type`（把 prompt 打进去让观众看，不急着发）或 `ask`（直接出结果）。示例：
```bash
$Q new-chat
$Q attach ./sample-data/revenue_weekly.csv
$Q ask "做交互式周度收入看板：总览/趋势/按分部/按区域/按产品5个tab+热力图,涨绿跌红"
$Q screenshot /tmp/demo1.png    # 投屏或存档
```

## 界面图谱

`scripts/` 下有采集工具：`map_screen.py`（单屏）、`crawl_all.py`（遍历所有屏）。各屏元素 dump 在 `/tmp/quickmap/*.json`。已知界面：主聊天、Activity feed、My stuff、Agents & skills、Mission control、Settings(Capabilities/My computer/My context/Customization)、模型菜单、+号菜单。

## 验证

`uv run --with playwright python scripts/verify_all.py` 单会话跑遍所有能力出 PASS/FAIL 报告。

## 网页版功能 vs 桌面端触发（重要结论，2026-07 实测）

`More` 菜单里的 **Apps / Chat agents / Research / Flows / Spaces / Dashboards** 是 `quick-web-menu-item`，点击跳**浏览器网页版**（Quick 的 web 控制台，需在浏览器里已登录）。

- ✅ **多数能力桌面端用自然语言就能触发**（已实测通过 CDP:9333）：
  - **Research（深度研究）**：`ask "深度研究 XX 课题"` → 桌面端自动 Browsed links / Searching web / Fetching，原生跑深度研究。✅
  - **Application（应用程序/Apps）**：`ask "帮我做一个网页表单应用收集…"` → 桌面端 Loading HTML Design skill → 生成含表单/统计/CSV导出/localStorage 的完整 App，内联在对话里可交互。✅
  - **Flows / Scheduled Tasks**：`ask "创建每周一早8点跑报告的定时任务…"` → 桌面 Flow/定时任务。✅
  - **Chat agents**：`ask "创建 XX agent"` → 交互式创建+配置（**写操作会弹权限确认框，需点 Allow**）。✅
- ⚠️ **两个硬缺口（桌面对话做不到）**：**Spaces 的"创建"**（无 `create_space` 工具，只能上传/搜索已有）、**原生 QuickSight Dashboard 的创建/发布**（只能查已有，创建限 Web 控制台）。这两个必须走**网页版**——见下方[网页版 CDP 通道](#网页版控制从-applescript-到-cdp)。

### 网页版控制：从 AppleScript 到 CDP

要自动化上面两个缺口，必须控制 Quick 网页版。早期版本（v1.x）曾判定"CDP 走不通、只有
AppleScript 可行"，后经真机复核，**那两条 CDP 结论都是误判或归因错误**：

| 方案 | v1.x 结论 | 真机复核 |
|---|:---:|---|
| **CDP-独立 profile** | ❌ 起不来 | ✅ **可行**，这就是现在的通道。独立 `--user-data-dir` + `--remote-debugging-port` 即可，登录态持久化在该目录里，首次人工登录一次就够 |
| **CDP-主 profile** | ❌ `/json/*` 全 404，"DevTools 发现层被策略掐死" | ❌ 结论对、**归因全错（反面教材）**。主 Chrome **根本没带** `--remote-debugging-port`；`:9222` 上是**与 DevTools 无关的其他服务**，404 完全正常，playwright 的 `This does not look like a DevTools server` **字面为真**。"被策略掐死"是凭空归因 |
| **AppleScript execute-javascript** | ✅ **唯一可行** | ✅（v1.x 通道，**已被 CDP 取代**）。功能确实读写俱全，代价是三层转义、JS 被迫 ES5、写操作靠剪贴板 hack 且**必须提标签到前台**（并非"零打扰"） |

**教训（仍有效）**：**端口监听 ≠ 可用**；正确的排查顺序是**先验证目标进程的启动参数，
再谈环境/策略限制** —— v1.x 跳过第一步，把一个可修的本地配置问题写成了不可逾越的红线，
并据此把整条网页通道锁在 AppleScript 上将近一个版本周期。凡是"不可证伪的解释"
（"就是被策略封了"）一旦写进文档，就没人再挑战它，所以下笔前必须先排除可验证的原因。

### 网页版 CDP 通道用法

前提：
1. **起持久 profile + 调试端口**（端口只在启动时能开）。`web_ensure.py ensure` 已把这步
   幂等封装，等价于：
   ```bash
   nohup "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
     --user-data-dir="$HOME/.chrome-cdp-profile" --remote-debugging-port=9445 \
     --no-first-run --no-default-browser-check >/dev/null 2>&1 &
   ```
2. **首次人工登录一次**：`web_ensure.py login` 打开网页版并等你**在那个窗口里自己登录**
   （工具不代填凭证）。登录态存在该 persistent profile 里，**实例重启后无需重新认证**。
   未登录判据是 URL 命中 `QUICK_UNAUTH_MARKERS`（默认 `signin,login,authorize,oauth,sso`，
   自家 IdP 域名不同就覆盖它）。
3. **起始 URL 用环境变量配置**：`QUICK_WEB_REGION` + `QUICK_WEB_ACCOUNT`（或
   `QUICK_WEB_BASE` 整体覆盖）。代码里的账户名只是占位符，跑之前先 export 成你自己的。

**playwright over CDP 三坑（必读）**：
- **禁用 `b.new_page()`** —— 报 `Browser context management is not supported`。
- 要**复用 `b.contexts[0]` 中 url 含 `quicksight` 的 page**。
- 开新标签走 CDP HTTP `PUT /json/new?<url>`。
- 现代 JS（箭头 / spread）在 `page.evaluate` 里**正常**，无需 ES5。

下表命令语义与选择器**沿用 v1.x 真机验证结果（未重新探测 UI）**，只换底层驱动为 CDP：

```bash
cd ~/.claude/skills/amazon-quick-control/scripts
uv run python web_ensure.py ensure   # 前置:幂等起 CDP 实例(未起则启动并等端口就绪)
C="uv run --with playwright python chrome_as.py"   # v2.0 起底层是 CDP
# —— 通用原语 ——
$C tabs                          # 列出 CDP 实例的 target(页面),取代 AppleScript 枚举窗口/标签
$C state quicksight              # 读 url/title/signedIn/h1
$C buttons quicksight            # 感知:扫全页可点元素(索引+文字)
$C click quicksight "库"         # 按文字点击(playwright locator,自由点击的内核)
$C fill quicksight "名称" "值"   # 按 label/placeholder 填输入框(底层=locator.fill(),不再走剪贴板+键盘)
$C eval quicksight "<js>"        # 逃生舱:page.evaluate 注入任意 JS(也可从 stdin);可用现代 JS
$C evalf quicksight <jsfile>     # 从文件读 JS 执行(便利手段;CDP 下已无 heredoc 转义问题,非必需)
# —— 网页版读命令层(零副作用;命令语义与选择器沿用 v1.x 真机验证,驱动换为 CDP) ——
$C goto spaces                   # 导航到11区任一(改location比点按钮稳):mystuff/spaces/research/agents/apps/flows/analyses/dashboards/data/personal/shared(支持中文别名)
$C wait-text "创建空间" 15       # 轮询等文字出现(SPA渲染),超时返回TIMEOUT
$C dump quicksight               # 读主内容区innerText(替代无权限的系统截图)——最可靠的"眼见为实"
$C list quicksight               # 粗读当前区列表(基于main文本,精度待每区定制)
$C view card                     # 视图切换 grid|list|table|card(自动映射各区文字/aria)
$C filter mine                   # 显示范围 recent|mine|favorites|shared|all
$C search "财务"                 # 区内搜索框(避开左栏全局搜索)——跨区命中各自搜索框
$C sort "名称"                   # 按列排序(传列名);无参=点排序下拉
$C page next                     # 分页 first|prev|next|last|<页码>
$C tab "库"                      # 区内标签切换(库/我的应用程序/流库/触发器/待批准…)
$C open "<资产名>"               # 打开列表项(contains 匹配)
$C open-menu "<资产名>"          # 打开行级/溢出菜单(只展开不点项)
$C help / user-menu / toggle-nav / open-chat / chat-search / more-menu / dismiss-banner  # 顶栏壳级只读入口
# —— 网页版写命令层(建/删资产;⚠️ 生产资产,只在用户明确要求时跑) ——
$C create-space "<名>"                    # 建空间:开对话框→填名(locator.fill)→提交(全自重试)
$C delete-space "<名>" --confirm          # 删空间:定位行→更多操作→删除→确认框填中文"删除"(i18n bug,见下)→提交(--confirm 把关)
# —— App(应用程序)写命令层:发布到 Applications 库,团队可访问(已真机验证) ——
$C create-app "<描述>"                    # apps区顶部textarea填描述(locator.fill)→点aria-label='生成'→进 /apps/<id>/edit 编辑器建组件
$C approve-prompts                        # 扫并自动点构建期弹出的授权/继续/预览框(轮询式,建App过程反复跑)
$C app-edit "<修改指令>"                  # 对编辑器里的App提对话式修改(填'要求应用程序进行更改'框+回车)
$C publish-app                            # 点'发布'→弹窗确认→读回 /apps/<id>/view/<name> 正式URL
$C share-app "<alias>"                    # 打开共享框+填alias(⚠️候选选中/定权限/点共享需人工,见盲区)
```

**网页版 11 区路由**(goto 目标)：`mystuff` 我的内容 · `spaces` 空间 · `research` 研究 · `agents` 聊天代理 · `apps` 应用程序 · `flows` 流程 · `analyses` 分析 · `dashboards` 控制面板 · `data` 数据 · `personal`/`shared` 文件夹。

**网页版写操作攻坚(必读)**：
1. **删除确认 i18n bug（仍为真，不变）**：删除空间弹窗提示"请键入 **Delete**"(英文没本地化)，但**实际校验中文"删除"**——按英文提示打永远启用不了删除按钮。删除类确认一律用中文"删除"。
2. **输入框写入**：CDP 下 playwright 原生 `locator.fill()` **实测直接写入 MUI 输入框**（"搜索空间"框已验证），这是当前唯一需要的写法。
   > **AppleScript 时代（v1.x）的历史约束，CDP 迁移后已消除**：确认框是 MUI/VegaTextField，`nativeSetter`/`_valueTracker`/合成事件链**全部无效**(按钮不启用)；当年唯一解是**剪贴板粘贴**——`pbcopy` 写入确认词 → AppleScript 提标签到前台 → `input.click()`+`focus()` 抢系统焦点 → `Cmd+A`/退格/`Cmd+V`（见 legacy `_bring_front_and_type()`，已退役）。连带的"粘贴需放宽 delay(提前台 1.2s、聚焦后 1.0s)"调参也一并作废。
3. **SPA 时序（仍为真）**：文本出现 ≠ 元素可交互(TR/按钮后挂载)。所有点击/行定位用**自重试轮询**(`_click_retry` / for 循环扫到为止)，不用固定 sleep。
> CDP 下**不再强制把标签提到前台**，可后台静默驱动。若仍希望高危确认动作肉眼可见，主动调 `page.bring_to_front()` —— 这是**策略选择**，不再是技术限制。

**发布 App 到 Applications 库(团队可访问)—— 必读结论(已真机验证)**：
1. **桌面端 chat「生成」的 App 进不了库、团队访问不到**——桌面端(quick_ctl.py `ask`)里让 Quick「做个 App」只是会话内产物,无 Create/Publish Q App 权限。**要发布到库、可共享,只能走网页版通道(现为 CDP :9445)。** 完整闭环不变:`create-app` → 反复 `approve-prompts` → 建完 `publish-app` → `share-app`。
2. **App 提交按钮是 `aria-label='生成'`(不是文字'生成')**;编辑器里改内容用 `app-edit`(输入框 placeholder 含'更改')。
3. **描述必须强约束,否则跑偏**:描述太泛时 Quick 会自作主张把 App 做成「文档浏览器/markdown 阅读器」。要复刻某 HTML 门户就明说「严格以 Space 里的 `<file>.html` 为唯一样板 1:1 复刻,不要自己设计布局/搜索/KPI/下钻」——纠偏也用 `app-edit` 发这句。
4. **构建期会多次弹授权框**(运行时集成注册等):跑 `approve-prompts` 自动点(允许/继续/预览);它是轮询式,建 App 的几分钟里反复跑几次。
5. **⚠️ App 共享框的自动补全:v1.x 是盲区,CDP 下待验证**。与 Space 共享框不同,App 共享搜索框的候选,v1.x `share-app` 用 JS setter / 剪贴板粘贴 / 真键盘 keystroke **四种注入都不出候选**——但这四种手段**全是 AppleScript 时代的**;CDP 下 playwright 原生输入(`fill` / `type` / `press_sequentially`)**尚未复测**,既不能照抄"盲区"结论,也不得宣称已解决。保守流程不变:`share-app` 只做「打开共享框+填 alias」,**选中候选、定权限(查看器/共同所有者)、点'共享'先按需人工在浏览器完成**,跑完提示用户手点,加完用 `dump`/eval 读共享对象列表核实。⚠️ **不得为验证此点真共享任何 App**。
6. **SVG 不能上传进 Space**(格式不支持,报错)。要让 App 内联 SVG:把 SVG 源码打包成 `.md`(每张一个 ```svg 代码块)上传,再让 App 读该 md 内联;或建 App 时把 SVG 源码随描述给到。

**网页版能力审计（深度调研，多 agent 并行）**：11 区共 **122 个操作**（100 读 + 22 写）全部厘清。**结论：其余操作原理上都能被 CDP 的 click/fill/eval 驱动**——写操作与行级菜单只是 dump 未展开，非不可达。关于 apps「附加文件」触发的**原生系统文件选择器**：AppleScript 下确实不可达（当年判为"任何 JS 方案都碰不到"）；**CDP 下 playwright 有 `set_input_files` / `expect_file_chooser`，理论可行但本项目尚未复测 —— 标记为待验证，不要当已解决**。读命令层（上表）的语义与选择器沿用 v1.x 跨区真机验证结果；写命令层（create-*/generate-*/favorite/item-action）在 CDP 下待逐个真机验证（会建生产资产，需用户明确确认）。

**踩坑固化（v1.x AppleScript 时代的约束，v2.0 CDP 迁移后已消除）**

保留是因为它们解释了 v1.x 的代码为何长成那样，也是"底层选型如何反噬上层写法"的实例：

| v1.x 约束 | 当年的原因 | v2.0 现状 |
|---|---|---|
| JS 绝不在 shell heredoc 里手拼 | shell/AppleScript/JS 三层转义地狱，`=>`、`...`、`<`、`\s`、中文引号任一层错位就 `syntax error` | ✅ 消除。`page.evaluate` 直传，参数走 playwright 序列化 |
| 扫描/点击 JS 一律 ES5（`function(){}`/`for`/`getElementsByTagName`） | 箭头函数与 spread 过不了 AppleScript 词法层 | ✅ 消除。现代 JS 正常 |
| 写输入框靠 `pbcopy` + 提标签到前台 + `Cmd+V` | MUI/Vega 反自动化挡掉 `nativeSetter`/`_valueTracker`/合成事件链 | ✅ 消除。`locator.fill()` 直接生效，写操作静默后台 |
| 不能用系统截图验证 | 终端无「屏幕录制」权限，`screencapture` 报 "could not create image from display" | ✅ 消除。`screenshot` 命令走 CDP 原生截图 |

> 唯一仍需注意的是 **SPA 时序**：文本出现 ≠ 元素可交互。playwright 的 locator API 自带等待，但注入式点击（`click`/`view`/`filter`）仍保留一层薄重试兜底懒加载。

## 被"剧本"调用做现场演示（分层：能力 vs 剧本）

本 skill 是**通用能力（演员）**：驱动 Quick 点/填/读/等。**具体演示的剧本**（暗号编排 → 什么 prompt → 什么数据）住在各自的演示 repo，用 `subprocess` 调本 skill 的 `quick_ctl.py`/`chrome_as.py`。换场景 → 新剧本，复用同一个 skill。

- **剧本长什么样**：一个 `demo.py`，把若干暗号（如 `prep`/`open`/`r1`/`c1`/`app1`/`flow1`）
  映射成一串 `quick_ctl.py` 调用，含半自动过弹窗、埋点、完成检测、离线备轨。
  暗号+prompt+数据是"这一场"的策略，不该焊死在通用能力 skill 里（机制 vs 策略分层）。
- **调用**：`QUICK_CTL=<本skill>/scripts/quick_ctl.py uv run --with playwright python <你的演示repo>/demo/demo.py <暗号>`

**踩坑（生成 artifact 的等待判据，剧本作者必读）**：Quick 生成看板类 artifact 有**长静默期**（跑 Python 处理数据时 UI 不吐字），`_wait_idle` 的"文字稳定"会**提前误判完成**。要靠 `quick_ctl.py wait-done`（Stop 按钮消失）+ 固定缓冲。原则：**可靠 >> 快，宁可多等几十秒，不能提前说错话**。
