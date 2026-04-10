# AskUserQuestion Interactive Support — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users see and answer Claude Code's `AskUserQuestion` prompts directly in the Code Island notch panel.

**Architecture:** Extend the existing `PermissionRequest` bidirectional socket mechanism to handle `AskUserQuestion`. The Python hook script blocks on `PreToolUse` when the tool is `AskUserQuestion`, Code Island shows a chip-flow UI, and sends the answer back through the socket. Falls back to tmux send-keys if hook output doesn't work.

**Tech Stack:** Swift/SwiftUI, Python (hook script), Unix domain sockets

**Spec:** `docs/superpowers/specs/2026-04-09-ask-user-question-design.md`

---

## File Structure

### New Files
| File | Responsibility |
|------|---------------|
| `ClaudeIsland/UI/Views/AskUserQuestionView.swift` | Interactive question UI with chip-flow options, Other text input, submit/skip buttons |
| `ClaudeIsland/UI/Components/ChipFlowLayout.swift` | Custom SwiftUI `Layout` for horizontal chip wrapping |
| `ClaudeIsland/Services/Shared/QuestionResponder.swift` | Answer delivery: hook socket primary, tmux send-keys fallback |

### Modified Files
| File | Change |
|------|--------|
| `ClaudeIsland/Resources/codeisland-state.py` | Add `AskUserQuestion` blocking path in `PreToolUse` |
| `ClaudeIsland/Models/SessionPhase.swift` | Add `.waitingForQuestion(QuestionContext)` case |
| `ClaudeIsland/Models/SessionEvent.swift` | Add `questionAnswered`/`questionSkipped` events + `determinePhase` update |
| `ClaudeIsland/Services/Hooks/HookSocketServer.swift` | Add `PendingQuestion`, `respondToQuestion()`, `skipQuestion()` |
| `ClaudeIsland/Services/State/SessionStore.swift` | Handle question events in `process()` and `processHookEvent()` |
| `ClaudeIsland/Services/Session/ClaudeSessionMonitor.swift` | Add `answerQuestion()` and `skipQuestion()` bridge methods |
| `ClaudeIsland/Utilities/SessionPhaseHelpers.swift` | Add color/description for `.waitingForQuestion` |
| `ClaudeIsland/UI/Components/StatusIcons.swift` | Add `WaitingForQuestionIcon` |
| `ClaudeIsland/UI/Views/NotchView.swift` | Handle `.waitingForQuestion` in dotColor and notification logic |

---

## Task 1: Python Hook Script — AskUserQuestion Blocking Path

**Files:**
- Modify: `ClaudeIsland/Resources/codeisland-state.py:52-71,103-110`

- [ ] **Step 1: Update `send_event()` to block for `waiting_for_question`**

In `codeisland-state.py`, change the blocking condition at line 61 from:

```python
        # For permission requests, wait for response
        if state.get("status") == "waiting_for_approval":
```

to:

```python
        # For permission requests and questions, wait for response
        if state.get("status") in ("waiting_for_approval", "waiting_for_question"):
```

- [ ] **Step 2: Add `AskUserQuestion` handling in `PreToolUse` branch**

Replace lines 103-110 (the `PreToolUse` branch) with:

```python
    elif event == "PreToolUse":
        tool_name = data.get("tool_name")

        if tool_name == "AskUserQuestion":
            # Block and wait for Code Island to respond (like PermissionRequest)
            state["status"] = "waiting_for_question"
            state["tool"] = tool_name
            state["tool_input"] = tool_input
            tool_use_id_from_event = data.get("tool_use_id")
            if tool_use_id_from_event:
                state["tool_use_id"] = tool_use_id_from_event

            response = send_event(state)

            if response:
                decision = response.get("decision", "skip")

                if decision == "answered":
                    # User answered in Code Island — pass answers through hook output
                    output = {
                        "hookSpecificOutput": {
                            "hookEventName": "PreToolUse",
                            "decision": {"behavior": "allow"},
                            "answers": response.get("answers", {}),
                        }
                    }
                    print(json.dumps(output))
                    sys.exit(0)

            # No response, skip, or timeout — let CLI handle it
            sys.exit(0)

        state["status"] = "running_tool"
        state["tool"] = tool_name
        state["tool_input"] = tool_input
        # Send tool_use_id to Swift for caching
        tool_use_id_from_event = data.get("tool_use_id")
        if tool_use_id_from_event:
            state["tool_use_id"] = tool_use_id_from_event
```

- [ ] **Step 3: Commit**

