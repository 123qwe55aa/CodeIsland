//
//  SessionEvent.swift
//  ClaudeIsland
//
//  Unified event types for the session state machine.
//  All state changes flow through SessionStore.process(event).
//

import Foundation

/// All events that can affect session state
/// This is the single entry point for state mutations
enum SessionEvent: Sendable {
    // MARK: - Hook Events (from HookSocketServer)

    /// A hook event was received from Claude Code
    case hookReceived(HookEvent)

    // MARK: - Permission Events (user actions)

    /// User approved a permission request
    case permissionApproved(sessionId: String, toolUseId: String)

    /// User denied a permission request
    case permissionDenied(sessionId: String, toolUseId: String, reason: String?)

    /// Permission socket failed (connection died before response)
    case permissionSocketFailed(sessionId: String, toolUseId: String)

    // MARK: - Question Events (user actions on AskUserQuestion)

    /// User answered a question from AskUserQuestion tool
    case questionAnswered(sessionId: String, toolUseId: String, answers: [String: String])

    /// User skipped a question from AskUserQuestion tool
    case questionSkipped(sessionId: String, toolUseId: String)

    // MARK: - File Events (from ConversationParser)

    /// JSONL file was updated with new content
    case fileUpdated(FileUpdatePayload)

    // MARK: - Tool Completion Events (from JSONL parsing)

    /// A tool was detected as completed via JSONL result
    /// This is the authoritative signal that a tool has finished
    case toolCompleted(sessionId: String, toolUseId: String, result: ToolCompletionResult)

    // MARK: - Interrupt Events (from JSONLInterruptWatcher)

    /// User interrupted Claude (detected via JSONL)
    case interruptDetected(sessionId: String)

    // MARK: - Subagent Events (Task tool tracking)

    /// A Task (subagent) tool has started
    case subagentStarted(sessionId: String, taskToolId: String)

    /// A tool was executed within an active subagent
    case subagentToolExecuted(sessionId: String, tool: SubagentToolCall)

    /// A subagent tool completed (status update)
    case subagentToolCompleted(sessionId: String, toolId: String, status: ToolStatus)

    /// A Task (subagent) tool has stopped
    case subagentStopped(sessionId: String, taskToolId: String)

    /// Agent file was updated with new subagent tools (from AgentFileWatcher)
    case agentFileUpdated(sessionId: String, taskToolId: String, tools: [SubagentToolInfo])

    // MARK: - Clear Events (from JSONL detection)

    /// User issued /clear command - reset UI state while keeping session alive
    case clearDetected(sessionId: String)

    // MARK: - Session Lifecycle

    /// Session has ended
    case sessionEnded(sessionId: String)

    /// Remove all ended sessions from state
    case clearEndedSessions

    /// User removed a session from the UI
    case removeSession(sessionId: String)

    /// Request to load initial history from file
    case loadHistory(sessionId: String, cwd: String)

    /// History load completed
    case historyLoaded(sessionId: String, messages: [ChatMessage], completedTools: Set<String>, toolResults: [String: ConversationParser.ToolResult], structuredResults: [String: ToolResultData], conversationInfo: ConversationInfo)
}

/// Payload for file update events
struct FileUpdatePayload: Sendable {
    let sessionId: String
    let cwd: String
    /// Messages to process - either only new messages (if isIncremental) or all messages
    let messages: [ChatMessage]
    /// When true, messages contains only NEW messages since last update
    /// When false, messages contains ALL messages (used for initial load or after /clear)
    let isIncremental: Bool
    let completedToolIds: Set<String>
    let toolResults: [String: ConversationParser.ToolResult]
    let structuredResults: [String: ToolResultData]
}

/// Result of a tool completion detected from JSONL
struct ToolCompletionResult: Sendable {
    let status: ToolStatus
    let result: String?
    let structuredResult: ToolResultData?

