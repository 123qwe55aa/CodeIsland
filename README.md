<div align="center">

<img src="ClaudeIsland/Assets.xcassets/AppIcon.appiconset/icon_128x128.png" width="128" height="128" alt="CodeIsland" />

# CodeIsland

**Your AI agents live in the notch.**

This is a passion project built purely out of personal interest. It is **free and open-source** with no commercial intentions whatsoever. I welcome everyone to try it out, report bugs, share it with your colleagues, and contribute code. Let's build something great together!

这是一个纯粹出于个人兴趣开发的项目，**完全免费开源**，没有任何商业目的。欢迎大家试用、提 Bug、推荐给身边的同事使用，也欢迎贡献代码。一起把它做得更好！

English | [中文](README.zh-CN.md)

[![GitHub stars](https://img.shields.io/github/stars/xmqywx/CodeIsland?style=social)](https://github.com/xmqywx/CodeIsland/stargazers)

[![Website](https://img.shields.io/badge/website-xmqywx.github.io%2FCodeIsland-7c3aed?style=flat-square)](https://xmqywx.github.io/CodeIsland/)
[![Release](https://img.shields.io/github/v/release/xmqywx/CodeIsland?style=flat-square&color=4ADE80)](https://github.com/xmqywx/CodeIsland/releases)
[![macOS](https://img.shields.io/badge/macOS-14%2B-black?style=flat-square&logo=apple)](https://github.com/xmqywx/CodeIsland/releases)
[![License](https://img.shields.io/badge/license-CC%20BY--NC%204.0-green?style=flat-square)](LICENSE.md)

**If you find this useful, please give it a star! It keeps us motivated to improve.**

**如果觉得好用，请点个 Star 支持一下！这是我们持续更新的最大动力。**

</div>

---

A native macOS app that turns your MacBook's notch into a real-time control surface for AI coding agents. Monitor sessions, approve permissions, jump to terminals, and hang out with your Claude Code buddy — all without leaving your flow.

> ### 📱 New: pairs with [Code Light](https://github.com/xmqywx/CodeLight) — your iPhone companion
> CodeIsland now includes a built-in **sync module** that pairs with the Code Light iPhone app. From your phone you can:
> - **See** every Claude Code session live, with the iPhone Dynamic Island showing the current phase
> - **Send** any text message — including all `/slash` commands like `/model`, `/cost`, `/usage`, `/clear`
> - **Spawn** brand-new cmux workspaces remotely with one tap (Mac-defined launch presets)
> - **Send** images via camera or photo library (auto-pasted into the cmux pane)
> - **Pair** multiple iPhones to the same Mac, or one iPhone to many Macs — your phone tracks them all
>
> Pairing is **one permanent 6-character code per Mac** (or scan a QR). No accounts, no QR expiry, no re-pair after reboot. See the [Code Light Sync](#code-light-sync-iphone-companion) section below.

## Features

### Dynamic Island Notch

The collapsed notch shows everything at a glance:

- **Animated buddy** — your Claude Code `/buddy` pet rendered as 16x16 pixel art with wave/dissolve/reassemble animation
- **Status dot** — color indicates state:
  - 🟦 Cyan = working
  - 🟧 Amber = needs approval
  - 🟩 Green = done / waiting for input
  - 🟣 Purple = thinking
  - 🔴 Red = error, or session unattended >60s
  - 🟠 Orange = session unattended >30s
- **Project name + status** — carousel rotates task title, tool action, project name
- **Session count** — `×3` badge showing active sessions
- **Pixel Cat Mode** — toggle to show the hand-drawn pixel cat instead of your buddy

### Session List

Expand the notch to see all your Claude Code sessions:

- **Pixel cat face** per session with state-specific expressions (blink, eye-dart, heart eyes on done, X eyes on error)
- **Auto-detected terminal** — shows Ghostty, Warp, iTerm2, cmux, Terminal, VS Code, Cursor, etc.
- **Task title** — displays your first message or Claude's summary, not just the folder name
- **Duration badge** — how long each session has been running
- **Golden jump button** — click to jump to the exact terminal tab (via cmux/Ghostty AppleScript)
- **Glow dots** with gradient dividers — minimal, clean design
- **Hover effects** — row highlight + golden terminal icon

### Claude Code Buddy Integration

Full integration with Claude Code's `/buddy` companion system:

- **Accurate stats** — species, rarity, eye style, hat, shiny status, and all 5 stats (DEBUGGING, PATIENCE, CHAOS, WISDOM, SNARK) computed using the exact same Bun.hash + Mulberry32 algorithm as Claude Code
- **Dynamic salt detection** — reads the actual salt from your Claude Code binary, supports patched installs (any-buddy compatible)
- **ASCII art sprite** — all 18 buddy species rendered as animated ASCII art with idle animation sequence (blink, fidget), matching Claude Code's terminal display
- **Buddy card** — left-right layout: ASCII sprite + name on the left, ASCII stat bars `[████████░░]` + personality on the right
- **Rarity stars** — ★ Common to ★★★★★ Legendary with color coding
- **18 species supported** — duck, goose, blob, cat, dragon, octopus, owl, penguin, turtle, snail, ghost, axolotl, capybara, cactus, robot, rabbit, mushroom, chonk

### Permission Approval

Approve or deny Claude Code's permission requests right from the notch:

- **Code diff preview** — see exactly what will change before allowing (green/red line highlighting)
- **File path display** — warning icon + tool name + file being modified
- **Deny/Allow buttons** — with keyboard hint labels
- **Hook-based protocol** — responses sent via Unix socket, no terminal switching needed

### Pixel Cat Companion

A hand-drawn pixel cat with 6 animated states:

| State | Expression |
|-------|-----------|
| Idle | Black eyes, gentle blink every 90 frames |
| Working | Eyes dart left/center/right (reading code) |
| Needs You | Eyes + right ear twitches |
| Thinking | Closed eyes, breathing nose |
| Error | Red X eyes |
| Done | Green heart eyes + green tint overlay |

### 8-bit Sound System

Chiptune alerts for every event:

| Event | Default |
|-------|---------|
| Session start | ON |
| Processing begins | OFF |
| Needs approval | ON |
| Approval granted | ON |
| Approval denied | ON |
| Session complete | ON |
| Error | ON |
| Context compacting | OFF |

Each sound can be toggled individually. Global mute and volume control available.

### Project Grouping

Toggle between flat list and project-grouped view:

- Sessions automatically grouped by working directory
- Collapsible project headers with active count
- Chevron icons for expand/collapse

### Code Light Sync (iPhone companion)

CodeIsland's **sync module** is the bridge that makes the [Code Light](https://github.com/xmqywx/CodeLight) iPhone companion possible. Open `Pair iPhone` from the notch menu to begin.

#### Pairing

Each Mac is identified on the server by a **permanent 6-character `shortCode`** (lazy-allocated on first connect, never rotates). The pairing window shows both:
- A QR code (scan with the iPhone's camera)
- The 6-character code in large monospace (type it in if you don't want to scan)

Both paths converge on the same `POST /v1/pairing/code/redeem` endpoint. The same code can pair as many iPhones as you want — it never expires, doesn't change when you restart CodeIsland, and survives upgrades.

#### Phone → terminal routing

Phone messages have to land in the **exact** Claude Code terminal that the user picked. CodeIsland's `TerminalWriter` does this with zero guessing:

1. `ps -Ax` to find the `claude --session-id <UUID>` process matching the message's session tag
2. `ps -E -p <pid>` to read `CMUX_WORKSPACE_ID` and `CMUX_SURFACE_ID` env vars
3. `cmux send --workspace <ws> --surface <surf> -- <text>`

If the live Claude PID was rotated by a `claude --resume`, a `cwd`-scoped fallback picks the highest-PID cmux-hosted Claude in the same directory. If nothing matches, the message is cleanly dropped — no orphan windows ever get hijacked.

For non-cmux terminals (iTerm2, Ghostty, Terminal.app), `TerminalWriter` falls back to AppleScript with the matching workspace title.

#### Slash commands with captured output

`/model`, `/cost`, `/usage`, `/clear`, `/compact` and friends don't write to Claude's JSONL — their output never reaches the file watcher. CodeIsland intercepts these specially:

1. Snapshot the cmux pane via `cmux capture-pane`
2. Inject the slash command via `cmux send`
3. Poll the pane every 200 ms until output settles
4. Diff the snapshots and ship the new lines back to the server as a synthetic `terminal_output` message

The phone sees the response inline in chat as if `/cost` were a normal Claude reply.

#### Remote session launch

The phone can ask CodeIsland to spawn a brand-new cmux workspace running a configured command. CodeIsland defines **launch presets** locally — name + command + icon — and uploads them to the server (using Mac-generated UUIDs as primary keys, so the round-trip works without ID translation).

When the phone calls `POST /v1/sessions/launch {macDeviceId, presetId, projectPath}`, the server emits a `session-launch` socket event scoped to this Mac. CodeIsland's `LaunchService` looks up the preset locally and runs:

```bash
cmux new-workspace --cwd <projectPath> --command "<preset.command>"
```

Default presets seeded on first launch:
- `Claude (skip perms)` → `claude --dangerously-skip-permissions`
- `Claude + Chrome` → `claude --dangerously-skip-permissions --chrome`

Add, edit, or remove your own presets from the **Launch Presets** menu in the notch.

#### Image attachments

Phone-attached images come down as opaque blob IDs (uploaded by the phone via `POST /v1/blobs`). CodeIsland downloads each blob, focuses the target cmux pane, writes the image to `NSPasteboard` in NSImage / `public.jpeg` / `.tiff` formats, then `System Events keystroke "v" using {command down}` (with a `CGEvent` fallback). Claude sees `[Image #N]` and the trailing text as a single message.

This requires **Accessibility permission** — and because permissions are tracked by the app's signed path, CodeIsland auto-installs a copy of itself to `/Applications/Code Island.app` so the grant survives Debug rebuilds.

#### Project path sync

CodeIsland uploads the unique `cwd` of every active session every 5 minutes. The phone fetches them from `GET /v1/devices/<macDeviceId>/projects` to populate the "Recent Projects" picker in the launch sheet. No manual configuration.

#### Echo loop dedup

Phone sends → server → CodeIsland pastes → Claude writes to JSONL → file watcher sees a "new user message" → would normally re-upload it → phone gets a duplicate. Fixed with a 60 s TTL `(claudeUuid, text)` ring on the Mac: MessageRelay consumes a matching entry before uploading and skips. No server changes, no localId negotiation.

#### Multi-iPhone, multi-server

A Mac can be paired with multiple iPhones simultaneously — they all share the same `shortCode`. From the iPhone side, one phone can be paired with multiple Macs across different backend servers; the phone's `LinkedMacs` list stores `serverUrl` per Mac and switches connections automatically when you tap into a different one.

## Settings

| Setting | Description |
|---------|-------------|
| **Screen** | Choose which display shows the notch (Auto, Built-in, or specific monitor) |
| **Notification Sound** | Select alert sound style |
| **Group by Project** | Toggle between flat list and project-grouped sessions |
| **Pixel Cat Mode** | Switch notch icon between pixel cat and buddy emoji animation |
| **Language** | Auto (system) / English / 中文 |
| **Launch at Login** | Start CodeIsland automatically when you log in |
| **Hooks** | Install/uninstall Claude Code hooks in `~/.claude/settings.json` |
| **Accessibility** | Grant accessibility permission for terminal window focusing + image-paste keystrokes |
| **Pair iPhone** | Show the QR + 6-character pairing code for the [Code Light](https://github.com/xmqywx/CodeLight) iPhone app |
| **Launch Presets** | Manage the named cmux launch commands the iPhone can trigger remotely |

## Terminal Support

CodeIsland auto-detects your terminal from the process tree:

| Terminal | Detection | Jump-to-Tab |
|----------|-----------|-------------|
| cmux | Auto | AppleScript (by working directory) |
| Ghostty | Auto | AppleScript (by working directory) |
| Warp | Auto | Activate only (no tab API) |
| iTerm2 | Auto | AppleScript |
| Terminal.app | Auto | Activate |
| Alacritty | Auto | Activate |
| Kitty | Auto | Activate |
| WezTerm | Auto | Activate |
| VS Code | Auto | Activate |
| Cursor | Auto | Activate |
| Zed | Auto | Activate |

> **Recommended: [cmux](https://cmux.io)** — A modern terminal multiplexer built on Ghostty. CodeIsland works best with cmux: precise workspace-level jumping, AskUserQuestion quick reply via `cmux send`, and smart popup suppression per workspace tab. If you manage multiple Claude Code sessions, cmux + CodeIsland is the ideal combo.
>
> **推荐搭配 [cmux](https://cmux.io)** — 基于 Ghostty 的现代终端复用器。CodeIsland 与 cmux 配合最佳：精确到 workspace 级别的跳转、AskUserQuestion 快捷回复、智能弹出抑制。多 Claude Code 会话管理的理想组合。

## Install

**Download** the latest `.dmg` from [Releases](https://github.com/xmqywx/CodeIsland/releases), open it, drag to Applications.

> **macOS Gatekeeper warning:** If you see "Code Island is damaged and can't be opened", run this in Terminal:
> ```bash
> sudo xattr -rd com.apple.quarantine /Applications/Code\ Island.app
> ```

### Build from Source

```bash
git clone https://github.com/xmqywx/CodeIsland.git
cd CodeIsland
xcodebuild -project ClaudeIsland.xcodeproj -scheme ClaudeIsland \
  -configuration Release CODE_SIGN_IDENTITY="-" \
  CODE_SIGNING_REQUIRED=NO CODE_SIGNING_ALLOWED=NO \
  DEVELOPMENT_TEAM="" build
```

### Requirements

- macOS 14+ (Sonoma)
- MacBook with notch (floating mode on external displays)
- [Bun](https://bun.sh) for accurate buddy stats (optional, falls back to basic info)

## How It Works

1. **Zero config** — on first launch, CodeIsland installs hooks into `~/.claude/settings.json`
2. **Hook events** — a Python script (`codeisland-state.py`) sends session state to the app via Unix socket (`/tmp/codeisland.sock`)
3. **Permission approval** — for `PermissionRequest` events, the socket stays open until you click Allow/Deny, then sends the decision back to Claude Code
4. **Buddy data** — reads `~/.claude.json` for name/personality, runs `buddy-bones.js` with Bun for accurate species/rarity/stats
5. **Terminal jump** — uses AppleScript to find and focus the correct terminal tab by matching working directory

## i18n

CodeIsland supports English and Chinese with automatic system locale detection. Override in Settings > Language.

## Contributing

Contributions are welcome! Here's how:

1. **Report bugs** — [Open an issue](https://github.com/xmqywx/CodeIsland/issues) with steps to reproduce
2. **Submit a PR** — Fork the repo, create a branch, make your changes, and open a Pull Request
3. **Suggest features** — Open an issue tagged `enhancement`

I will personally review and merge all PRs. Please keep changes focused and include a clear description.

## 参与贡献

欢迎参与！方式如下：

1. **提交 Bug** — 在 [Issues](https://github.com/xmqywx/CodeIsland/issues) 中描述问题和复现步骤
2. **提交 PR** — Fork 本仓库，新建分支，修改后提交 Pull Request
3. **建议功能** — 在 Issues 中提出，标记为 `enhancement`

我会亲自 Review 并合并所有 PR。请保持改动聚焦，附上清晰的说明。

## Contact / 联系方式

Have questions or want to chat? Reach out!

有问题或想交流？欢迎联系！

- **Email / 邮箱**: xmqywx@gmail.com

<img src="docs/wechat-qr-kris.jpg" width="180" alt="WeChat - Kris" />  <img src="docs/wechat-qr.jpg" width="180" alt="WeChat - Carey" />

## Credits

Forked from [Claude Island](https://github.com/farouqaldori/claude-island) by farouqaldori. Rebuilt with pixel cat animations, buddy integration, cmux support, i18n, and minimal glow-dot design.

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=xmqywx/CodeIsland&type=Date)](https://star-history.com/#xmqywx/CodeIsland&Date)

## License

CC BY-NC 4.0 — free for personal use, no commercial use.
