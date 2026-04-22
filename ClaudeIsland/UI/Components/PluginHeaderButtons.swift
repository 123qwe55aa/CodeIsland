//
//  PluginHeaderButtons.swift
//  ClaudeIsland
//
//  Native SwiftUI buttons for loaded plugins in the instances header.
//  Each plugin gets an icon button based on its `icon` property.
//  Hover: fluorescent pink, scale up, hand cursor.
//

import SwiftUI

struct PluginHeaderButtons: View {
    let viewModel: NotchViewModel
    @ObservedObject private var manager = NativePluginManager.shared
    @ObservedObject private var notchStore: NotchCustomizationStore = .shared
    @State private var showOverflow = false

    private let maxVisible = 4

    private var visiblePlugins: [NativePluginManager.LoadedPlugin] {
        Array(manager.loadedPlugins.prefix(maxVisible))
    }

    private var overflowPlugins: [NativePluginManager.LoadedPlugin] {
        Array(manager.loadedPlugins.dropFirst(maxVisible))
    }

    private var theme: ThemeResolver { ThemeResolver(theme: notchStore.customization.theme) }

    var body: some View {
        // Visible icons
        ForEach(visiblePlugins) { plugin in
            PluginHeaderButton(plugin: plugin, viewModel: viewModel)
        }

        // Overflow "..." button when >4 plugins
        if !overflowPlugins.isEmpty {
            HeaderIconButton(icon: "ellipsis", hoverColor: theme.workingColor) {
                showOverflow.toggle()
            }
            .popover(isPresented: $showOverflow, attachmentAnchor: .rect(.bounds), arrowEdge: .trailing) {
                VStack(spacing: 4) {
                    ForEach(overflowPlugins) { plugin in
                        Button {
                            showOverflow = false
                            viewModel.showPlugin(plugin.id)
                        } label: {
                            HStack(spacing: 8) {
                                Image(systemName: plugin.icon)
                                    .font(.system(size: 11))
                                    .frame(width: 16)
                                Text(plugin.name)
                                    .font(.system(size: 11, weight: .medium))
                                Spacer()
                            }
                            .foregroundColor(theme.primaryText.opacity(0.8))
                            .padding(.horizontal, 10)
                            .padding(.vertical, 6)
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                    }
                }
                .padding(6)
                .frame(minWidth: 140)
                .background(theme.overlay)
            }
        }
    }
}

private struct PluginHeaderButton: View {
    let plugin: NativePluginManager.LoadedPlugin
    let viewModel: NotchViewModel
    @ObservedObject private var notchStore: NotchCustomizationStore = .shared

    private var theme: ThemeResolver { ThemeResolver(theme: notchStore.customization.theme) }

    var body: some View {
        HeaderIconButton(icon: plugin.icon, hoverColor: theme.needsYouColor) {
            viewModel.showPlugin(plugin.id)
        }
    }
}

/// Reusable header icon button with hover effects.
/// Used for both plugin buttons and the settings gear.
struct HeaderIconButton: View {
    let icon: String
    var hoverColor: Color? = nil
    let action: () -> Void
    @ObservedObject private var notchStore: NotchCustomizationStore = .shared
    @State private var isHovered = false

    private var theme: ThemeResolver { ThemeResolver(theme: notchStore.customization.theme) }

    var body: some View {
        Button(action: action) {
            Image(systemName: icon)
                .font(.system(size: 11))
                .foregroundColor(isHovered ? (hoverColor ?? theme.workingColor) : theme.secondaryText.opacity(0.7))
                .scaleEffect(isHovered ? 1.2 : 1.0)
                .animation(.easeOut(duration: 0.12), value: isHovered)
                .frame(width: 28, height: 28)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { hovering in
            isHovered = hovering
            if hovering {
                NSCursor.pointingHand.set()
            } else {
                NSCursor.arrow.set()
            }
        }
    }
}