    nonisolated static func from(parserResult: ConversationParser.ToolResult?, structuredResult: ToolResultData?) -> ToolCompletionResult {
        let status: ToolStatus
        if parserResult?.isInterrupted == true {
            status = .interrupted
        } else if parserResult?.isError == true {
            status = .error
        } else {
            status = .success
        }

        var resultText: String? = nil
        if let r = parserResult {
            if !r.isInterrupted {
                if let stdout = r.stdout, !stdout.isEmpty {
                    resultText = stdout
                } else if let stderr = r.stderr, !stderr.isEmpty {
                    resultText = stderr
                } else if let content = r.content, !content.isEmpty {
                    resultText = content
                }
            }
        }

        return ToolCompletionResult(status: status, result: resultText, structuredResult: structuredResult)
    }
}

// MARK: - Hook Event Extensions

extension HookEvent {
    /// Determine the target session phase based on this hook event
    nonisolated func determinePhase() -> SessionPhase {
        // PreCompact takes priority
        if event == "PreCompact" {
            return .compacting
        }

        // Permission request creates waitingForApproval state
        if expectsResponse && event == "PermissionRequest", let tool = tool {
            return .waitingForApproval(PermissionContext(
                toolUseId: toolUseId ?? "",
                toolName: tool,
                toolInput: toolInput,
                receivedAt: Date()
            ))
        }

        // AskUserQuestion: detect from PreToolUse by tool name
        if event == "PreToolUse" && tool == "AskUserQuestion" {
            let questionItems = parseQuestionItems(from: toolInput)
            return .waitingForQuestion(QuestionContext(
                toolUseId: toolUseId ?? "",
                questions: questionItems,
                receivedAt: Date()
            ))
        }

        if event == "Notification" && notificationType == "idle_prompt" {
            return .idle
        }

        switch status {
        case "waiting_for_input":
            return .waitingForInput
        case "running_tool", "processing", "starting":
            return .processing
        case "compacting":
            return .compacting
        case "ended":
            return .ended
        default:
            return .idle
        }
    }

    /// Parse question items from tool input for AskUserQuestion
    nonisolated func parseQuestionItems(from input: [String: AnyCodable]?) -> [QuestionItem] {
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
            return QuestionItem(question: question, header: header, options: options, multiSelect: multiSelect)
        }
    }

    /// Whether this is a tool-related event
    nonisolated var isToolEvent: Bool {
        event == "PreToolUse" || event == "PostToolUse" || event == "PermissionRequest"
    }

    /// Whether this event should trigger a file sync
    nonisolated var shouldSyncFile: Bool {
        switch event {
        case "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop":
            return true
        default:
            return false
        }
    }
}

// MARK: - Debug Description