```bash
git add ClaudeIsland/Resources/codeisland-state.py
git commit -m "feat(hook): add AskUserQuestion blocking path in PreToolUse"
```

---

## Task 2: SessionPhase — Add `.waitingForQuestion`

**Files:**
- Modify: `ClaudeIsland/Models/SessionPhase.swift:12-40,54-69,74-134,136-178,180-193`

- [ ] **Step 1: Add `QuestionContext` struct**

After `PermissionContext` (after line 40), add:

```swift
/// Context for an AskUserQuestion prompt awaiting user response.
struct QuestionContext: Equatable, Sendable {
    let toolUseId: String
    let questions: [QuestionItem]
    let receivedAt: Date

    static func == (lhs: QuestionContext, rhs: QuestionContext) -> Bool {
        lhs.toolUseId == rhs.toolUseId
    }
}
```

- [ ] **Step 2: Add `.waitingForQuestion` enum case**

After `.waitingForApproval(PermissionContext)` (line 63), add:

```swift
    /// Claude is asking the user a question (AskUserQuestion tool)
    case waitingForQuestion(QuestionContext)
```

- [ ] **Step 3: Update `canTransition(to:)` method**

In the `canTransition` method, add transitions for `.waitingForQuestion`. After the `.waitingForApproval` cases (around line 112), add:

```swift
        case .waitingForQuestion:
            switch to {
            case .processing, .idle, .ended, .waitingForQuestion:
                return true
            default:
                return false
            }
```

Also add `.waitingForQuestion` as a valid target from `.processing`:

In the `.processing` switch (around line 96), add `.waitingForQuestion` to the allowed targets:

```swift
        case .processing:
            switch to {
            case .waitingForInput, .idle, .waitingForApproval, .waitingForQuestion, .compacting, .ended, .processing:
                return true
            default:
                return false
            }
```

- [ ] **Step 4: Update computed properties**

In the `needsAttention` property (around line 142), add `.waitingForQuestion`:

```swift
    var needsAttention: Bool {
        switch self {
        case .waitingForApproval, .waitingForInput, .waitingForQuestion:
            return true
        default:
            return false
        }
    }
```

Add helper properties after the existing ones:

```swift
    var isWaitingForQuestion: Bool {
        if case .waitingForQuestion = self { return true }
        return false
    }

    var questionContext: QuestionContext? {
        if case .waitingForQuestion(let ctx) = self { return ctx }
        return nil
    }
```

- [ ] **Step 5: Update `Equatable` conformance**

In the `==` operator (around line 180), add the `.waitingForQuestion` case:

```swift
        case (.waitingForQuestion(let lhs), .waitingForQuestion(let rhs)):
            return lhs == rhs
```

- [ ] **Step 6: Compile check**

```bash
xcodebuild -project ClaudeIsland.xcodeproj -scheme ClaudeIsland -configuration Debug CODE_SIGN_IDENTITY="-" CODE_SIGNING_REQUIRED=NO CODE_SIGNING_ALLOWED=NO DEVELOPMENT_TEAM="" build 2>&1 | tail -5
```

Expected: Build errors in files that switch on `SessionPhase` exhaustively (this is expected — we fix them in subsequent tasks).

- [ ] **Step 7: Commit**

```bash
git add ClaudeIsland/Models/SessionPhase.swift
git commit -m "feat(model): add .waitingForQuestion phase with QuestionContext"
```

---

## Task 3: SessionEvent — Add Question Events + `determinePhase` Update

**Files:**
- Modify: `ClaudeIsland/Models/SessionEvent.swift:13-81,134-166`
- Modify: `ClaudeIsland/Services/Hooks/HookSocketServer.swift:53-82`

- [ ] **Step 1: Add question events to `SessionEvent`**

After `permissionSocketFailed` (line 28), add:

```swift
    // Question events (AskUserQuestion)
    /// User answered questions from Code Island UI
    case questionAnswered(sessionId: String, toolUseId: String, answers: [String: String])
    /// User skipped / jumped to terminal
    case questionSkipped(sessionId: String, toolUseId: String)
```

- [ ] **Step 2: Update `HookEvent.sessionPhase` to handle `waiting_for_question`**

In `HookSocketServer.swift`, in the `sessionPhase` computed var (line 53), add after the `waiting_for_approval` case (around line 58):

```swift
        case "waiting_for_question":
            if let tool = tool {
                // QuestionContext will be built in determinePhase with full question data
                return .processing  // Placeholder; determinePhase handles the real logic
            }
            return .processing
```

- [ ] **Step 3: Update `HookEvent.expectsResponse`**

