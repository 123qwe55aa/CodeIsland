//
//  CompletionPanelController.swift
//  ClaudeIsland
//
//  @MainActor wrapper around the pure CompletionPanelState. Owns all
//  side effects: the 15 s auto-dismiss Task, Combine subscription to
//  SessionStore.sessionsPublisher, KVO observer for the
//  "quickReplyEnabled" UserDefault. Spec §5.4.
//

import Combine
import Foundation

@MainActor
final class CompletionPanelController: NSObject, ObservableObject {
    static let shared = CompletionPanelController()

    @Published private(set) var state = CompletionPanelState()

    // MARK: - Dependencies / observers

    private var autoDismissTask: Task<Void, Never>?
    private var sessionsCancellable: AnyCancellable?
    private var observingEnabledKey = false
    private static let enabledKey = "quickReplyEnabled"

    // MARK: - Detection caches

    private var previousWaitingIds: Set<String> = []
    private var didCaptureBaseline = false
    private var previousPhaseByStableId: [String: SessionPhase] = [:]
    private var previousActiveTaskIds: [String: Set<String>] = [:]
    private var previousTaskContextByToolId: [String: [String: TaskContext]] = [:]
    private var lastKnownSessions: [String: SessionState] = [:]

    // MARK: - Init

    private override init() {
        super.init()
        UserDefaults.standard.addObserver(self, forKeyPath: Self.enabledKey, options: [.new, .old], context: nil)
        observingEnabledKey = true

        sessionsCancellable = SessionStore.shared.sessionsPublisher
            .receive(on: DispatchQueue.main)
            .sink { [weak self] sessions in
                Task { @MainActor [weak self] in self?.onSessionsUpdate(sessions) }
            }
    }

    deinit {
        if observingEnabledKey {
            UserDefaults.standard.removeObserver(self, forKeyPath: Self.enabledKey)
        }
    }

    // MARK: - KVO

    override nonisolated func observeValue(
        forKeyPath keyPath: String?, of object: Any?,
        change: [NSKeyValueChangeKey: Any]?, context: UnsafeMutableRawPointer?
    ) {
        guard keyPath == Self.enabledKey else { return }
        let oldV = (change?[.oldKey] as? Bool) ?? true
        let newV = (change?[.newKey] as? Bool) ?? true
        guard oldV != newV else { return }
        Task { @MainActor [weak self] in self?.applyEnabledChange() }
    }

    // MARK: - Public actions (called from views)

    func dismissFront(stableId: String) {
        state.dismissFront(stableId: stableId)
        while let next = state.front, !popTimePredicateHolds(for: next) {
            state.dismissFront(stableId: next.stableId)
        }
        restartTimer()
    }

    func recordSendFailure(stableId: String, message: String) {
        state.recordSendFailure(stableId: stableId, message: message)
        autoDismissTask?.cancel(); autoDismissTask = nil
    }

    func setPanelVisible(_ visible: Bool) {
        state.isPanelVisible = visible
        if visible { restartTimer() } else { autoDismissTask?.cancel(); autoDismissTask = nil }
    }

    // MARK: - Internals

    private func applyEnabledChange() {
        let enabled = (UserDefaults.standard.object(forKey: Self.enabledKey) as? Bool) ?? true
        state.flush(enabled: enabled)
        restartTimer()
    }

    private func onSessionsUpdate(_ sessions: [SessionState]) {
        lastKnownSessions = Dictionary(uniqueKeysWithValues: sessions.map { ($0.stableId, $0) })

        let waitingNow = sessions.filter { $0.phase == .waitingForInput }
        let waitingIds = Set(waitingNow.map(\.stableId))
        state.syncWithCurrentWaiting(waitingIds)

        let activeIds = Set(sessions.map(\.stableId))
        previousActiveTaskIds = previousActiveTaskIds.filter { activeIds.contains($0.key) }
        previousTaskContextByToolId = previousTaskContextByToolId.filter { activeIds.contains($0.key) }
        previousPhaseByStableId = previousPhaseByStableId.filter { activeIds.contains($0.key) }

        if !didCaptureBaseline {
            previousWaitingIds = waitingIds
            for session in sessions {
                previousPhaseByStableId[session.stableId] = session.phase
                previousActiveTaskIds[session.stableId] = Set(session.subagentState.activeTasks.keys)
                previousTaskContextByToolId[session.stableId] = session.subagentState.activeTasks
            }
            didCaptureBaseline = true
            return
        }

        let enabled = (UserDefaults.standard.object(forKey: Self.enabledKey) as? Bool) ?? true
        guard enabled else {
            refreshSnapshots(sessions)
            return
        }

        for session in sessions {
            let prevPhase = previousPhaseByStableId[session.stableId]
            let prevSubs = previousActiveTaskIds[session.stableId] ?? []
            let nowSubs = Set(session.subagentState.activeTasks.keys)
            let finishedSubs = prevSubs.subtracting(nowSubs)

            let transitionedToWaiting = (prevPhase == .processing || prevPhase == .compacting)
                && session.phase == .waitingForInput

            let transitionedToApproval: Bool = {
                guard let prev = prevPhase else { return false }
                if case .waitingForApproval = prev { return false }
                if case .waitingForApproval = session.phase { return true }
                return false
            }()

            if transitionedToWaiting, !finishedSubs.isEmpty {
                let lines = finishedSubs.compactMap { toolId -> SubagentLine? in
                    guard let ctx = (previousTaskContextByToolId[session.stableId] ?? [:])[toolId] else { return nil }
                    return Self.subagentLine(from: ctx)
                }
                guard !lines.isEmpty else { continue }
                state.enqueue(CompletionEntry(
                    stableId: session.stableId,
                    projectName: session.projectName,
                    variant: .subagentDone(subagents: lines)
                ))
            } else if transitionedToWaiting {
                if session.hasNoContentYet {
                    DebugLogger.log("CP/suppress", "claudeStop suppressed hasNoContentYet session=\(session.stableId.prefix(8))")
                    continue
                }
                if TerminalVisibilityDetector.isSessionTerminalFrontmost(session) {
                    DebugLogger.log("CP/suppress", "claudeStop suppressed terminalFrontmost session=\(session.stableId.prefix(8))")
                    continue
                }
                let rawSummary = resolveSummary(for: session)
                let clean = SummaryExtraction.extract(rawSummary)
                state.enqueue(CompletionEntry(
                    stableId: session.stableId,
                    projectName: session.projectName,
                    variant: .claudeStop(summary: clean)
                ))
            }

            if transitionedToApproval {
                if session.pendingToolName == "AskUserQuestion" { continue }
                guard let perm = session.activePermission else { continue }
                let toolName = perm.toolName
                let risk: RiskLevel =
                    ToolApprovalRequest.lowRiskTools.contains(toolName) ? .low :
                    ToolApprovalRequest.highRiskTools.contains(toolName) ? .high : .high
                // formattedInput is optional — fallback to empty string if nil
                let args = String((perm.formattedInput ?? "").prefix(200))
                state.enqueue(CompletionEntry(
                    stableId: session.stableId,
                    projectName: session.projectName,
                    variant: .pendingTool(request: ToolApprovalRequest(
                        toolName: toolName, argumentsSummary: args, riskLevel: risk
                    ))
                ))
            }
        }

        refreshSnapshots(sessions)
        restartTimer()
    }

