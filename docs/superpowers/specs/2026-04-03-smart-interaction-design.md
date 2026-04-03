# Smart Interaction Design Spec

## 1. AI Summary (from JSONL)

**Trigger:** session 完成时 (waitingForInput) + 每次工具调用结束时更新
**Source:** 从 JSONL 提取已有的 summary（Claude Code 自己生成的 ConversationInfo.summary）
**Display:** 全部位置 — 列表副标题、灵动岛滚动文字、展开详情

## 2. 未处理任务提醒

当 session 完成但用户长时间没处理：
- 灵动岛圆点/猫变色提醒（比如脉动橙色→红色）
- 时间越长提醒越强烈（30s → 橙色，1min → 红色闪烁）
- buddy emoji 可以变"着急"的表情

## 3. Summary 快速展示

session 完成时：
- 灵动岛自动展开一小部分，显示 summary 滚动文字
- 向上滑动/点击展开该 session 详情
- 多个任务待处理时，依次轮播或堆叠显示

## 4. 快捷选择面板

当 Claude Code 提出 A/B/C 选择（AskUserQuestion）：
- 灵动岛自动展开显示问题 + 选项按钮
- 显示上下文 summary 帮助快速决策
- 点击选项直接发送到终端
- 键盘快捷键 ⌘1/⌘2/⌘3 对应选项

## 5. 空闲 session 跳转修复

- 空闲/完成的 session 也要能跳转到终端
- 只要有 PID/TTY 就保持跳转能力
- 不要因为状态变 idle 就失去终端关联

## 6. 更多交互创意

- 长按灵动岛 → 显示所有待处理 session 的 mini 卡片
- 双击灵动岛 → 跳到最需要处理的 session
- 拖拽文件到灵动岛 → 发送到当前 session
- session 完成时 buddy 的 speech bubble 弹出来