In `HookSocketServer.swift`, change line 80-82 from:

```swift
    nonisolated var expectsResponse: Bool {
        event == "PermissionRequest" && status == "waiting_for_approval"
    }
```

to:

```swift
    nonisolated var expectsResponse: Bool {
        (event == "PermissionRequest" && status == "waiting_for_approval") ||
        (event == "PreToolUse" && status == "waiting_for_question")
    }
```

- [ ] **Step 4: Update `determinePhase()` in SessionEvent.swift**

In `determinePhase()` (line 134), after the `expectsResponse` block that creates `.waitingForApproval` (lines 141-148), add:

```swift
        // AskUserQuestion creates waitingForQuestion state
        if event == "PreToolUse" && status == "waiting_for_question",
           let tool = tool {
            let questionItems = parseQuestionItems(from: toolInput)
            return .waitingForQuestion(QuestionContext(
                toolUseId: toolUseId ?? "",
                questions: questionItems,
                receivedAt: Date()
            ))
        }
```

Then add the helper method at the end of the `HookEvent` extension:

```swift
    /// Parse QuestionItem array from AskUserQuestion tool input
    private nonisolated func parseQuestionItems(from input: [String: AnyCodable]?) -> [QuestionItem] {
        guard let input = input,
              let questionsRaw = input["questions"]?.value as? [[String: Any]] else {
            return []
        }
        return questionsRaw.compactMap { q in
            guard let question = q["question"] as? String else { return nil }
            let header = q["header"] as? String
            let optionsRaw = q["options"] as? [[String: Any]] ?? []
            let options = optionsRaw.compactMap { o -> QuestionOption? in
                guard let label = o["label"] as? String else { return nil }
                let description = o["description"] as? String
                return QuestionOption(label: label, description: description)
            }
            let multiSelect = q["multiSelect"] as? Bool ?? false
            return QuestionItem(question: question, header: header, options: options)
        }
    }
```

- [ ] **Step 5: Commit**

```bash
git add ClaudeIsland/Models/SessionEvent.swift ClaudeIsland/Services/Hooks/HookSocketServer.swift
git commit -m "feat(model): add question events and determinePhase for AskUserQuestion"
```

---

## Task 4: QuestionItem — Add `multiSelect` Field

**Files:**
- Modify: `ClaudeIsland/Models/ToolResultData.swift:195-199`

- [ ] **Step 1: Add `multiSelect` to `QuestionItem`**

Change the `QuestionItem` struct (lines 195-199) from:

```swift
struct QuestionItem: Equatable, Sendable {
    let question: String
    let header: String?
    let options: [QuestionOption]
}
```

to:

```swift
struct QuestionItem: Equatable, Sendable {
    let question: String
    let header: String?
    let options: [QuestionOption]
    let multiSelect: Bool
}
```

- [ ] **Step 2: Update `parseAskUserQuestionResult` in ConversationParser.swift**

Find the line where `QuestionItem` is constructed in `parseAskUserQuestionResult()` and add the `multiSelect` parameter:

```swift
let multiSelect = questionDict["multiSelect"] as? Bool ?? false
return QuestionItem(question: question, header: header, options: options, multiSelect: multiSelect)
```

- [ ] **Step 3: Commit**

```bash
git add ClaudeIsland/Models/ToolResultData.swift ClaudeIsland/Services/Session/ConversationParser.swift
git commit -m "feat(model): add multiSelect field to QuestionItem"
```

---

## Task 5: HookSocketServer — PendingQuestion + Response Methods

**Files:**
- Modify: `ClaudeIsland/Services/Hooks/HookSocketServer.swift:92-98,119,216-220,424-465,473-505`

- [ ] **Step 1: Add `PendingQuestion` struct**

After `PendingPermission` (line 98), add:

```swift
struct PendingQuestion: Sendable {
    let sessionId: String
    let toolUseId: String
    let questions: [QuestionItem]
    let clientSocket: Int32
    let receivedAt: Date
}
```

- [ ] **Step 2: Add `pendingQuestions` dictionary**

After `pendingPermissions` (line 119), add:

```swift
    private var pendingQuestions: [String: PendingQuestion] = [:]
```

- [ ] **Step 3: Add public response methods**

After `respondToPermission` (line 220), add:

```swift
    func respondToQuestion(toolUseId: String, answers: [String: String]) {
        queue.async { [weak self] in
            self?.sendQuestionResponse(toolUseId: toolUseId, decision: "answered", answers: answers)
        }
    }

    func skipQuestion(toolUseId: String) {
        queue.async { [weak self] in
            self?.sendQuestionResponse(toolUseId: toolUseId, decision: "skip", answers: nil)
        }
    }
```

