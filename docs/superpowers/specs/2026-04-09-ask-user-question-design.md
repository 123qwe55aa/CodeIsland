# AskUserQuestion Interactive Support in Code Island

**Date:** 2026-04-09
**Status:** Draft
**Branch:** fix/multi-choice

## 1. Problem

Claude Code's `AskUserQuestion` tool presents interactive multi-choice questions in the CLI. Code Island can observe these tool calls (via `PreToolUse`/`PostToolUse` hooks) and display completed results, but cannot show the questions in real-time or let users answer from the notch panel.

## 2. Goal

Enable users to see and answer `AskUserQuestion` prompts directly in the Code Island notch panel, with full support for:
- Selecting from predefined options (single-select and multi-select)
- Entering custom text ("Other")
- Jumping to the terminal to answer in the CLI instead
- Graceful handling when the user answers in the CLI directly

## 3. Approach: Hybrid Hook Socket + Tmux Send-Keys

Reuse the bidirectional socket mechanism from `PermissionRequest`. When `AskUserQuestion` is detected in `PreToolUse`, the Python hook script blocks and waits for Code Island's response through the socket. If Claude Code does not honor `hookSpecificOutput` for `PreToolUse`, fall back to tmux send-keys.

## 4. Data Flow

```
Claude Code calls AskUserQuestion
    ↓
PreToolUse hook fires (tool_name = "AskUserQuestion")
    ↓
codeisland-state.py:
  → status = "waiting_for_question"
  → send_event() blocks waiting for socket response
    ↓
HookSocketServer:
  → Parses toolInput.questions/options
  → Creates PendingQuestion (keeps socket open)
    ↓
SessionStore:
  → Phase → .waitingForQuestion(QuestionContext)
    ↓
UI: Notch expands, shows AskUserQuestionView
    ↓
User responds (one of four paths, see §5)
```

## 5. User Paths

| Path | Trigger | Code Island Behavior |
|------|---------|---------------------|
| A. Select option in notch | User clicks chip | Socket responds `{"decision":"answered","answers":{...}}` |
| B. Enter custom text | User types in Other field | Same as A, with custom text as answer value |
| C. Click "Jump to Terminal" | User clicks button | Socket responds `{"decision":"skip"}`, closes question UI, calls `TerminalJumper.jump(to:)` |
| D. Answer directly in CLI | User switches to terminal | PostToolUse arrives → auto-cleanup pending question, close UI |

## 6. Edge Cases

| Case | Handling |
|------|---------|
| **Timeout** (300s) | Socket disconnects → Python script exits → CLI takes over → Code Island cleans up on next PostToolUse or status change |
| **Notch closed** | Question stays pending. Reopening notch shows the question again. Cleared on PostToolUse or timeout. |
| **User interrupts** (Ctrl+C) | `interruptDetected` event → clean up PendingQuestion, close socket |
| **Multiple sessions** | Each session has independent `toolUseId` and `PendingQuestion`. Instances list shows question icon per session. |
| **App restart** | Socket lost → Python script times out → CLI fallback. No data loss. |

## 7. New State: `.waitingForQuestion`

### SessionPhase

New enum case:
```swift
case waitingForQuestion(QuestionContext)
```

### QuestionContext

```swift
struct QuestionContext: Sendable {
    let toolUseId: String
    let questions: [QuestionItem]  // Reuses existing struct from ToolResultData.swift
    let receivedAt: Date
}
```

### State Transitions

- `.processing` → `.waitingForQuestion` (PreToolUse with AskUserQuestion)
- `.waitingForQuestion` → `.processing` (answered, skipped, or PostToolUse received)
- `.waitingForQuestion` → `.idle` (interrupted)
- `.waitingForQuestion` → `.ended` (session ended)
- `.waitingForQuestion` → `.waitingForQuestion` (multiple questions from different tool calls — unlikely but handled)

### Helper Properties

- `needsAttention` → `true`
- `isActive` → `false`
- `isWaitingForQuestion` → type guard
- `questionContext` → extract context

## 8. Hook Script Changes (`codeisland-state.py`)

### PreToolUse Branch

When `tool_name == "AskUserQuestion"`:
- Set `status = "waiting_for_question"`
- Include `tool_use_id` and `tool_input` in event
- Call `send_event()` which blocks (same as `waiting_for_approval`)
- On response:
  - `decision == "answered"` → output `hookSpecificOutput` with answers
  - `decision == "skip"` or no response → exit without output (CLI handles)

### send_event() Change

Extend the blocking condition:
```python
if state.get("status") in ("waiting_for_approval", "waiting_for_question"):
    response = sock.recv(4096)
```

## 9. Socket Protocol

### Code Island → Python Script

