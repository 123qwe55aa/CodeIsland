# CodeIsland Plugin Platform Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an open plugin platform for CodeIsland that supports theme, buddy, and sound plugins — loaded from `~/.config/codeisland/plugins/`, with a registry and store UI.

**Architecture:** Declarative-only plugins (JSON + media files). Runtime registries replace compile-time enums. Plugin template repo with CLAUDE.md enables AI-driven plugin development. GitHub-based registry with Stripe payments for monetization.

**Tech Stack:** Swift/SwiftUI, AVAudioPlayer (plugin sounds), JSON Schema validation, GitHub Actions (registry CI)

**Spec:** `docs/superpowers/specs/2026-04-10-plugin-platform-design.md`

---

## File Structure

### New files to create:

| File | Responsibility |
|------|---------------|
| `ClaudeIsland/Models/PluginManifest.swift` | Plugin JSON types (PluginManifest, ThemeManifest, BuddyManifest, SoundManifest) |
| `ClaudeIsland/Models/ThemeDefinition.swift` | ThemeDefinition struct + built-in themes as ThemeDefinition |
| `ClaudeIsland/Models/BuddyDefinition.swift` | BuddyDefinition + FrameData structs |
| `ClaudeIsland/Services/Plugin/PluginManager.swift` | Scans ~/.config/codeisland/plugins/, loads manifests, manages install/uninstall |
| `ClaudeIsland/Services/Plugin/ThemeRegistry.swift` | Runtime theme registry (replaces NotchThemeID enum routing) |
| `ClaudeIsland/Services/Plugin/BuddyRegistry.swift` | Runtime buddy registry |
| `ClaudeIsland/Services/Plugin/PluginSoundManager.swift` | AVAudioPlayer-based plugin sound playback |
| `ClaudeIsland/Services/Plugin/PluginDownloader.swift` | Fetches registry.json, downloads plugin packages |
| `ClaudeIsland/Services/Plugin/LicenseManager.swift` | License key storage and validation |
| `ClaudeIsland/UI/Views/PluginStoreView.swift` | Plugin Store tab in SystemSettingsView |
| `ClaudeIsland/UI/Components/PluginBuddyView.swift` | Canvas renderer for plugin buddy bitmaps |

### Files to modify:

| File | Change |
|------|--------|
| `ClaudeIsland/Models/NotchCustomization.swift` | `theme: NotchThemeID` → `theme: String`, remove NotchThemeID enum |
| `ClaudeIsland/Models/NotchTheme.swift` | `NotchPalette.for(_:)` → delegates to ThemeRegistry |
| `ClaudeIsland/Services/State/NotchCustomizationStore.swift` | Add `buddyId: String` and `notificationSoundPlugin: String?` to NotchCustomization |
| `ClaudeIsland/UI/Components/PixelCharacterView.swift` | Read activeBuddyId, branch between built-in and plugin |
| `ClaudeIsland/Core/SoundManager.swift` | Rename to SynthSoundEngine, integrate with PluginSoundManager priority |
| `ClaudeIsland/UI/Views/SystemSettingsView.swift` | Add `plugins` case to SettingsTab, wire PluginStoreView |
| `ClaudeIsland/App/AppDelegate.swift` | Initialize PluginManager on launch |

---

## Chunk 1: Plugin Data Models + Theme Migration

### Task 1: Plugin manifest types

**Files:**
- Create: `ClaudeIsland/Models/PluginManifest.swift`

- [ ] **Step 1: Create PluginManifest.swift with all manifest types**

```swift
// ClaudeIsland/Models/PluginManifest.swift
import Foundation

/// The type field in plugin.json
enum PluginType: String, Codable {
    case theme, buddy, sound
}

/// Shared fields across all plugin.json files
struct PluginManifest: Codable, Identifiable {
    let type: PluginType
    let id: String
    let name: String
    let version: String
    let minAppVersion: String?
    let author: PluginAuthor
    let price: Int          // cents, 0 = free
    let description: String?
    let tags: [String]?
    let preview: String?    // filename relative to plugin dir
}

struct PluginAuthor: Codable {
    let name: String
    let url: String?
    let github: String?
}

/// Theme-specific manifest (palette colors as hex strings)
struct ThemeManifest: Codable {
    let type: PluginType
    let id: String
    let name: String
    let version: String
    let author: PluginAuthor
    let price: Int
    let palette: PaletteManifest
    let preview: String?
}

struct PaletteManifest: Codable {
    let bg: String          // hex e.g. "#0A1628"
    let fg: String
    let secondaryFg: String
}

/// Buddy-specific manifest
struct BuddyManifest: Codable {
    let type: PluginType
    let id: String
    let name: String
    let version: String
    let author: PluginAuthor
    let price: Int
    let grid: GridSpec
    let palette: [String]   // indexed color palette, max 8 hex colors
    let frames: [String: [FrameManifest]]  // animationState -> frames
    let preview: String?
}

struct GridSpec: Codable {
    let width: Int
    let height: Int
    let cellSize: Int
}

struct FrameManifest: Codable {
    let duration: Int       // ms
    let pixels: String      // base64 encoded 4-bit indexed bitmap
}

/// Sound-specific manifest
struct SoundManifest: Codable {
    let type: PluginType
    let id: String
    let name: String
    let version: String
    let author: PluginAuthor
    let price: Int
    let category: SoundCategory
    let sounds: [String: SoundFileEntry]  // event key -> file info
    let preview: String?
}

enum SoundCategory: String, Codable {
    case music, notification, ambient
}

struct SoundFileEntry: Codable {
    let file: String
    let loop: Bool?
    let volume: Float?
}
```