- [ ] **Step 4: Add `sendQuestionResponse` private method**

After `sendPermissionResponse` (line 505), add:

```swift
    private func sendQuestionResponse(toolUseId: String, decision: String, answers: [String: String]?) {
        permissionsLock.lock()
        guard let pending = pendingQuestions.removeValue(forKey: toolUseId) else {
            permissionsLock.unlock()
            logger.debug("No pending question for toolUseId: \(toolUseId.prefix(12), privacy: .public)")
            return
        }
        permissionsLock.unlock()

        var responseDict: [String: Any] = ["decision": decision]
        if let answers = answers {
            responseDict["answers"] = answers
        }

        guard let data = try? JSONSerialization.data(withJSONObject: responseDict) else {
            close(pending.clientSocket)
            return
        }

        let age = Date().timeIntervalSince(pending.receivedAt)
        logger.info("Sending question response: \(decision, privacy: .public) for \(pending.sessionId.prefix(8), privacy: .public) (age: \(String(format: "%.1f", age), privacy: .public)s)")

        data.withUnsafeBytes { bytes in
            guard let baseAddress = bytes.baseAddress else { return }
            let result = write(pending.clientSocket, baseAddress, data.count)
            if result < 0 {
                logger.error("Question response write failed with errno: \(errno)")
            }
        }

        close(pending.clientSocket)
    }
```

- [ ] **Step 5: Update `handleClient` to store `PendingQuestion`**

In `handleClient` (around line 424), the existing `if event.expectsResponse` block creates `PendingPermission`. We need to branch based on event type. Replace the block starting at line 424 through line 465 to also handle questions:

After the existing `PendingPermission` creation block (line 453-462), add an else branch for questions:

```swift
        if event.expectsResponse {
            let toolUseId: String
            // ... existing toolUseId resolution code ...

            if event.status == "waiting_for_question" {
                // Parse questions from tool input
                let questionItems = event.parseQuestionItems()
                let pending = PendingQuestion(
                    sessionId: event.sessionId,
                    toolUseId: toolUseId,
                    questions: questionItems,
                    clientSocket: clientSocket,
                    receivedAt: Date()
                )
                permissionsLock.lock()
                pendingQuestions[toolUseId] = pending
                permissionsLock.unlock()

                eventHandler?(updatedEvent)
                return
            } else {
                // Existing PendingPermission logic
                let pending = PendingPermission(
                    sessionId: event.sessionId,
                    toolUseId: toolUseId,
                    clientSocket: clientSocket,
                    event: updatedEvent,
                    receivedAt: Date()
                )
                permissionsLock.lock()
                pendingPermissions[toolUseId] = pending
                permissionsLock.unlock()

                eventHandler?(updatedEvent)
                return
            }
        }
```

Add the `parseQuestionItems()` method to `HookEvent` (use the same one from Task 3 step 4, make it `nonisolated` and accessible).

- [ ] **Step 6: Commit**

```bash
git add ClaudeIsland/Services/Hooks/HookSocketServer.swift
git commit -m "feat(socket): add PendingQuestion and question response methods"
```

---

## Task 6: SessionStore — Process Question Events

**Files:**
- Modify: `ClaudeIsland/Services/State/SessionStore.swift:62-129,183-186`

- [ ] **Step 1: Add question event cases to `process()`**

In the `process(_ event:)` method (line 62), add cases for the new events. After the `permissionSocketFailed` case, add:

```swift
        case .questionAnswered(let sessionId, let toolUseId, _):
            processQuestionAnswered(sessionId: sessionId, toolUseId: toolUseId)
        case .questionSkipped(let sessionId, let toolUseId):
            processQuestionSkipped(sessionId: sessionId, toolUseId: toolUseId)
```

- [ ] **Step 2: Add `processQuestionAnswered` method**

After the existing `processPermissionApproved` method, add:

```swift
    private func processQuestionAnswered(sessionId: String, toolUseId: String) {
        guard var session = sessions[sessionId] else { return }

        if session.phase.isWaitingForQuestion {
            session.phase = .processing
        }

        sessions[sessionId] = session
        publishState()
    }
```

- [ ] **Step 3: Add `processQuestionSkipped` method**

```swift
    private func processQuestionSkipped(sessionId: String, toolUseId: String) {
        guard var session = sessions[sessionId] else { return }

        if session.phase.isWaitingForQuestion {
            session.phase = .processing
        }

        sessions[sessionId] = session
        publishState()
    }
```

