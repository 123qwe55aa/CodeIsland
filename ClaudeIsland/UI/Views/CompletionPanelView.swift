//
//  CompletionPanelView.swift
//  ClaudeIsland
//
//  Variant router for the Completion Panel. Spec §5.6.
//

import SwiftUI

struct CompletionPanelView: View {
    let entry: CompletionEntry

    var body: some View {
        switch entry.variant {
        case .claudeStop(let summary):
            ClaudeStopVariantView(entry: entry, summary: summary)
        case .subagentDone(let subagents):
            SubagentDoneVariantView(entry: entry, subagents: subagents)
        case .pendingTool(let request):
            PendingToolVariantView(entry: entry, request: request)
        }
    }
}