    private func refreshSnapshots(_ sessions: [SessionState]) {
        var newPhase: [String: SessionPhase] = [:]
        var newSubs: [String: Set<String>] = [:]
        var newTaskCtx: [String: [String: TaskContext]] = [:]
        for session in sessions {
            newPhase[session.stableId] = session.phase
            newSubs[session.stableId] = Set(session.subagentState.activeTasks.keys)
            newTaskCtx[session.stableId] = session.subagentState.activeTasks
        }
        previousPhaseByStableId = newPhase
        previousActiveTaskIds = newSubs
        previousTaskContextByToolId = newTaskCtx
        previousWaitingIds = Set(sessions.filter { $0.phase == .waitingForInput }.map(\.stableId))
    }

    private static func subagentLine(from ctx: TaskContext) -> SubagentLine {
        let agentType = ctx.agentId ?? "agent"
        let description = String((ctx.description ?? "").prefix(60))
        let lastToolHint: String = {
            guard let last = ctx.subagentTools.last else { return "" }
            // input is [String: String] — join up to 2 key-value pairs for a compact hint
            let inputStr = last.input.prefix(2).map { "\($0.key): \($0.value)" }.joined(separator: ", ")
            let combined = "[\(last.name)] \(inputStr)"
            return String(combined.prefix(80))
        }()
        return SubagentLine(agentType: agentType, description: description, lastToolHint: lastToolHint)
    }

    private func resolveSummary(for session: SessionState) -> String {
        if session.codexTranscriptPath == nil {
            // Claude session — no transcriptPath helper; use conversationInfo.lastMessage
            return session.conversationInfo.lastMessage ?? ""
        }
        // Codex session — attempt async transcript parse, return fast fallback immediately
        let fallback = session.conversationInfo.lastMessage ?? ""
        let stableId = session.stableId
        let projectName = session.projectName
        let path = session.codexTranscriptPath!
        Task { [weak self] in
            let full = await CodexChatHistoryParser.shared.lastAssistantMessage(transcriptPath: path) ?? ""
            let clean = SummaryExtraction.extract(full)
            guard !clean.isEmpty else { return }
            await MainActor.run { [weak self] in
                guard let self else { return }
                if self.state.front?.stableId == stableId
                    || self.state.pending.contains(where: { $0.stableId == stableId }) {
                    self.state.enqueue(CompletionEntry(
                        stableId: stableId, projectName: projectName,
                        variant: .claudeStop(summary: clean)
                    ))
                }
            }
        }
        return fallback
    }

    private func popTimePredicateHolds(for entry: CompletionEntry) -> Bool {
        guard let s = lastKnownSessions[entry.stableId] else { return false }
        switch entry.variant {
        case .claudeStop:     return s.phase == .waitingForInput
        case .subagentDone:   return true
        case .pendingTool:    if case .waitingForApproval = s.phase { return true }; return false
        }
    }

    private func restartTimer() {
        autoDismissTask?.cancel()
        guard let front = state.front else { return }
        guard state.isPanelVisible, state.sendError == nil else { return }
        guard let seconds = front.variant.autoDismissSeconds else { return }

        let token = state.timerToken
        autoDismissTask = Task { @MainActor [weak self] in
            try? await Task.sleep(nanoseconds: UInt64(seconds * 1_000_000_000))
            guard let self, !Task.isCancelled, self.state.timerToken == token else { return }
            if let f = self.state.front { self.dismissFront(stableId: f.stableId) }
        }
    }
}