- [ ] **Step 4: Handle PostToolUse cleanup for AskUserQuestion**

In `processHookEvent` (line 141), after the `PermissionRequest` tool status update (lines 183-186), add cleanup for PostToolUse of AskUserQuestion:

```swift
        // Clean up pending question when PostToolUse arrives for AskUserQuestion
        if event.event == "PostToolUse" && event.tool == "AskUserQuestion" {
            if session.phase.isWaitingForQuestion {
                session.phase = .processing
            }
        }
```

- [ ] **Step 5: Commit**

```bash
git add ClaudeIsland/Services/State/SessionStore.swift
git commit -m "feat(store): handle question answered/skipped/PostToolUse events"
```

---

## Task 7: ClaudeSessionMonitor — Bridge Methods

**Files:**
- Modify: `ClaudeIsland/Services/Session/ClaudeSessionMonitor.swift:84-121`

- [ ] **Step 1: Add question handling methods**

After the `denyPermission` method (line 121), add:

```swift
    // MARK: - Question Handling

    func answerQuestion(sessionId: String, answers: [String: String]) {
        Task {
            guard let session = await SessionStore.shared.session(for: sessionId),
                  let questionCtx = session.phase.questionContext else {
                return
            }

            HookSocketServer.shared.respondToQuestion(
                toolUseId: questionCtx.toolUseId,
                answers: answers
            )

            await SessionStore.shared.process(
                .questionAnswered(sessionId: sessionId, toolUseId: questionCtx.toolUseId, answers: answers)
            )
        }
    }

    func skipQuestion(sessionId: String) {
        Task {
            guard let session = await SessionStore.shared.session(for: sessionId),
                  let questionCtx = session.phase.questionContext else {
                return
            }

            HookSocketServer.shared.skipQuestion(toolUseId: questionCtx.toolUseId)

            await SessionStore.shared.process(
                .questionSkipped(sessionId: sessionId, toolUseId: questionCtx.toolUseId)
            )
        }
    }
```

- [ ] **Step 2: Commit**

```bash
git add ClaudeIsland/Services/Session/ClaudeSessionMonitor.swift
git commit -m "feat(monitor): add answerQuestion and skipQuestion bridge methods"
```

---

## Task 8: SessionPhaseHelpers + StatusIcons — UI Support

**Files:**
- Modify: `ClaudeIsland/Utilities/SessionPhaseHelpers.swift:12-43`
- Modify: `ClaudeIsland/UI/Components/StatusIcons.swift:219-240`

- [ ] **Step 1: Add `.waitingForQuestion` to `phaseColor`**

In `SessionPhaseHelpers.swift`, in `phaseColor` (line 12), add after the `.waitingForApproval` case:

```swift
        case .waitingForQuestion:
            return TerminalColors.amber
```

- [ ] **Step 2: Add `.waitingForQuestion` to `phaseDescription`**

In `phaseDescription` (line 28), add:

```swift
        case .waitingForQuestion:
            return "Asking question"
```

- [ ] **Step 3: Add `WaitingForQuestionIcon`**

In `StatusIcons.swift`, before the `StatusIcon` view (line 219), add:

```swift
struct WaitingForQuestionIcon: View {
    var body: some View {
        ZStack {
            Circle()
                .fill(TerminalColors.amber.opacity(0.2))
                .frame(width: 20, height: 20)
            Text("?")
                .font(.system(size: 12, weight: .bold, design: .monospaced))
                .foregroundColor(TerminalColors.amber)
        }
    }
}
```

- [ ] **Step 4: Add `.waitingForQuestion` case to `StatusIcon` view**

In the `StatusIcon` view's switch (around line 231), add after `.waitingForApproval`:

```swift
            case .waitingForQuestion:
                WaitingForQuestionIcon()
```

- [ ] **Step 5: Commit**

```bash
git add ClaudeIsland/Utilities/SessionPhaseHelpers.swift ClaudeIsland/UI/Components/StatusIcons.swift
git commit -m "feat(ui): add phase color, description, and icon for waitingForQuestion"
```

---

## Task 9: NotchView — Handle `.waitingForQuestion` State

**Files:**
- Modify: `ClaudeIsland/UI/Views/NotchView.swift:708-718`

- [ ] **Step 1: Add `.waitingForQuestion` to `dotColor`**

In the `dotColor(for:)` function (line 707), add after `.waitingForApproval`:

```swift
        case .waitingForQuestion:
            return TerminalColors.amber
```

- [ ] **Step 2: Fix any remaining exhaustive switch errors**

