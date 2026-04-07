<div align="center">

<img src="ClaudeIsland/Assets.xcassets/AppIcon.appiconset/icon_128x128.png" width="128" height="128" alt="CodeIsland" />

# CodeIsland

**你的 AI 代理住在刘海里。**

这是一个纯粹出于个人兴趣开发的项目，**完全免费开源**，没有任何商业目的。欢迎大家试用、提 Bug、推荐给身边的同事使用，也欢迎贡献代码。一起把它做得更好！

**如果觉得好用，请点个 Star 支持一下！这是我们持续更新的最大动力。**

[![GitHub stars](https://img.shields.io/github/stars/xmqywx/CodeIsland?style=social)](https://github.com/xmqywx/CodeIsland/stargazers)

[![Website](https://img.shields.io/badge/website-xmqywx.github.io%2FCodeIsland-7c3aed?style=flat-square)](https://xmqywx.github.io/CodeIsland/)
[![Release](https://img.shields.io/github/v/release/xmqywx/CodeIsland?style=flat-square&color=4ADE80)](https://github.com/xmqywx/CodeIsland/releases)
[![macOS](https://img.shields.io/badge/macOS-14%2B-black?style=flat-square&logo=apple)](https://github.com/xmqywx/CodeIsland/releases)
[![License](https://img.shields.io/badge/license-CC%20BY--NC%204.0-green?style=flat-square)](LICENSE.md)

[English](README.md) | 中文

</div>

---

一款原生 macOS 应用，将你的 MacBook 刘海变成 AI 编码代理的实时控制面板。监控会话、审批权限、跳转终端、和你的 Claude Code 宠物互动 — 无需离开当前工作流。

> ### 📱 全新：与 [Code Light](https://github.com/xmqywx/CodeLight) 配对 — 你的 iPhone 伴侣
> CodeIsland 内置了**同步模块**，可以与 Code Light iPhone 应用配对。在手机上你可以：
> - **看到**所有 Claude Code 会话实时更新，灵动岛显示当前阶段
> - **发送**任意文本消息 — 包括 `/model`、`/cost`、`/usage`、`/clear` 等所有 `/slash` 命令
> - **远程启动**新的 cmux workspace（基于 Mac 端定义的启动预设）
> - **发送图片** — 拍照或从相册选择，自动粘贴到 cmux 窗格
> - **多端配对** — 同一台 Mac 可以配对多部 iPhone，同一部 iPhone 也可以配对多台 Mac
>
> 配对方式：**每台 Mac 一个永久 6 位字符配对码**（也支持扫码）。无账号、不过期、重启不变。详见下方 [Code Light Sync](#code-light-sync-iphone-伴侣) 章节。

## 功能特性

### 灵动岛刘海

收起状态一眼掌握全局：

- **动画宠物** — 你的 Claude Code `/buddy` 宠物渲染为 16x16 像素画，带波浪/消散/重组动画
- **状态指示点** — 颜色表示状态：
  - 🟦 青色 = 工作中
  - 🟧 琥珀色 = 等待审批
  - 🟩 绿色 = 完成 / 等待输入
  - 🟣 紫色 = 思考中
  - 🔴 红色 = 出错，或会话超过 60 秒无人处理
  - 🟠 橙色 = 会话超过 30 秒无人处理
- **项目名 + 状态** — 轮播显示任务标题、工具动态、项目名
- **会话数量** — `×3` 角标显示活跃会话数
- **像素猫模式** — 可切换显示手绘像素猫或宠物 emoji 动画

### 会话列表

展开刘海查看所有 Claude Code 会话：

- **活跃会话凸显** — 更大图标、加粗标题、状态色背景、工具动态行
- **自动识别终端** — 彩色标签显示终端类型（cmux 蓝、Ghostty 紫、iTerm 绿、Warp 琥珀等）
- **任务标题** — 显示最新用户消息或 Claude 摘要
- **运行时长** — 活跃会话用状态色显示
- **终端跳转** — 绿色按钮一键跳到对应终端
- **删除会话** — 空闲/结束的会话可一键删除
- **Subagent 追踪** — ⚡ 标签 + 可折叠的子 Agent 详情列表
- **动态面板高度** — ≤4 个会话自适应，>4 个可展开/收起

### Claude 用量监控

实时显示 Claude 使用量：

- **5h/7d 百分比** — 直接调用 Anthropic OAuth API 获取
- **进度条 + 重置时间** — 绿色 <70%，橙色 70-90%，红色 >90%
- **自动刷新** — 每 5 分钟刷新，支持手动刷新
- **零配置** — 从 macOS 钥匙串读取 OAuth Token

### 智能弹出抑制

当 Claude 会话完成时，智能判断是否弹出：

- **cmux** — 精确到 workspace 级别，正在看的 tab 不弹出
- **iTerm2** — 检测当前 session 名称
- **Ghostty** — 检测前台窗口标题
- **Terminal.app** — 检测 tab 标题
- **不抢焦点** — hover/通知弹出不会打断你在其他应用的打字

### AskUserQuestion 快捷回复

Claude 提问时，选项按钮直接显示在会话行：

- **cmux** — 点击直接发送答案（`cmux send`）
- **iTerm2** — AppleScript `write text`
- **Terminal.app** — AppleScript `do script`
- 其他终端跳转手动选择

### Claude Code 宠物集成

与 Claude Code 的 `/buddy` 伙伴系统完整集成：

- **精确属性** — 物种、稀有度、眼型、帽子、闪光状态和全部 5 项属性
- **动态盐值检测** — 支持修改过的安装（兼容 any-buddy）
- **ASCII 精灵动画** — 全部 18 种宠物物种
- **宠物卡片** — ASCII 精灵 + 属性条 + 性格描述
- **稀有度星级** — ★ 普通 到 ★★★★★ 传说

### 权限审批

直接在刘海中审批 Claude Code 的权限请求：

- **代码差异预览** — 绿色/红色行高亮
- **拒绝/允许按钮** — 带键盘快捷键提示
- **基于 Hook 协议** — 通过 Unix socket 响应

### 像素猫伙伴

手绘像素猫，6 种动画状态：

| 状态 | 表情 |
|------|------|
| 空闲 | 黑色眼睛，每 90 帧温柔眨眼 |
| 工作中 | 眼球左/中/右移动（阅读代码） |
| 需要你 | 眼睛 + 右耳抖动 |
| 思考中 | 闭眼，鼻子呼吸 |
| 出错 | 红色 X 眼 |
| 完成 | 绿色爱心眼 + 绿色调叠加 |

### 8-bit 音效系统

每个事件的芯片音乐提醒，每个声音可单独开关。

### Code Light Sync (iPhone 伴侣)

CodeIsland 的**同步模块**是 [Code Light](https://github.com/xmqywx/CodeLight) iPhone 伴侣应用得以工作的桥梁。从刘海菜单打开 `Pair iPhone` 即可开始。

#### 配对方式

每台 Mac 在 server 端有一个**永久 6 位 `shortCode`**（首次连接时懒分配，永不轮转）。配对窗口同时显示：
- 二维码（用 iPhone 相机扫描）
- 6 位大字号字符码（不想扫码就直接输入）

两条路径走的是同一个 `POST /v1/pairing/code/redeem` 接口。同一个码可以配对任意多部 iPhone —— 永不过期、CodeIsland 重启也不变、升级后依然有效。

#### 手机 → 终端 路由

手机发来的消息必须**精准**落到用户选中的那个 Claude 终端。CodeIsland 的 `TerminalWriter` 不做任何猜测：

1. `ps -Ax` 找到匹配 session 标签的 `claude --session-id <UUID>` 进程
2. `ps -E -p <pid>` 读取 `CMUX_WORKSPACE_ID` 和 `CMUX_SURFACE_ID` 环境变量
3. `cmux send --workspace <ws> --surface <surf> -- <text>`

如果 Claude 进程被 `claude --resume` 重启过，PID 已经轮转，会以 `cwd` 为范围 fallback —— 在同一目录下挑 PID 最高的 cmux 中托管 Claude 进程。如果都没匹配到，消息会被干净地丢掉，绝不会误发到旁边的窗口。

非 cmux 终端（iTerm2、Ghostty、Terminal.app）走 AppleScript fallback。

#### 斜杠命令带回显

`/model`、`/cost`、`/usage`、`/clear`、`/compact` 这类命令**不会**写入 Claude 的 JSONL —— 输出根本不会被文件监听器看到。CodeIsland 特殊处理：

1. 用 `cmux capture-pane` 给当前 pane 拍快照
2. 用 `cmux send` 注入斜杠命令
3. 每 200ms 轮询 pane 直到输出稳定
4. diff 前后快照，把新增的行作为合成的 `terminal_output` 消息发回 server

手机端在聊天里看到回复，就像 `/cost` 是普通的 Claude 回答一样。

#### 远程新建会话

手机可以让 CodeIsland 直接 spawn 一个新的 cmux workspace，跑指定命令。CodeIsland 在本地定义**启动预设** —— 名称 + 命令 + 图标 —— 并上传到 server（使用 Mac 生成的 UUID 作为主键，让 round-trip 不需要做 ID 转换）。

手机调 `POST /v1/sessions/launch {macDeviceId, presetId, projectPath}` 时，server 给这台 Mac 的 deviceId 推一个 `session-launch` socket 事件。CodeIsland 的 `LaunchService` 在本地查到预设后跑：

```bash
cmux new-workspace --cwd <projectPath> --command "<preset.command>"
```

首次启动会自动 seed 两个默认预设：
- `Claude (skip perms)` → `claude --dangerously-skip-permissions`
- `Claude + Chrome` → `claude --dangerously-skip-permissions --chrome`

可以从刘海菜单的 **Launch Presets** 项里增删改自己的预设。

#### 图片附件

手机发来的图片是不透明的 blob ID（手机通过 `POST /v1/blobs` 上传）。CodeIsland 下载每个 blob → 聚焦目标 cmux pane → 把图片以 NSImage / `public.jpeg` / `.tiff` 三种格式同时写入 `NSPasteboard` → `System Events keystroke "v" using {command down}`（CGEvent fallback）。Claude 看到 `[Image #N]` 和后续文本作为同一条消息。

这需要**辅助功能权限** —— 而权限是按 app 签名路径记录的，所以 CodeIsland 会自安装一份到 `/Applications/Code Island.app`，让权限在 Debug rebuild 后依然有效。

#### 项目路径同步

CodeIsland 每 5 分钟把所有活跃 session 的 unique `cwd` 上传一次。手机从 `GET /v1/devices/<macDeviceId>/projects` 拉取，填充启动 sheet 里的"最近项目"选择器。无需手动配置。

#### Echo 去重

手机发 → server → CodeIsland 粘贴 → Claude 写 JSONL → 文件监听器看到"新用户消息" → 默认会重新上传 → 手机收到自己刚发的消息的副本。解法：Mac 端保留一个 60 秒 TTL 的 `(claudeUuid, text)` 环，MessageRelay 上传前消费一次匹配项就跳过。不改 server，不做 localId 协商。

#### 多 iPhone、多 server

一台 Mac 可以同时配对多部 iPhone —— 它们共用同一个 `shortCode`。从 iPhone 端看，一部手机也可以配对**不同 server 上**的多台 Mac；手机的 `LinkedMacs` 列表会按 Mac 存 `serverUrl`，点击不同 Mac 时自动切换 socket 连接。

## 终端支持

| 终端 | 检测 | 跳转 | 快捷回复 | 智能抑制 |
|------|------|------|---------|---------|
| cmux | 自动 | workspace 精确跳转 | ✅ | workspace 级别 |
| iTerm2 | 自动 | AppleScript | ✅ | session 级别 |
| Ghostty | 自动 | AppleScript | - | 窗口级别 |
| Terminal.app | 自动 | 激活 | ✅ | tab 级别 |
| Warp | 自动 | 激活 | - | - |
| Kitty | 自动 | CLI | - | - |
| WezTerm | 自动 | CLI | - | - |
| VS Code | 自动 | 激活 | - | - |
| Cursor | 自动 | 激活 | - | - |
| Zed | 自动 | 激活 | - | - |

## 安装

从 [Releases](https://github.com/xmqywx/CodeIsland/releases) 下载最新 `.zip`，解压后拖到应用程序文件夹。

> **macOS 门禁提示：** 如果看到"Code Island 已损坏，无法打开"，在终端中运行：
> ```bash
> sudo xattr -rd com.apple.quarantine /Applications/Code\ Island.app
> ```

### 从源码构建

```bash
git clone https://github.com/xmqywx/CodeIsland.git
cd CodeIsland
xcodebuild -project ClaudeIsland.xcodeproj -scheme ClaudeIsland \
  -configuration Release CODE_SIGN_IDENTITY="-" \
  CODE_SIGNING_REQUIRED=NO CODE_SIGNING_ALLOWED=NO \
  DEVELOPMENT_TEAM="" build
```

### 系统要求

- macOS 14+（Sonoma）
- 带刘海的 MacBook（外接显示器使用浮动模式）

## 参与贡献

欢迎参与！方式如下：

1. **提交 Bug** — 在 [Issues](https://github.com/xmqywx/CodeIsland/issues) 中描述问题和复现步骤
2. **提交 PR** — Fork 本仓库，新建分支，修改后提交 Pull Request
3. **建议功能** — 在 Issues 中提出，标记为 `enhancement`

我会亲自 Review 并合并所有 PR。请保持改动聚焦，附上清晰的说明。

## 联系方式

- **邮箱**: xmqywx@gmail.com

<img src="docs/wechat-qr-kris.jpg" width="180" alt="微信 - Kris" />  <img src="docs/wechat-qr.jpg" width="180" alt="微信 - Carey" />

## 致谢

基于 [Claude Island](https://github.com/farouqaldori/claude-island)（作者 farouqaldori）改造。

## 许可证

CC BY-NC 4.0 — 个人免费使用，禁止商业用途。