- [ ] **Step 2: Verify it compiles**

Run: `xcodebuild -scheme ClaudeIsland -configuration Debug build 2>&1 | tail -3`
Expected: BUILD SUCCEEDED

- [ ] **Step 3: Commit**

```bash
git add ClaudeIsland/Models/PluginManifest.swift
git commit -m "feat(plugins): add plugin manifest types for theme/buddy/sound"
```

---

### Task 2: ThemeDefinition and ThemeRegistry

**Files:**
- Create: `ClaudeIsland/Models/ThemeDefinition.swift`
- Create: `ClaudeIsland/Services/Plugin/ThemeRegistry.swift`

- [ ] **Step 1: Create ThemeDefinition.swift**

```swift
// ClaudeIsland/Models/ThemeDefinition.swift
import SwiftUI

/// A theme definition that can come from built-in code or a plugin JSON.
struct ThemeDefinition: Identifiable, Equatable {
    let id: String          // must match old NotchThemeID.rawValue for built-ins
    let name: String
    let palette: NotchPalette
    let isBuiltIn: Bool

    /// Built-in themes — IDs match old NotchThemeID.rawValue exactly for persistence compat.
    static let builtIns: [ThemeDefinition] = [
        ThemeDefinition(id: "classic", name: "Classic", palette: NotchPalette(
            bg: .black, fg: .white, secondaryFg: Color(white: 1, opacity: 0.4)
        ), isBuiltIn: true),
        ThemeDefinition(id: "paper", name: "Paper", palette: NotchPalette(
            bg: .white, fg: .black, secondaryFg: Color(white: 0, opacity: 0.55)
        ), isBuiltIn: true),
        // neonLime, cyber, mint, sunset — copy exact values from current NotchTheme.swift
        // (will fill in during implementation from NotchPalette.for(_:) switch cases)
    ]
}
```

Note to implementer: copy all 6 palette definitions from `NotchTheme.swift:31-67` into `ThemeDefinition.builtIns`.

- [ ] **Step 2: Create ThemeRegistry.swift**

```swift
// ClaudeIsland/Services/Plugin/ThemeRegistry.swift
import SwiftUI

@MainActor
final class ThemeRegistry: ObservableObject {
    static let shared = ThemeRegistry()

    @Published private(set) var themes: [ThemeDefinition] = []

    init() {
        themes = ThemeDefinition.builtIns
    }

    func register(_ theme: ThemeDefinition) {
        // Avoid duplicates
        themes.removeAll { $0.id == theme.id }
        themes.append(theme)
    }

    func unregister(_ id: String) {
        themes.removeAll { $0.id == id && !$0.isBuiltIn }
    }

    func palette(for id: String) -> NotchPalette {
        themes.first(where: { $0.id == id })?.palette
            ?? ThemeDefinition.builtIns[0].palette
    }

    func theme(for id: String) -> ThemeDefinition? {
        themes.first(where: { $0.id == id })
    }
}
```

- [ ] **Step 3: Verify it compiles**

Run: `xcodebuild -scheme ClaudeIsland -configuration Debug build 2>&1 | tail -3`

- [ ] **Step 4: Commit**

```bash
git add ClaudeIsland/Models/ThemeDefinition.swift ClaudeIsland/Services/Plugin/ThemeRegistry.swift
git commit -m "feat(plugins): add ThemeDefinition and ThemeRegistry"
```

---

### Task 3: Migrate NotchCustomization.theme from enum to String

**Files:**
- Modify: `ClaudeIsland/Models/NotchCustomization.swift` (lines 15-91)
- Modify: `ClaudeIsland/Models/NotchTheme.swift` (lines 25-69)

- [ ] **Step 1: Change NotchCustomization.theme to String**