Search for all `switch` statements on `SessionPhase` across the codebase and add `.waitingForQuestion` cases. These will typically mirror `.waitingForApproval` behavior.

- [ ] **Step 3: Compile check**

```bash
xcodebuild -project ClaudeIsland.xcodeproj -scheme ClaudeIsland -configuration Debug CODE_SIGN_IDENTITY="-" CODE_SIGNING_REQUIRED=NO CODE_SIGNING_ALLOWED=NO DEVELOPMENT_TEAM="" build 2>&1 | tail -5
```

Expected: **BUILD SUCCEEDED** (all switch exhaustiveness errors resolved).

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "feat(notch): handle .waitingForQuestion in all phase switches"
```

---

## Task 10: ChipFlowLayout — Custom SwiftUI Layout

**Files:**
- Create: `ClaudeIsland/UI/Components/ChipFlowLayout.swift`

- [ ] **Step 1: Create `ChipFlowLayout`**

```swift
//
//  ChipFlowLayout.swift
//  ClaudeIsland
//
//  Horizontal chip layout with automatic line wrapping
//

import SwiftUI

struct ChipFlowLayout: Layout {
    var spacing: CGFloat = 6

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let result = arrange(proposal: proposal, subviews: subviews)
        return result.size
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let result = arrange(proposal: proposal, subviews: subviews)
        for (index, position) in result.positions.enumerated() {
            subviews[index].place(
                at: CGPoint(x: bounds.minX + position.x, y: bounds.minY + position.y),
                proposal: ProposedViewSize(result.sizes[index])
            )
        }
    }

    private struct ArrangeResult {
        var size: CGSize
        var positions: [CGPoint]
        var sizes: [CGSize]
    }

    private func arrange(proposal: ProposedViewSize, subviews: Subviews) -> ArrangeResult {
        let maxWidth = proposal.width ?? .infinity
        var positions: [CGPoint] = []
        var sizes: [CGSize] = []
        var x: CGFloat = 0
        var y: CGFloat = 0
        var rowHeight: CGFloat = 0
        var totalHeight: CGFloat = 0
        var totalWidth: CGFloat = 0

        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            sizes.append(size)

            if x + size.width > maxWidth && x > 0 {
                // Wrap to next line
                x = 0
                y += rowHeight + spacing
                rowHeight = 0
            }

            positions.append(CGPoint(x: x, y: y))
            rowHeight = max(rowHeight, size.height)
            x += size.width + spacing
            totalWidth = max(totalWidth, x - spacing)
            totalHeight = y + rowHeight
        }

        return ArrangeResult(
            size: CGSize(width: totalWidth, height: totalHeight),
            positions: positions,
            sizes: sizes
        )
    }
}
```

- [ ] **Step 2: Commit**

```bash
git add ClaudeIsland/UI/Components/ChipFlowLayout.swift
git commit -m "feat(ui): add ChipFlowLayout for horizontal chip wrapping"
```

---

## Task 11: AskUserQuestionView — Interactive Question UI

**Files:**
- Create: `ClaudeIsland/UI/Views/AskUserQuestionView.swift`

- [ ] **Step 1: Create the view**

```swift
//
//  AskUserQuestionView.swift
//  ClaudeIsland
//
//  Interactive UI for answering AskUserQuestion prompts from Claude Code
//

import SwiftUI

struct AskUserQuestionView: View {
    let session: SessionState
    let context: QuestionContext
    @ObservedObject var sessionMonitor: ClaudeSessionMonitor