extension SessionEvent: CustomStringConvertible {
    nonisolated var description: String {
        switch self {
        case .hookReceived(let event):
            return "hookReceived(\(event.event), session: \(event.sessionId.prefix(8)))"
        case .permissionApproved(let sessionId, let toolUseId):
            return "permissionApproved(session: \(sessionId.prefix(8)), tool: \(toolUseId.prefix(12)))"
        case .permissionDenied(let sessionId, let toolUseId, _):
            return "permissionDenied(session: \(sessionId.prefix(8)), tool: \(toolUseId.prefix(12)))"
        case .permissionSocketFailed(let sessionId, let toolUseId):
            return "permissionSocketFailed(session: \(sessionId.prefix(8)), tool: \(toolUseId.prefix(12)))"
        case .questionAnswered(let sessionId, let toolUseId, _):
            return "questionAnswered(session: \(sessionId.prefix(8)), tool: \(toolUseId.prefix(12)))"
        case .questionSkipped(let sessionId, let toolUseId):
            return "questionSkipped(session: \(sessionId.prefix(8)), tool: \(toolUseId.prefix(12)))"
        case .fileUpdated(let payload):
            return "fileUpdated(session: \(payload.sessionId.prefix(8)), messages: \(payload.messages.count))"
        case .interruptDetected(let sessionId):
            return "interruptDetected(session: \(sessionId.prefix(8)))"
        case .clearDetected(let sessionId):
            return "clearDetected(session: \(sessionId.prefix(8)))"
        case .sessionEnded(let sessionId):
            return "sessionEnded(session: \(sessionId.prefix(8)))"
        case .loadHistory(let sessionId, _):
            return "loadHistory(session: \(sessionId.prefix(8)))"
        case .historyLoaded(let sessionId, let messages, _, _, _, _):
            return "historyLoaded(session: \(sessionId.prefix(8)), messages: \(messages.count))"
        case .toolCompleted(let sessionId, let toolUseId, let result):
            return "toolCompleted(session: \(sessionId.prefix(8)), tool: \(toolUseId.prefix(12)), status: \(result.status))"
        case .subagentStarted(let sessionId, let taskToolId):
            return "subagentStarted(session: \(sessionId.prefix(8)), task: \(taskToolId.prefix(12)))"
        case .subagentToolExecuted(let sessionId, let tool):
            return "subagentToolExecuted(session: \(sessionId.prefix(8)), tool: \(tool.name))"
        case .subagentToolCompleted(let sessionId, let toolId, let status):
            return "subagentToolCompleted(session: \(sessionId.prefix(8)), tool: \(toolId.prefix(12)), status: \(status))"
        case .subagentStopped(let sessionId, let taskToolId):
            return "subagentStopped(session: \(sessionId.prefix(8)), task: \(taskToolId.prefix(12)))"
        case .agentFileUpdated(let sessionId, let taskToolId, let tools):
            return "agentFileUpdated(session: \(sessionId.prefix(8)), task: \(taskToolId.prefix(12)), tools: \(tools.count))"
        case .clearEndedSessions:
            return "clearEndedSessions"
        case .removeSession(let sessionId):
            return "removeSession(session: \(sessionId.prefix(8)))"
        }
    }
}

// MARK: - HookEvent (moved from HookSocketServer.swift)

/// Event received from Claude Code hooks
struct HookEvent: Codable, Sendable {
    let sessionId: String
    let cwd: String
    let event: String
    let status: String
    let pid: Int?
    let tty: String?
    let tool: String?
    let toolInput: [String: AnyCodable]?
    let toolUseId: String?
    let notificationType: String?
    let message: String?
    let remoteHost: String?
    let remoteUser: String?
    let remoteTmuxTarget: String?
    let lastToolName: String?
    let conversationSummary: String?
    let conversationFirstMessage: String?
    let conversationLatestMessage: String?
    let conversationLastTool: String?
    let source: String?
    let transcriptPath: String?
    let terminalApp: String?
    let shouldSync: Bool?