In `NotchCustomization.swift`:
- Change `var theme: NotchThemeID` → `var theme: String`
- Update `static let initial` to use `theme: "classic"` (string)
- Update the custom `init(from decoder:)` to decode theme as String with fallback to "classic"
- Remove the `NotchThemeID` enum entirely (it's replaced by ThemeRegistry)
- Keep `FontScale` and `HardwareNotchMode` enums as-is

- [ ] **Step 2: Update NotchPalette.for(_:) to use ThemeRegistry**

In `NotchTheme.swift`, replace:
```swift
static func `for`(_ id: NotchThemeID) -> NotchPalette {
    switch id { ... }
}
```
With:
```swift
static func `for`(_ id: String) -> NotchPalette {
    ThemeRegistry.shared.palette(for: id)
}
```

Remove `NotchThemeID.displayName` extension (moved to ThemeDefinition.name).

- [ ] **Step 3: Fix all compiler errors from NotchThemeID removal**

Search project for `NotchThemeID` references and update:
- Theme picker in appearance settings → iterate `ThemeRegistry.shared.themes`
- Any `== .classic` comparisons → `== "classic"`
- `CaseIterable` usage → `ThemeRegistry.shared.themes`

Run: `grep -rn "NotchThemeID" ClaudeIsland/` to find all references.

- [ ] **Step 4: Verify it compiles and themes still work**

Run: `xcodebuild -scheme ClaudeIsland -configuration Debug build 2>&1 | tail -3`

- [ ] **Step 5: Commit**

```bash
git add ClaudeIsland/Models/NotchCustomization.swift ClaudeIsland/Models/NotchTheme.swift
git add -u  # catch all files that had NotchThemeID references
git commit -m "refactor(themes): migrate NotchThemeID enum to String-based ThemeRegistry

Built-in theme IDs match old enum rawValues for UserDefaults backward compat."
```

---

### Task 4: Add buddyId and notificationSoundPlugin to NotchCustomization

**Files:**
- Modify: `ClaudeIsland/Models/NotchCustomization.swift`

- [ ] **Step 1: Add new fields to NotchCustomization**

```swift
struct NotchCustomization: Codable, Equatable {
    var theme: String
    var fontScale: FontScale
    var showBuddy: Bool
    var showUsageBar: Bool
    var maxWidth: CGFloat
    var horizontalOffset: CGFloat
    var hardwareNotchMode: HardwareNotchMode
    var buddyId: String                      // NEW — default "pixel-cat"
    var notificationSoundPlugin: String?     // NEW — nil = use built-in synth
    var bgmPlugin: String?                   // NEW — nil = no BGM
}
```

- [ ] **Step 2: Update custom Codable init for backward compat**

In `init(from decoder:)`, decode new fields with defaults:
```swift
buddyId = (try? container.decode(String.self, forKey: .buddyId)) ?? "pixel-cat"
notificationSoundPlugin = try? container.decode(String.self, forKey: .notificationSoundPlugin)
bgmPlugin = try? container.decode(String.self, forKey: .bgmPlugin)
```

- [ ] **Step 3: Update `static let initial`**

```swift
static let initial = NotchCustomization(
    theme: "classic",
    fontScale: .default,
    showBuddy: true,
    showUsageBar: true,
    maxWidth: 700,
    horizontalOffset: 0,
    hardwareNotchMode: .auto,
    buddyId: "pixel-cat",
    notificationSoundPlugin: nil,
    bgmPlugin: nil
)
```

- [ ] **Step 4: Verify it compiles**

- [ ] **Step 5: Commit**

```bash
git add ClaudeIsland/Models/NotchCustomization.swift
git commit -m "feat(plugins): add buddyId and sound plugin fields to NotchCustomization"
```

---

## Chunk 2: BuddyRegistry + PluginBuddyView

### Task 5: BuddyRegistry

**Files:**
- Create: `ClaudeIsland/Services/Plugin/BuddyRegistry.swift`

- [ ] **Step 1: Create BuddyRegistry.swift**

```swift
// ClaudeIsland/Services/Plugin/BuddyRegistry.swift
import Foundation

struct BuddyDefinition: Identifiable, Equatable {
    let id: String
    let name: String
    let grid: GridSpec
    let palette: [String]               // hex colors
    let frames: [String: [FrameData]]   // animationState -> frames
    let isBuiltIn: Bool

    static let builtInCat = BuddyDefinition(
        id: "pixel-cat",
        name: "Pixel Cat",
        grid: GridSpec(width: 13, height: 11, cellSize: 4),
        palette: [],
        frames: [:],    // built-in uses procedural rendering, not frames
        isBuiltIn: true
    )
}

struct FrameData: Equatable {
    let duration: Int       // ms
    let pixels: Data        // decoded from base64, 4-bit indexed
}

@MainActor
final class BuddyRegistry: ObservableObject {
    static let shared = BuddyRegistry()

    @Published private(set) var buddies: [BuddyDefinition] = []

    init() {
        buddies = [BuddyDefinition.builtInCat]
    }

    func register(_ buddy: BuddyDefinition) {
        buddies.removeAll { $0.id == buddy.id }
        buddies.append(buddy)
    }

    func unregister(_ id: String) {
        buddies.removeAll { $0.id == id && !$0.isBuiltIn }
    }

    func definition(for id: String) -> BuddyDefinition? {
        buddies.first(where: { $0.id == id })
    }
}
```

- [ ] **Step 2: Verify compiles, commit**

---

### Task 6: PluginBuddyView (bitmap renderer)

**Files:**
- Create: `ClaudeIsland/UI/Components/PluginBuddyView.swift`

- [ ] **Step 1: Create PluginBuddyView.swift**

A Canvas-based SwiftUI view that renders FrameData bitmaps. Uses TimelineView for frame animation.

```swift
// ClaudeIsland/UI/Components/PluginBuddyView.swift
import SwiftUI

/// Renders plugin buddy characters from indexed bitmap frame data.
struct PluginBuddyView: View {
    let definition: BuddyDefinition
    let state: AnimationState
    @State private var frameIndex = 0

    private var currentFrames: [FrameData] {
        let key = "\(state)"  // idle, working, etc.
        return definition.frames[key] ?? definition.frames["idle"] ?? []
    }

    var body: some View {
        TimelineView(.animation(minimumInterval: 0.1)) { timeline in
            Canvas { context, size in
                guard !currentFrames.isEmpty else { return }
                let frame = currentFrames[frameIndex % currentFrames.count]
                drawFrame(context: &context, frame: frame, size: size)
            }
            .frame(
                width: CGFloat(definition.grid.width * definition.grid.cellSize),
                height: CGFloat(definition.grid.height * definition.grid.cellSize)
            )
            .onChange(of: timeline.date) { _, _ in
                advanceFrame()
            }
        }
    }

    private func drawFrame(context: inout GraphicsContext, frame: FrameData, size: CGSize) {
        let cellSize = CGFloat(definition.grid.cellSize)
        let width = definition.grid.width
        let colors = definition.palette.compactMap { Color(hex: $0) }

        for y in 0..<definition.grid.height {
            for x in 0..<width {
                let pixelIndex = y * width + x
                let byteIndex = pixelIndex / 2
                guard byteIndex < frame.pixels.count else { continue }
                let byte = frame.pixels[byteIndex]
                let colorIndex: UInt8 = (pixelIndex % 2 == 0)
                    ? (byte >> 4) & 0x0F
                    : byte & 0x0F
                guard colorIndex > 0, Int(colorIndex) - 1 < colors.count else { continue }
                let color = colors[Int(colorIndex) - 1]  // 0 = transparent
                let rect = CGRect(x: CGFloat(x) * cellSize, y: CGFloat(y) * cellSize,
                                  width: cellSize, height: cellSize)
                context.fill(Path(rect), with: .color(color))
            }
        }
    }

    private func advanceFrame() {
        let frames = currentFrames
        guard !frames.isEmpty else { return }
        frameIndex = (frameIndex + 1) % frames.count
    }
}
```

- [ ] **Step 2: Add Color(hex:) extension if not present**

Check if a hex color initializer exists. If not, add:

```swift
extension Color {
    init?(hex: String) {
        var h = hex.trimmingCharacters(in: .whitespacesAndNewlines)
        if h.hasPrefix("#") { h.removeFirst() }
        guard h.count == 6, let rgb = UInt64(h, radix: 16) else { return nil }
        self.init(
            red: Double((rgb >> 16) & 0xFF) / 255,
            green: Double((rgb >> 8) & 0xFF) / 255,
            blue: Double(rgb & 0xFF) / 255
        )
    }
}
```

- [ ] **Step 3: Update PixelCharacterView call sites to branch on buddyId**

Where PixelCharacterView is used (in ClaudeInstancesView), add branching:

```swift
let buddyId = NotchCustomizationStore.shared.customization.buddyId
if buddyId == "pixel-cat" {
    PixelCharacterView(state: animState)
} else if let def = BuddyRegistry.shared.definition(for: buddyId) {
    PluginBuddyView(definition: def, state: animState)
} else {
    PixelCharacterView(state: animState)  // fallback
}
```

- [ ] **Step 4: Verify compiles, commit**

---

## Chunk 3: PluginSoundManager + SoundManager Integration

### Task 7: PluginSoundManager

**Files:**
- Create: `ClaudeIsland/Services/Plugin/PluginSoundManager.swift`

- [ ] **Step 1: Create PluginSoundManager.swift**

```swift
// ClaudeIsland/Services/Plugin/PluginSoundManager.swift
import AVFAudio
import Foundation

/// Plays plugin sound files (m4a/mp3) via AVAudioPlayer.
/// Coexists with the built-in SoundManager (synth engine).
@MainActor
final class PluginSoundManager: ObservableObject {
    static let shared = PluginSoundManager()

    @Published var activeBGMPlugin: String? = nil
    private var bgmPlayer: AVAudioPlayer?
    private var notificationPlayers: [String: AVAudioPlayer] = [:]

    /// Base directory for installed plugins
    private var pluginsDir: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".config/codeisland/plugins")
    }

    func playBGM(pluginId: String) {
        stopBGM()
        let dir = pluginsDir.appendingPathComponent("sounds/\(pluginId)")
        // Read plugin.json to find bgm file
        guard let manifest = loadSoundManifest(from: dir),
              let bgmEntry = manifest.sounds["bgm"],
              let player = createPlayer(dir: dir, filename: bgmEntry.file) else { return }
        player.numberOfLoops = (bgmEntry.loop ?? true) ? -1 : 0
        player.volume = bgmEntry.volume ?? 0.3
        player.play()
        bgmPlayer = player
        activeBGMPlugin = pluginId
    }

    func stopBGM() {
        bgmPlayer?.stop()
        bgmPlayer = nil
        activeBGMPlugin = nil
    }

    func playNotification(pluginId: String, event: SoundEvent) {
        let dir = pluginsDir.appendingPathComponent("sounds/\(pluginId)")
        guard let manifest = loadSoundManifest(from: dir),
              let entry = manifest.sounds[event.rawValue],
              let player = createPlayer(dir: dir, filename: entry.file) else { return }
        player.volume = entry.volume ?? 0.7
        player.play()
    }

    private func loadSoundManifest(from dir: URL) -> SoundManifest? {
        let url = dir.appendingPathComponent("plugin.json")
        guard let data = try? Data(contentsOf: url) else { return nil }
        return try? JSONDecoder().decode(SoundManifest.self, from: data)
    }

    private func createPlayer(dir: URL, filename: String) -> AVAudioPlayer? {
        let url = dir.appendingPathComponent("assets/\(filename)")
        return try? AVAudioPlayer(contentsOf: url)
    }
}
```

- [ ] **Step 2: Update SoundManager.play() to check for plugin override**

In `SoundManager.swift`, at the top of `play(_ event:)` (line ~314), add:

```swift
// If user has a plugin notification sound pack active, use that instead
if let pluginId = NotchCustomizationStore.shared.customization.notificationSoundPlugin {
    PluginSoundManager.shared.playNotification(pluginId: pluginId, event: event)
    return
}
// Otherwise fall through to built-in synth
```

- [ ] **Step 3: Verify compiles, commit**

---

## Chunk 4: PluginManager (Scanner + Loader)

### Task 8: PluginManager

**Files:**
- Create: `ClaudeIsland/Services/Plugin/PluginManager.swift`

- [ ] **Step 1: Create PluginManager.swift**

```swift
// ClaudeIsland/Services/Plugin/PluginManager.swift
import Foundation
import OSLog
import SwiftUI

/// Scans, loads, and manages installed plugins from ~/.config/codeisland/plugins/
@MainActor
final class PluginManager: ObservableObject {
    static let shared = PluginManager()
    private static let log = Logger(subsystem: "com.codeisland.app", category: "PluginManager")

    @Published private(set) var installedPlugins: [PluginManifest] = []

    private var pluginsDir: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".config/codeisland/plugins")
    }

    func loadAll() {
        ensureDirectoryExists()
        loadThemes()
        loadBuddies()
        loadSounds()
        Self.log.info("Loaded \(self.installedPlugins.count) plugins")
    }

    private func ensureDirectoryExists() {
        let fm = FileManager.default
        for sub in ["themes", "buddies", "sounds"] {
            let dir = pluginsDir.appendingPathComponent(sub)
            if !fm.fileExists(atPath: dir.path) {
                try? fm.createDirectory(at: dir, withIntermediateDirectories: true)
            }
        }
    }

    private func loadThemes() {
        let dir = pluginsDir.appendingPathComponent("themes")
        for pluginDir in subdirectories(of: dir) {
            guard let manifest = decode(ThemeManifest.self, from: pluginDir) else { continue }
            guard let palette = parsePalette(manifest.palette) else {
                Self.log.warning("Invalid palette in theme \(manifest.id)")
                continue
            }
            let def = ThemeDefinition(
                id: manifest.id,
                name: manifest.name,
                palette: palette,
                isBuiltIn: false
            )
            ThemeRegistry.shared.register(def)
            addToInstalled(from: pluginDir)
        }
    }

    private func loadBuddies() {
        let dir = pluginsDir.appendingPathComponent("buddies")
        for pluginDir in subdirectories(of: dir) {
            guard let manifest = decode(BuddyManifest.self, from: pluginDir) else { continue }
            let frames = manifest.frames.mapValues { frameManifests in
                frameManifests.compactMap { fm -> FrameData? in
                    guard let data = Data(base64Encoded: fm.pixels) else { return nil }
                    return FrameData(duration: fm.duration, pixels: data)
                }
            }
            let def = BuddyDefinition(
                id: manifest.id,
                name: manifest.name,
                grid: manifest.grid,
                palette: manifest.palette,
                frames: frames,
                isBuiltIn: false
            )
            BuddyRegistry.shared.register(def)
            addToInstalled(from: pluginDir)
        }
    }

    private func loadSounds() {
        let dir = pluginsDir.appendingPathComponent("sounds")
        for pluginDir in subdirectories(of: dir) {
            addToInstalled(from: pluginDir)
            // Sound plugins are loaded on-demand by PluginSoundManager
        }
    }

    // MARK: - Install / Uninstall

    func install(pluginDir sourceDir: URL, type: String, id: String) throws {
        let dest = pluginsDir.appendingPathComponent("\(type)s/\(id)")
        if FileManager.default.fileExists(atPath: dest.path) {
            try FileManager.default.removeItem(at: dest)
        }
        try FileManager.default.copyItem(at: sourceDir, to: dest)
        loadAll()  // reload
    }

    func uninstall(type: String, id: String) {
        let dir = pluginsDir.appendingPathComponent("\(type)s/\(id)")
        try? FileManager.default.removeItem(at: dir)

        // Revert to default if this was the active plugin
        let store = NotchCustomizationStore.shared
        if type == "theme" && store.customization.theme == id {
            store.update { $0.theme = "classic" }
        }
        if type == "buddy" && store.customization.buddyId == id {
            store.update { $0.buddyId = "pixel-cat" }
        }
        if type == "sound" && store.customization.notificationSoundPlugin == id {
            store.update { $0.notificationSoundPlugin = nil }
        }
        if type == "sound" && store.customization.bgmPlugin == id {
            store.update { $0.bgmPlugin = nil }
            PluginSoundManager.shared.stopBGM()
        }

        ThemeRegistry.shared.unregister(id)
        BuddyRegistry.shared.unregister(id)
        installedPlugins.removeAll { $0.id == id }
    }

    // MARK: - Helpers

    private func subdirectories(of dir: URL) -> [URL] {
        (try? FileManager.default.contentsOfDirectory(at: dir, includingPropertiesForKeys: [.isDirectoryKey]))?.filter {
            (try? $0.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) == true
        } ?? []
    }

    private func decode<T: Decodable>(_ type: T.Type, from dir: URL) -> T? {
        let url = dir.appendingPathComponent("plugin.json")
        guard let data = try? Data(contentsOf: url) else { return nil }
        return try? JSONDecoder().decode(type, from: data)
    }

    private func addToInstalled(from dir: URL) {
        if let manifest = decode(PluginManifest.self, from: dir) {
            installedPlugins.removeAll { $0.id == manifest.id }
            installedPlugins.append(manifest)
        }
    }

    private func parsePalette(_ p: PaletteManifest) -> NotchPalette? {
        guard let bg = Color(hex: p.bg),
              let fg = Color(hex: p.fg),
              let sec = Color(hex: p.secondaryFg) else { return nil }
        return NotchPalette(bg: bg, fg: fg, secondaryFg: sec)
    }
}
```

- [ ] **Step 2: Initialize PluginManager in AppDelegate**

In `AppDelegate.swift`, in `applicationDidFinishLaunching`, after WindowManager setup:

```swift
PluginManager.shared.loadAll()
```

- [ ] **Step 3: Verify compiles, commit**

---

## Chunk 5: Plugin Store UI

### Task 9: PluginStoreView

**Files:**
- Create: `ClaudeIsland/UI/Views/PluginStoreView.swift`
- Modify: `ClaudeIsland/UI/Views/SystemSettingsView.swift`

- [ ] **Step 1: Add `plugins` tab to SettingsTab enum**

In `SystemSettingsView.swift`, add to the SettingsTab enum (after `codelight`):

```swift
case plugins
```

Add icon: `"puzzlepiece.extension"` and label: `"Plugins"`.

Add the case to the detail dispatcher switch:

```swift
case .plugins: PluginStoreView()
```

- [ ] **Step 2: Create PluginStoreView.swift**

```swift
// ClaudeIsland/UI/Views/PluginStoreView.swift
import SwiftUI

struct PluginStoreView: View {
    @ObservedObject private var pluginManager = PluginManager.shared
    @ObservedObject private var themeRegistry = ThemeRegistry.shared
    @ObservedObject private var buddyRegistry = BuddyRegistry.shared
    @ObservedObject private var store = NotchCustomizationStore.shared

    @State private var selectedCategory = 0  // 0=themes, 1=buddies, 2=sounds

    private let categories = ["Themes", "Buddies", "Sounds"]

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            // Category picker
            Picker("", selection: $selectedCategory) {
                ForEach(0..<categories.count, id: \.self) { i in
                    Text(categories[i]).tag(i)
                }
            }
            .pickerStyle(.segmented)
            .frame(maxWidth: 300)

            switch selectedCategory {
            case 0: themesSection
            case 1: buddiesSection
            case 2: soundsSection
            default: EmptyView()
            }

            Spacer()
        }
        .padding(20)
    }

    // MARK: - Themes

    private var themesSection: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 120))], spacing: 12) {
            ForEach(themeRegistry.themes) { theme in
                themeCard(theme)
            }
        }
    }

    private func themeCard(_ theme: ThemeDefinition) -> some View {
        let isActive = store.customization.theme == theme.id
        return VStack(spacing: 6) {
            // Color preview
            RoundedRectangle(cornerRadius: 8)
                .fill(theme.palette.bg)
                .frame(height: 60)
                .overlay(
                    Text("Aa")
                        .font(.system(size: 18, weight: .bold))
                        .foregroundColor(theme.palette.fg)
                )
                .overlay(
                    RoundedRectangle(cornerRadius: 8)
                        .strokeBorder(isActive ? Color.green : Color.clear, lineWidth: 2)
                )

            Text(theme.name)
                .font(.system(size: 11, weight: .medium))
                .foregroundColor(.white.opacity(0.8))

            if isActive {
                Text("Active")
                    .font(.system(size: 9, weight: .semibold))
                    .foregroundColor(.green)
            } else {
                Button("Apply") {
                    store.update { $0.theme = theme.id }
                }
                .buttonStyle(.plain)
                .font(.system(size: 9, weight: .semibold))
                .foregroundColor(.white.opacity(0.6))
            }
        }
        .padding(8)
        .background(RoundedRectangle(cornerRadius: 10).fill(Color.white.opacity(0.05)))
    }

    // MARK: - Buddies

    private var buddiesSection: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 120))], spacing: 12) {
            ForEach(buddyRegistry.buddies) { buddy in
                buddyCard(buddy)
            }
        }
    }

    private func buddyCard(_ buddy: BuddyDefinition) -> some View {
        let isActive = store.customization.buddyId == buddy.id
        return VStack(spacing: 6) {
            if buddy.isBuiltIn {
                PixelCharacterView(state: .idle)
                    .frame(height: 60)
            } else {
                PluginBuddyView(definition: buddy, state: .idle)
                    .frame(height: 60)
            }

            Text(buddy.name)
                .font(.system(size: 11, weight: .medium))
                .foregroundColor(.white.opacity(0.8))

            if isActive {
                Text("Active")
                    .font(.system(size: 9, weight: .semibold))
                    .foregroundColor(.green)
            } else {
                Button("Apply") {
                    store.update { $0.buddyId = buddy.id }
                }
                .buttonStyle(.plain)
                .font(.system(size: 9, weight: .semibold))
                .foregroundColor(.white.opacity(0.6))
            }
        }
        .padding(8)
        .background(RoundedRectangle(cornerRadius: 10).fill(Color.white.opacity(0.05)))
    }

    // MARK: - Sounds

    private var soundsSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            let soundPlugins = pluginManager.installedPlugins.filter { $0.type == .sound }
            if soundPlugins.isEmpty {
                Text("No sound plugins installed")
                    .font(.system(size: 12))
                    .foregroundColor(.white.opacity(0.4))
            } else {
                ForEach(soundPlugins) { plugin in
                    soundRow(plugin)
                }
            }
        }
    }

    private func soundRow(_ plugin: PluginManifest) -> some View {
        HStack {
            Image(systemName: "music.note")
                .foregroundColor(.white.opacity(0.6))
            Text(plugin.name)
                .font(.system(size: 12, weight: .medium))
                .foregroundColor(.white.opacity(0.8))
            Spacer()
            // BGM toggle etc.
        }
        .padding(8)
        .background(RoundedRectangle(cornerRadius: 8).fill(Color.white.opacity(0.05)))
    }
}
```

- [ ] **Step 3: Verify compiles, commit**

---

## Chunk 6: Plugin Downloader + Registry Integration

### Task 10: PluginDownloader

**Files:**
- Create: `ClaudeIsland/Services/Plugin/PluginDownloader.swift`

- [ ] **Step 1: Create PluginDownloader.swift**

```swift
// ClaudeIsland/Services/Plugin/PluginDownloader.swift
import Foundation
import OSLog

/// Fetches the plugin registry and downloads plugin packages.
@MainActor
final class PluginDownloader: ObservableObject {
    static let shared = PluginDownloader()
    private static let log = Logger(subsystem: "com.codeisland.app", category: "PluginDownloader")

    private let registryURL = URL(string: "https://raw.githubusercontent.com/IsleOS/codeisland-plugin-registry/main/registry.json")!

    @Published private(set) var availablePlugins: [RegistryEntry] = []
    @Published private(set) var isLoading = false

    struct RegistryEntry: Codable, Identifiable {
        let id: String
        let type: PluginType
        let name: String
        let version: String
        let author: String
        let price: Int
        let description: String?
        let tags: [String]?
        let downloadUrl: String
        let previewUrl: String?
    }

    struct RegistryResponse: Codable {
        let version: Int
        let updatedAt: String
        let plugins: [RegistryEntry]
    }

    func fetchRegistry() async {
        isLoading = true
        defer { isLoading = false }

        do {
            let (data, _) = try await URLSession.shared.data(from: registryURL)
            let registry = try JSONDecoder().decode(RegistryResponse.self, from: data)
            availablePlugins = registry.plugins
            Self.log.info("Fetched \(registry.plugins.count) plugins from registry")
        } catch {
            Self.log.error("Failed to fetch registry: \(error)")
        }
    }

    func download(_ entry: RegistryEntry) async throws {
        guard let baseURL = URL(string: entry.downloadUrl) else { return }
        let pluginJsonURL = baseURL.appendingPathComponent("plugin.json")

        // Download plugin.json
        let (jsonData, _) = try await URLSession.shared.data(from: pluginJsonURL)

        // Create temp dir, save plugin.json
        let tmpDir = FileManager.default.temporaryDirectory
            .appendingPathComponent("codeisland-plugin-\(entry.id)")
        try? FileManager.default.removeItem(at: tmpDir)
        try FileManager.default.createDirectory(at: tmpDir, withIntermediateDirectories: true)
        try jsonData.write(to: tmpDir.appendingPathComponent("plugin.json"))

        // Download preview if exists
        if let previewUrl = entry.previewUrl, let url = URL(string: previewUrl) {
            let (previewData, _) = try await URLSession.shared.data(from: url)
            let filename = url.lastPathComponent
            try previewData.write(to: tmpDir.appendingPathComponent(filename))
        }

        // Install
        let typeDir = entry.type == .theme ? "theme" : entry.type == .buddy ? "buddie" : "sound"
        try PluginManager.shared.install(pluginDir: tmpDir, type: typeDir, id: entry.id)

        // Cleanup
        try? FileManager.default.removeItem(at: tmpDir)
    }
}
```

- [ ] **Step 2: Add "Available" section to PluginStoreView**

Add a section in PluginStoreView that shows available-but-not-installed plugins from the registry. Add a [Download] button for free plugins and [Buy] button for paid ones.

- [ ] **Step 3: Add refresh on appear**

```swift
.task {
    await PluginDownloader.shared.fetchRegistry()
}
```

- [ ] **Step 4: Verify compiles, commit**

---

## Chunk 7: LicenseManager + URL Scheme

### Task 11: LicenseManager

**Files:**
- Create: `ClaudeIsland/Services/Plugin/LicenseManager.swift`

- [ ] **Step 1: Create LicenseManager.swift**

```swift
// ClaudeIsland/Services/Plugin/LicenseManager.swift
import Foundation
import IOKit

@MainActor
final class LicenseManager: ObservableObject {
    static let shared = LicenseManager()

    @Published private(set) var licenses: [String: LicenseEntry] = [:]  // pluginId -> license

    struct LicenseEntry: Codable {
        let key: String
        let pluginId: String
        let activatedAt: Date
        let expiresAt: Date?    // nil = perpetual
    }

    private var licensesFile: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".config/codeisland/licenses.json")
    }

    init() {
        load()
    }

    func isLicensed(_ pluginId: String) -> Bool {
        guard let entry = licenses[pluginId] else { return false }
        if let exp = entry.expiresAt, exp < Date() { return false }
        return true
    }

    func activate(key: String, pluginId: String) {
        // TODO: server validation in Phase 4
        let entry = LicenseEntry(key: key, pluginId: pluginId, activatedAt: Date(), expiresAt: nil)
        licenses[pluginId] = entry
        save()
    }

    private func load() {
        guard let data = try? Data(contentsOf: licensesFile),
              let decoded = try? JSONDecoder().decode([String: LicenseEntry].self, from: data) else { return }
        licenses = decoded
    }

    private func save() {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        guard let data = try? encoder.encode(licenses) else { return }
        try? data.write(to: licensesFile, options: .atomic)
    }
}
```

- [ ] **Step 2: Register `codeisland://` URL scheme**

In Info.plist or Xcode target settings, add URL scheme `codeisland`.

In AppDelegate, handle:

```swift
func application(_ application: NSApplication, open urls: [URL]) {
    for url in urls {
        if url.scheme == "codeisland", url.host == "license",
           let components = URLComponents(url: url, resolvingAgainstBaseURL: false),
           let key = components.queryItems?.first(where: { $0.name == "key" })?.value,
           let pluginId = components.queryItems?.first(where: { $0.name == "plugin" })?.value {
            LicenseManager.shared.activate(key: key, pluginId: pluginId)
        }
    }
}
```

- [ ] **Step 3: Verify compiles, commit**

---

## Chunk 8: Plugin Template Repo

### Task 12: Create codeisland-plugin-template repository

This is a separate GitHub repo, not code in CodeIsland.

**Files (in new repo):**
- Create: `CLAUDE.md`
- Create: `AGENTS.md` (copy of CLAUDE.md)
- Create: `README.md`
- Create: `schemas/theme.schema.json`
- Create: `schemas/buddy.schema.json`
- Create: `schemas/sound.schema.json`
- Create: `examples/theme-example/plugin.json`
- Create: `examples/buddy-example/plugin.json`
- Create: `examples/sound-example/plugin.json`
- Create: `tools/validate.sh`

- [ ] **Step 1: Create the GitHub repo `IsleOS/codeisland-plugin-template`**

- [ ] **Step 2: Write CLAUDE.md** — the core AI-readable spec. Include:
  - Full JSON schemas inline for each plugin type
  - All constraints (grid size, color count, file size limits, animation states)
  - Examples for each type
  - Common errors section
  - Validation command

- [ ] **Step 3: Write JSON Schema files** for automated validation

- [ ] **Step 4: Create example plugins** — one per type, minimal but valid

- [ ] **Step 5: Write validate.sh** — checks JSON schema, file existence, image/audio sizes

- [ ] **Step 6: Commit and push**

---

## Chunk 9: Plugin Registry Repo + CI

### Task 13: Create codeisland-plugin-registry repository

- [ ] **Step 1: Create `IsleOS/codeisland-plugin-registry` repo**

- [ ] **Step 2: Set up directory structure**

```
plugins/
  themes/
  buddies/
  sounds/
registry.json
.github/workflows/
  validate-pr.yml
  build-registry.yml
CONTRIBUTING.md
```

- [ ] **Step 3: Write validate-pr.yml** — GitHub Action that runs on PR:
  - Checks plugin.json against schema
  - Verifies required files exist
  - Checks file size limits
  - Comments results on PR

- [ ] **Step 4: Write build-registry.yml** — runs on merge to main:
  - Scans all plugins/ directories
  - Generates registry.json with download URLs
  - Commits registry.json

- [ ] **Step 5: Seed with 2-3 example plugins** (the ones from the template repo)

- [ ] **Step 6: Commit and push**

---

## Execution Order Summary

| Phase | Tasks | Deliverable |
|-------|-------|-------------|
| Phase 1 | Tasks 1-4 | Plugin models + theme migration |
| Phase 2 | Tasks 5-6 | Buddy registry + renderer |
| Phase 3 | Task 7 | Sound plugin support |
| Phase 4 | Task 8 | Plugin scanner/loader |
| Phase 5 | Task 9 | Plugin Store UI |
| Phase 6 | Task 10 | Registry download |
| Phase 7 | Task 11 | Licensing + URL scheme |
| Phase 8 | Tasks 12-13 | Template + registry repos |

Tasks 1-9 are in the CodeIsland repo. Tasks 12-13 are separate repos.
Each task is independently committable and testable.