    @State private var selections: [Int: Set<String>] = [:]  // questionIndex -> selected labels
    @State private var otherTexts: [Int: String] = [:]        // questionIndex -> custom text
    @State private var showOther: [Int: Bool] = [:]           // questionIndex -> showing Other field

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            header
            questionsList
            submitBar
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
    }

    // MARK: - Header

    private var header: some View {
        HStack {
            Text(session.projectName)
                .font(.system(size: 11, weight: .semibold))
                .foregroundColor(.white.opacity(0.5))
            Spacer()
            Button(action: jumpToTerminal) {
                HStack(spacing: 3) {
                    Image(systemName: "terminal")
                    Text("Terminal")
                }
                .font(.system(size: 10))
                .foregroundColor(.white.opacity(0.5))
            }
            .buttonStyle(.plain)
        }
    }

    // MARK: - Questions List

    private var questionsList: some View {
        ScrollView(.vertical, showsIndicators: false) {
            VStack(alignment: .leading, spacing: 14) {
                ForEach(Array(context.questions.enumerated()), id: \.offset) { index, question in
                    questionBlock(index: index, question: question)
                }
            }
        }
    }

    @ViewBuilder
    private func questionBlock(index: Int, question: QuestionItem) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            // Question text
            Text(question.question)
                .font(.system(size: 12, weight: .medium))
                .foregroundColor(.white.opacity(0.9))

            // Option chips
            ChipFlowLayout(spacing: 6) {
                ForEach(question.options, id: \.label) { option in
                    chipButton(
                        label: option.label,
                        isSelected: selections[index]?.contains(option.label) == true,
                        action: { toggleOption(index: index, label: option.label, multiSelect: question.multiSelect) }
                    )
                }
                // "Other" chip
                chipButton(
                    label: "Other",
                    isSelected: showOther[index] == true,
                    action: { showOther[index] = !(showOther[index] ?? false) }
                )
            }

            // Selected option description
            if let selected = selections[index]?.first,
               let desc = question.options.first(where: { $0.label == selected })?.description {
                Text(desc)
                    .font(.system(size: 10))
                    .foregroundColor(.white.opacity(0.4))
                    .padding(.leading, 2)
            }

            // Other text field
            if showOther[index] == true {
                TextField("Type your answer...", text: Binding(
                    get: { otherTexts[index] ?? "" },
                    set: { otherTexts[index] = $0 }
                ))
                .textFieldStyle(.plain)
                .font(.system(size: 11, design: .monospaced))
                .padding(6)
                .background(Color.white.opacity(0.08))
                .cornerRadius(6)
            }
        }
    }

    private func chipButton(label: String, isSelected: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(label)
                .font(.system(size: 11, weight: isSelected ? .semibold : .regular))
                .padding(.horizontal, 10)
                .padding(.vertical, 5)
                .background(isSelected ? TerminalColors.amber.opacity(0.3) : Color.white.opacity(0.08))
                .foregroundColor(isSelected ? TerminalColors.amber : .white.opacity(0.7))
                .cornerRadius(12)
                .overlay(
                    RoundedRectangle(cornerRadius: 12)
                        .stroke(isSelected ? TerminalColors.amber.opacity(0.5) : Color.clear, lineWidth: 1)
                )
        }
        .buttonStyle(.plain)
    }

    // MARK: - Submit Bar

    private var submitBar: some View {
        HStack {
            Spacer()
            Button(action: submit) {
                Text("Submit")
                    .font(.system(size: 11, weight: .semibold))
                    .padding(.horizontal, 14)
                    .padding(.vertical, 5)
                    .background(canSubmit ? TerminalColors.amber : Color.white.opacity(0.1))
                    .foregroundColor(canSubmit ? .black : .white.opacity(0.3))
                    .cornerRadius(8)
            }
            .buttonStyle(.plain)
            .disabled(!canSubmit)
        }
    }

    // MARK: - Logic

    private var canSubmit: Bool {
        for (index, _) in context.questions.enumerated() {
            let hasSelection = !(selections[index] ?? []).isEmpty
            let hasOther = !(otherTexts[index] ?? "").isEmpty && showOther[index] == true
            if !hasSelection && !hasOther { return false }
        }
        return true
    }

    private func toggleOption(index: Int, label: String, multiSelect: Bool) {
        // Deselect "Other" when selecting a predefined option
        showOther[index] = false
        otherTexts[index] = nil

        if multiSelect {
            var current = selections[index] ?? []
            if current.contains(label) {
                current.remove(label)
            } else {
                current.insert(label)
            }
            selections[index] = current
        } else {
            selections[index] = [label]
        }
    }

    private func submit() {
        var answers: [String: String] = [:]
        for (index, question) in context.questions.enumerated() {
            if showOther[index] == true, let text = otherTexts[index], !text.isEmpty {
                answers[question.question] = text
            } else if let selected = selections[index] {
                answers[question.question] = selected.joined(separator: ", ")
            }
        }
        sessionMonitor.answerQuestion(sessionId: session.sessionId, answers: answers)
    }

    private func jumpToTerminal() {
        sessionMonitor.skipQuestion(sessionId: session.sessionId)
        Task {
            await TerminalJumper.shared.jump(to: session)
        }
    }
}
```

- [ ] **Step 2: Add to Xcode project**

Add the file to the ClaudeIsland target in the Xcode project.

- [ ] **Step 3: Commit**

```bash
git add ClaudeIsland/UI/Views/AskUserQuestionView.swift
git commit -m "feat(ui): add AskUserQuestionView with chip-flow interactive options"
```

---

## Task 12: QuestionResponder — Tmux Fallback

**Files:**
- Create: `ClaudeIsland/Services/Shared/QuestionResponder.swift`

- [ ] **Step 1: Create the responder**

```swift
//
//  QuestionResponder.swift
//  ClaudeIsland
//
//  Delivers AskUserQuestion answers to Claude Code.
//  Primary: hook socket response. Fallback: tmux send-keys.
//

