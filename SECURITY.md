# 安全说明 / Security

本项目是一个**本机自动化工具**：它通过 Chrome DevTools Protocol 驱动本机已登录的
Amazon Quick 桌面端与网页版。它不是服务、不监听外部端口、不存储凭证。
但它确实运行在**已认证的会话之内**，所以边界必须写清楚。

## 信任边界（明确不做什么）

| 项 | 本项目的行为 |
|---|---|
| 凭证 / 密钥 | **不读、不写、不存、不传**。仓库内无任何 token/证书/私钥 |
| 身份认证 | **不自动化**。`web_ensure.py login` 只负责打开页面并等你**在那个 Chrome 窗口里亲手登录**；工具不代填账号密码、不代过 MFA。无人值守拿不到会话 |
| 登录态存放 | 落在你指定的持久 profile 目录（默认 `~/.chrome-cdp-profile`）里，由 Chrome 自己管理；本项目不解析、不复制、不导出其中的 cookie |
| 网络暴露 | CDP 只连 `127.0.0.1` 回环（有单元测试 `test_cdp_endpoint_uses_loopback` 守着） |
| 远程控制 | 无。全部操作由本机进程发起 |

### 关于独立的 CDP profile

CDP 需要 `--remote-debugging-port`，而日常主浏览器通常没开这个端口。本项目因此起一个
**独立 `--user-data-dir` 的 Chrome 实例**（`web_ensure.py ensure`），好处有两条：
调试端口不落在你的主浏览器上（主 profile 的标签、cookie、扩展都不受影响），
且这个专用目录把登录态持久化下来——只需首次人工登录一次。

这个实例的权限**不高于你本人**：它拿到的会话就是你自己在那个窗口里登录出来的会话，
既不提权、也不绕过你所在组织的任何访问控制。

## 高危操作的护栏

- `chrome_as.py delete-space` 必须显式加 `--confirm`，否则 **exit 2 拒绝执行**
  （回归测试 `test_chrome_as_delete_space_guarded` 直接在 AST 上验证这道闸还在）
- E2E 测试只做**只读 / 无副作用**操作，绝不建、删、共享任何资产
- 真机通道不可用时测试**自动 skip**，不会去碰一个"猜测中"的目标

## 使用者须遵守

- 只在**你自己有权访问**的 Amazon Quick 账号上运行
- 生成的截图 / dump 可能含**你账号里的业务数据** —— 不要提交进 git（`.gitignore` 已排除 `*.png`）
- 不要把 CDP 调试端口暴露到回环之外；不要在共享/多用户机器上跑
- 遵守所在组织关于自动化访问其系统的规定

## 报告安全问题

如果你在本项目中发现潜在的安全问题，**请不要开 public issue**，而是通过 AWS 漏洞
报告渠道提交：

<https://aws.amazon.com/security/vulnerability-reporting/>

详见 [CONTRIBUTING.md](./CONTRIBUTING.md) 的 "Security issue notifications" 一节。