    enum CodingKeys: String, CodingKey {
        case sessionId = "session_id"
        case cwd, event, status, pid, tty, tool
        case toolInput = "tool_input"
        case toolUseId = "tool_use_id"
        case notificationType = "notification_type"
        case message
        case remoteHost = "remote_host"
        case remoteUser = "remote_user"
        case remoteTmuxTarget = "remote_tmux_target"
        case lastToolName = "last_tool_name"
        case conversationSummary = "conversation_summary"
        case conversationFirstMessage = "conversation_first_message"
        case conversationLatestMessage = "conversation_latest_message"
        case conversationLastTool = "conversation_last_tool"
        case hookEventName = "hook_event_name"
        case sessionPhase = "session_phase"
        case source
        case transcriptPath = "transcript_path"
        case terminalApp = "terminal_app"
        case shouldSync = "should_sync_file"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        sessionId = try container.decodeIfPresent(String.self, forKey: .sessionId) ?? ""
        cwd = try container.decodeIfPresent(String.self, forKey: .cwd) ?? ""
        event = try container.decodeIfPresent(String.self, forKey: .event)
            ?? container.decodeIfPresent(String.self, forKey: .hookEventName)
            ?? ""
        status = try container.decodeIfPresent(String.self, forKey: .status) ?? ""
        pid = try container.decodeIfPresent(Int.self, forKey: .pid)
        tty = try container.decodeIfPresent(String.self, forKey: .tty)
        tool = try container.decodeIfPresent(String.self, forKey: .tool)
        toolInput = try container.decodeIfPresent([String: AnyCodable].self, forKey: .toolInput)
        toolUseId = try container.decodeIfPresent(String.self, forKey: .toolUseId)
        notificationType = try container.decodeIfPresent(String.self, forKey: .notificationType)
        message = try container.decodeIfPresent(String.self, forKey: .message)
        remoteHost = try container.decodeIfPresent(String.self, forKey: .remoteHost)
        remoteUser = try container.decodeIfPresent(String.self, forKey: .remoteUser)
        remoteTmuxTarget = try container.decodeIfPresent(String.self, forKey: .remoteTmuxTarget)
        lastToolName = try container.decodeIfPresent(String.self, forKey: .lastToolName)
        conversationSummary = try container.decodeIfPresent(String.self, forKey: .conversationSummary)
        conversationFirstMessage = try container.decodeIfPresent(String.self, forKey: .conversationFirstMessage)
        conversationLatestMessage = try container.decodeIfPresent(String.self, forKey: .conversationLatestMessage)
        conversationLastTool = try container.decodeIfPresent(String.self, forKey: .conversationLastTool)
        source = try container.decodeIfPresent(String.self, forKey: .source)
        transcriptPath = try container.decodeIfPresent(String.self, forKey: .transcriptPath)
        terminalApp = try container.decodeIfPresent(String.self, forKey: .terminalApp)
        shouldSync = try container.decodeIfPresent(Bool.self, forKey: .shouldSync)
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(sessionId, forKey: .sessionId)
        try container.encode(cwd, forKey: .cwd)
        try container.encode(event, forKey: .event)
        try container.encode(status, forKey: .status)
        try container.encodeIfPresent(pid, forKey: .pid)
        try container.encodeIfPresent(tty, forKey: .tty)
        try container.encodeIfPresent(tool, forKey: .tool)
        try container.encodeIfPresent(toolInput, forKey: .toolInput)
        try container.encodeIfPresent(toolUseId, forKey: .toolUseId)
        try container.encodeIfPresent(notificationType, forKey: .notificationType)
        try container.encodeIfPresent(message, forKey: .message)
        try container.encodeIfPresent(remoteHost, forKey: .remoteHost)
        try container.encodeIfPresent(remoteUser, forKey: .remoteUser)
        try container.encodeIfPresent(remoteTmuxTarget, forKey: .remoteTmuxTarget)
        try container.encodeIfPresent(lastToolName, forKey: .lastToolName)
        try container.encodeIfPresent(conversationSummary, forKey: .conversationSummary)
        try container.encodeIfPresent(conversationFirstMessage, forKey: .conversationFirstMessage)
        try container.encodeIfPresent(conversationLatestMessage, forKey: .conversationLatestMessage)
        try container.encodeIfPresent(conversationLastTool, forKey: .conversationLastTool)
        try container.encodeIfPresent(source, forKey: .source)
        try container.encodeIfPresent(transcriptPath, forKey: .transcriptPath)
        try container.encodeIfPresent(terminalApp, forKey: .terminalApp)
        try container.encodeIfPresent(shouldSync, forKey: .shouldSync)
    }