import Foundation

actor QuestionResponder {
    static let shared = QuestionResponder()

    private init() {}

    /// Send answer via tmux send-keys as fallback
    /// Maps the selected option label to its 1-based index in the CLI list
    func sendViaTmux(session: SessionState, optionIndex: Int) async {
        guard let tty = session.tty else { return }

        // AskUserQuestion CLI shows options as numbered list (1, 2, 3...)
        // Send the number + Enter
        let keys = "\(optionIndex)"
        let tmuxPath = TmuxPathFinder.findTmuxPath() ?? "/opt/homebrew/bin/tmux"

        do {
            // Find the tmux pane for this tty
            let panes = try await ProcessExecutor.shared.run(tmuxPath, arguments: [
                "list-panes", "-a", "-F", "#{pane_tty} #{pane_id}"
            ])
            let targetPane = panes.split(separator: "\n")
                .first { $0.contains(tty) }?
                .split(separator: " ")
                .last
                .map(String.init)

            guard let paneId = targetPane else { return }

            _ = try await ProcessExecutor.shared.run(tmuxPath, arguments: [
                "send-keys", "-t", paneId, "-l", keys
            ])
            _ = try await ProcessExecutor.shared.run(tmuxPath, arguments: [
                "send-keys", "-t", paneId, "Enter"
            ])
        } catch {
            DebugLogger.log("QuestionResponder", "tmux fallback failed: \(error)")
        }
    }
}
```

- [ ] **Step 2: Commit**

```bash
git add ClaudeIsland/Services/Shared/QuestionResponder.swift
git commit -m "feat(responder): add QuestionResponder with tmux send-keys fallback"
```

---

## Task 13: Integration — Wire AskUserQuestionView into NotchView

**Files:**
- Modify: `ClaudeIsland/UI/Views/NotchView.swift`

- [ ] **Step 1: Add `.waitingForQuestion` detection to notification handling**

In the notification/status change handlers where `.waitingForApproval` opens the notch, add the same logic for `.waitingForQuestion`. Find the pending sessions handler (around line 488-502) and add parallel handling:

In `handleStatusChange` (around line 469), add:

```swift
        case .waitingForQuestion:
            isVisible = true
```

- [ ] **Step 2: Show `AskUserQuestionView` when appropriate**

In the opened content area of NotchView (where `ClaudeInstancesView` and `ChatView` are shown based on `contentType`), add a check for `.waitingForQuestion`:

When the notch is opened and the active session is in `.waitingForQuestion`, overlay or replace the content with `AskUserQuestionView`. The exact integration point depends on how the current view hierarchy switches content — follow the pattern used for `.waitingForApproval` in `ClaudeInstancesView`.

- [ ] **Step 3: Build and verify**

```bash
xcodebuild -project ClaudeIsland.xcodeproj -scheme ClaudeIsland -configuration Release CODE_SIGN_IDENTITY="-" CODE_SIGNING_REQUIRED=NO CODE_SIGNING_ALLOWED=NO DEVELOPMENT_TEAM="" CONFIGURATION_BUILD_DIR="$(pwd)/build" build 2>&1 | tail -5
```

Expected: **BUILD SUCCEEDED**

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "feat: integrate AskUserQuestionView into NotchView"
```

---

## Task 14: Manual Testing Checklist

- [ ] **Step 1: Test the full flow**

1. Start Code Island app
2. In a Claude Code session, trigger `AskUserQuestion` (e.g., ask Claude to present choices)
3. Verify: notch expands showing question with chip options
4. Click an option chip → verify it highlights
5. Click Submit → verify answer is sent to Claude Code
6. Verify Claude Code continues with the selected answer

- [ ] **Step 2: Test edge cases**

1. **Jump to Terminal**: Click "Terminal" button → verify notch closes, terminal activates
2. **Answer in CLI directly**: When question shows in notch, answer in CLI instead → verify notch auto-closes on PostToolUse
3. **Other text**: Select "Other", type custom text, submit → verify custom text is received
4. **Multiple questions**: If possible, trigger multi-question AskUserQuestion → verify scroll works
5. **multiSelect**: Trigger a multiSelect question → verify multiple chips can be selected

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "feat: AskUserQuestion interactive support complete"
```