User answered:
```json
{
  "decision": "answered",
  "answers": {
    "Which library should we use?": "axios"
  }
}
```

User skipped (jump to terminal or gave up):
```json
{
  "decision": "skip"
}
```

### Python Script → Claude Code (hookSpecificOutput)

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "decision": {"behavior": "allow"},
    "answers": {"Which library should we use?": "axios"}
  }
}
```

## 10. Swift Changes

### HookSocketServer.swift

- New struct `PendingQuestion` (mirrors `PendingPermission`):
  ```swift
  struct PendingQuestion {
      let toolUseId: String
      let questions: [QuestionItem]
      let clientSocket: Int32
      let receivedAt: Date
  }
  ```
- New dict `pendingQuestions: [String: PendingQuestion]`
- New methods: `respondToQuestion(toolUseId:answers:)`, `skipQuestion(toolUseId:)`
- Detect `status == "waiting_for_question"` → parse `toolInput.questions`, create `PendingQuestion`, keep socket open

### SessionEvent.swift

New events:
```swift
case questionAnswered(sessionId: String, toolUseId: String, answers: [String: String])
case questionSkipped(sessionId: String, toolUseId: String)
```

### SessionStore.swift

- `processHookEvent()`: handle `waiting_for_question` → create `.waitingForQuestion(QuestionContext)`
- `processQuestionAnswered()`: update phase → `.processing`, clean up
- `processQuestionSkipped()`: same cleanup
- PostToolUse for `AskUserQuestion`: clean up any lingering `PendingQuestion`

### ClaudeSessionMonitor.swift

New methods:
```swift
func answerQuestion(sessionId: String, answers: [String: String])
func skipQuestion(sessionId: String)
```
Bridge between UI actions and HookSocketServer + SessionStore.

### SessionPhase.swift

- Add `.waitingForQuestion(QuestionContext)` case
- Update `canTransition(to:)` rules
- Update `needsAttention`, `isActive`, etc.

### SessionPhaseHelpers.swift

Display text and icon for `.waitingForQuestion`.

### StatusIcons.swift

Question mark icon for `.waitingForQuestion` state.

## 11. UI Components

### New Files

#### `AskUserQuestionView.swift`

Main interactive view displayed when session enters `.waitingForQuestion`:
- Header: session name + "Jump to Terminal" button
- For each question:
  - Question text
  - Chip flow layout with options (horizontal, auto-wrapping)
  - Selected chip highlighted with accent color
  - Description text below chips (shows selected option's description)
  - "Other" chip expands inline TextField
- Submit button at bottom
- Single-select: one chip active at a time
- Multi-select (`multiSelect: true`): chips toggle independently

#### `ChipFlowLayout.swift`

Custom SwiftUI `Layout` for horizontal chip arrangement with automatic line wrapping. Each chip is a rounded pill with label text.

#### `QuestionResponder.swift`

Handles answer delivery with fallback:
1. Try hook socket response (`HookSocketServer.respondToQuestion()`)
2. If socket unavailable or Claude Code ignores hook output → fall back to tmux send-keys via `ToolApprovalHandler`-style mechanism (send option number + Enter)

### Modified Files

#### `NotchView.swift`

- Detect `.waitingForQuestion` → auto-expand notch, show `AskUserQuestionView`
- Reuse existing notification open logic (`.notification` reason)

#### `ClaudeInstancesView.swift`

- Show question icon for sessions in `.waitingForQuestion`

## 12. Files Summary

### Modified (9 files)
1. `ClaudeIsland/Resources/codeisland-state.py`
2. `ClaudeIsland/Models/SessionPhase.swift`
3. `ClaudeIsland/Models/SessionEvent.swift`
4. `ClaudeIsland/Services/Hooks/HookSocketServer.swift`
5. `ClaudeIsland/Services/State/SessionStore.swift`
6. `ClaudeIsland/Services/Session/ClaudeSessionMonitor.swift`
7. `ClaudeIsland/Utilities/SessionPhaseHelpers.swift`
8. `ClaudeIsland/UI/Components/StatusIcons.swift`
9. `ClaudeIsland/UI/Views/NotchView.swift`

### New (3 files)
1. `ClaudeIsland/UI/Views/AskUserQuestionView.swift`
2. `ClaudeIsland/UI/Components/ChipFlowLayout.swift`
3. `ClaudeIsland/Services/Shared/QuestionResponder.swift`

### Unchanged (leveraged as-is)
- `ToolResultData.swift` — `AskUserQuestionResult`, `QuestionItem`, `QuestionOption` already defined
- `ConversationParser.swift` — `parseAskUserQuestionResult()` already implemented
- `ToolResultViews.swift` — `AskUserQuestionResultContent` for post-hoc display
- `HookInstaller.swift` — `PreToolUse` hook already registered