    init(sessionId: String, cwd: String, event: String, status: String, pid: Int?, tty: String?, tool: String?, toolInput: [String: AnyCodable]?, toolUseId: String?, notificationType: String?, message: String?, remoteHost: String? = nil, remoteUser: String? = nil, remoteTmuxTarget: String? = nil, lastToolName: String? = nil, conversationSummary: String? = nil, conversationFirstMessage: String? = nil, conversationLatestMessage: String? = nil, conversationLastTool: String? = nil, source: String? = nil, transcriptPath: String? = nil, terminalApp: String? = nil, shouldSync: Bool? = nil) {
        self.sessionId = sessionId
        self.cwd = cwd
        self.event = event
        self.status = status
        self.pid = pid
        self.tty = tty
        self.tool = tool
        self.toolInput = toolInput
        self.toolUseId = toolUseId
        self.notificationType = notificationType
        self.message = message
        self.remoteHost = remoteHost
        self.remoteUser = remoteUser
        self.remoteTmuxTarget = remoteTmuxTarget
        self.lastToolName = lastToolName
        self.conversationSummary = conversationSummary
        self.conversationFirstMessage = conversationFirstMessage
        self.conversationLatestMessage = conversationLatestMessage
        self.conversationLastTool = conversationLastTool
        self.source = source
        self.transcriptPath = transcriptPath
        self.terminalApp = terminalApp
        self.shouldSync = shouldSync
    }

    var sessionPhase: SessionPhase {
        if event == "PreCompact" { return .compacting }
        switch status {
        case "waiting_for_approval":
            return .waitingForApproval(PermissionContext(
                toolUseId: toolUseId ?? "",
                toolName: tool ?? "unknown",
                toolInput: toolInput,
                receivedAt: Date()
            ))
        case "waiting_for_input": return .waitingForInput
        case "running_tool", "processing", "starting": return .processing
        case "compacting": return .compacting
        default: return .idle
        }
    }

    nonisolated var expectsResponse: Bool {
        event == "PermissionRequest" && status == "waiting_for_approval"
    }
}

/// Response to send back to the hook
struct HookResponse: Codable {
    let decision: String
    let reason: String?
}

/// Pending permission request waiting for user decision
struct PendingPermission: Sendable {
    let sessionId: String
    let toolUseId: String
    let clientSocket: Int32
    let event: HookEvent
    let receivedAt: Date
}

/// Incoming message from SSH relay (has extra SSH metadata)
struct RelayMessage: Codable, Sendable {
    let type: String
    let psk: String?
    let version: String?
    let event: HookEvent?
    let remoteHost: String?
    let remoteUser: String?
    let remoteTmuxTarget: String?
    let action: String?
    let target: String?
    let text: String?
    let result: [String: AnyCodable]?
    let id: String?

    enum CodingKeys: String, CodingKey {
        case type, psk, version, event, remoteHost, remoteUser, remoteTmuxTarget
        case action, target, text, result, id
    }
}

/// Relay command for sending text to remote tmux
struct RelayCommand: Codable {
    let type: String
    let action: String
    let target: String
    let text: String?
    let id: String?
}

/// Type-erasing codable wrapper for heterogeneous values
struct AnyCodable: Codable, @unchecked Sendable {
    nonisolated(unsafe) let value: Any

    init(_ value: Any) { self.value = value }

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            value = NSNull()
        } else if let bool = try? container.decode(Bool.self) {
            value = bool
        } else if let int = try? container.decode(Int.self) {
            value = int
        } else if let double = try? container.decode(Double.self) {
            value = double
        } else if let string = try? container.decode(String.self) {
            value = string
        } else if let array = try? container.decode([AnyCodable].self) {
            value = array.map { $0.value }
        } else if let dict = try? container.decode([String: AnyCodable].self) {
            value = dict.mapValues { $0.value }
        } else {
            throw DecodingError.dataCorruptedError(in: container, debugDescription: "Cannot decode value")
        }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch value {
        case is NSNull: try container.encodeNil()
        case let bool as Bool: try container.encode(bool)
        case let int as Int: try container.encode(int)
        case let double as Double: try container.encode(double)
        case let string as String: try container.encode(string)
        case let array as [Any]: try container.encode(array.map { AnyCodable($0) })
        case let dict as [String: Any]: try container.encode(dict.mapValues { AnyCodable($0) })
        default: throw EncodingError.invalidValue(value, EncodingError.Context(codingPath: [], debugDescription: "Cannot encode value"))
        }
    }
}
