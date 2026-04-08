# CodeIsland Notch Customization — Design Spec

**Date:** 2026-04-08
**Status:** Draft (pending review)
**Target version:** v1.10.0
**Author:** Brainstorming session with project owner

## 1. Background

CodeIsland today renders a fixed black-on-white notch overlay locked to
the MacBook Pro hardware notch. All colors, fonts, notch dimensions, and
buddy/usage-bar visibility are hardcoded. Users cannot customize any
appearance or layout aspect of the notch, and the idle-state notch is
always as wide as its maximum expanded state — leaving large empty
space in the middle of the menu bar even when there is almost nothing
to show.

This spec defines a set of seven user-facing customization features and
the supporting architecture to deliver them in v1.10.0 as a single
release.

## 2. Goals

1. Let the user hide the buddy (pet) indicator via a setting.
2. Let the user hide the usage-bar (rate-limit %) indicator via a
   setting.
3. Let the user resize the notch via an in-place live edit mode on the
   notch body itself, covering both MacBooks with and without a
   hardware notch.
4. Let the user slide the notch horizontally along the top edge of the
   screen (not free-floating).
5. Let the user pick a theme from six built-in presets, with smooth
   color transitions on switch.
6. Make the notch auto-shrink to fit its content at idle and expand up
   to a user-configured maximum width when content grows.
7. Let the user scale all notch fonts via a four-step size picker.

## 3. Non-goals

- Fully free-floating notch positioning (rejected: breaks the notch's
  visual identity; hardware notch on the Mac remains regardless).
- User-defined custom themes with color pickers (rejected this round:
  six curated presets cover the intent; a future iteration can add a
  custom palette editor without breaking the current architecture).
- Vertical resizing of the notch (rejected: height is a visual
  signature; hardware notch height is fixed at ~37pt).
- Undo/redo history beyond a single Cancel-to-origin rollback in live
  edit mode.
- Refactoring `@AppStorage` keys unrelated to the notch (notifications,
  CodeLight, behavior tabs stay untouched).
- Changing the notarization / release pipeline.

## 4. User-facing design

### 4.1 Settings surface

A new "Notch" section is added inside the existing **Appearance** tab
of `SystemSettingsView`. No new top-level tab.

```
Appearance Tab
  ...existing controls...

  ─── Notch ───

  Theme              [ Classic       ▾ ]      ← 6 presets, mini swatch in each row
  Font Size          [ S | M | L | XL ]       ← Segmented picker
  Show Buddy         [   ]                    ← Toggle
  Show Usage Bar     [   ]                    ← Toggle
  Hardware Notch     [ Auto          ▾ ]      ← Auto | Force Virtual (2 cases)
  [ Customize Size & Position… ]              ← Big button → enter live edit mode
```

### 4.2 Live edit mode

A one-shot interaction that takes over the notch itself to let the user
resize, reposition, and preview the geometry. Entered from the
Customize button in Settings.

#### Window model

Live edit mode adds a **new auxiliary `NSPanel` subclass**,
`NotchLiveEditPanel`, separate from `NotchPanel`. Its purpose:

- Hosts the floating edit controls (arrow buttons, Notch Preset, Drag
  Mode, Save, Cancel).
- Because controls are clickable, the panel must become key.
  `styleMask = [.borderless, .nonactivatingPanel]`,
  `isMovableByWindowBackground = false`, `canBecomeKey = true`,
  `collectionBehavior = [.canJoinAllSpaces, .stationary, .fullScreenAuxiliary]`.
- Frame: the panel is sized to the full screen width (so the arrow
  buttons can live outside the notch's narrow bounds) and positioned
  flush with the top of the active screen. Its height covers the
  notch area plus the space for the controls beneath (~160pt total).
- **Menu-bar pass-through.** Because the panel's frame overlaps the
  macOS menu bar region (Apple menu, app menus, Control Center, status
  items), clicks outside the edit controls MUST reach the system. The
  panel sets `ignoresMouseEvents = false` so its own controls accept
  clicks, and its `contentView` is an `NSView` subclass that overrides
  `hitTest(_:)`:
  ```swift
  override func hitTest(_ point: NSPoint) -> NSView? {
      // Walk subviews: if the point hits a control view, return it;
      // otherwise return nil so the click falls through to whatever
      // is beneath the panel (menu bar, desktop, etc.)
      for sub in subviews where sub.frame.contains(point) {
          if let target = sub.hitTest(convert(point, to: sub)) { return target }
      }
      return nil
  }
  ```
  This is the correct AppKit idiom for a full-screen-wide transparent
  overlay. The `ignoresMouseEvents` flag is a **window** property; the
  per-subview pass-through is implemented via `hitTest` on
  `contentView`.
- Created by `NotchWindowController.enterLiveEditMode()`, torn down by
  `exitLiveEditMode()`. Lifetime is strictly scoped to `store.isEditing`.
- `NotchPanel` itself stays non-key (`canBecomeKey = false`) and
  unchanged — the notch content is still drawn by `NotchView`, but the
  overlay window above it catches the clicks on controls.

While in edit mode:

- The notch (inside `NotchPanel`) shows **simulated Claude content**
  driven by `NotchLiveEditSimulator` (see timing below).
- A **dashed border** and a **soft neon-green breathing gradient**
  surround the notch (implemented inside `NotchView`, conditioned on
  `store.isEditing`).
- The `SystemSettingsWindow` is minimized/hidden so the user can see
  the real notch. On Save or Cancel, the Settings window is re-shown.

#### Simulated content rotation

Driven by `TimelineView(.periodic(from: .now, by: 2))` scoped to
`NotchLiveEditSimulator`. Lifecycle rules:

1. Timeline runs only while `store.isEditing == true`. Leaving live
   edit mode ends the timeline automatically via view lifetime.
2. **Rotation pauses during an active resize or drag gesture.** While
   the user is mid-gesture, the simulator freezes on the current
   message so the notch width changes in response to user input, not
   in response to auto-rotation. Implementation: the timeline's
   `context.date` is gated through a `@State var isInteracting: Bool`.
3. Rotation resumes 0.8s after the last gesture ends (de-bounce).
4. Messages rotate through 5 fixtures: empty / short / medium / long /
   long-with-wrap. See `NotchLiveEditSimulator.fixtures`.

#### Control layout

The auxiliary panel hosts the following controls, positioned relative
to the notch frame:

```
               ┌─────────────────────────────┐
               │   [simulated Claude text]   │
               └─────────────────────────────┘
          ◀                                         ▶       ← Neon green arrow buttons (resize)

                [⊙ Notch Preset]  [✋ Drag Mode]              ← Action buttons

                     [ Save ]    [ Cancel ]                  ← Neon green / neon pink
```

Interactions:

- **Arrow buttons (◀ ▶):** one click = symmetric (mirror) resize by
  2pt. `⌘+click` = 10pt. `⌥+click` = 1pt. Resize always shrinks/grows
  the notch around its current center.
- **Drag on the left/right edge of the notch:** continuous mirror
  resize, equivalent to the arrow buttons.
- **Notch Preset button:** sets `maxWidth = hardwareNotchWidth + 20pt`
  (with small breathing room), where `hardwareNotchWidth` is read from
  `NSScreen.main?.safeAreaInsets` (the usable-area rectangle excludes
  the notch, so `screen.frame.width - safeAreaInsets.left - safeAreaInsets.right`
  yields the notch width). Also flashes a dashed width marker in the
  `NotchLiveEditPanel`, positioned 8pt below the notch frame,
  centered horizontally, with a concrete fade animation: opacity
  `0 → 1` over 0.2s (.easeIn), hold 1.6s, `1 → 0` over 0.2s
  (.easeOut). Total visible time: 2s. **Enabled iff effective
  `hasHardwareNotch == true`**
  (i.e., whenever a real hardware notch is detected *and* the user has
  not overridden with `.forceVirtual`). Otherwise disabled with help
  tooltip: *"Your device doesn't have a hardware notch"*. This rule
  holds regardless of how the mode was selected.
- **Drag Mode button:** toggles the edit sub-mode between `.resize`
  (default) and `.drag`. On each toggle, the entire notch flashes once:
  opacity animates `1.0 → 0.4 → 1.0` over 0.3s total with
  `.easeInOut`. While in `.drag`, dragging the notch moves it
  **horizontally only** along the top edge of the screen — y is
  locked to the top. Click Drag Mode again to return to `.resize`.
- **Save (neon green):** commits all changes made during the edit
  session via `store.commitEdit()`, tears down the overlay, restores
  the Settings window. **Works in both `.resize` and `.drag`
  sub-modes** — the sub-mode is transient and does not gate Save.
- **Cancel (neon pink):** rolls back all changes to the snapshot taken
  at `enterEditMode()` via `store.cancelEdit()`, tears down the
  overlay, restores the Settings window. **Works in both sub-modes.**
  `editSubMode` is transient state owned by `NotchLiveEditOverlay`; it
  is not persisted and dies with the overlay — cancelling while in
  `.drag` fully exits live edit and restores the pre-edit snapshot,
  including rolling back any horizontal offset changes.

#### Edit sub-mode state machine

```
         enterEditMode()              commitEdit() / cancelEdit()
  (idle) ─────────────▶ .resize ─┐ ────────────────────────▶ (idle)
                           ▲     │
                           │     ▼
                 [Drag Mode button] ⇆ .drag
```

- `editSubMode` is local state inside `NotchLiveEditOverlay` (SwiftUI
  `@State`).
- All transitions flash the notch (`.resize ↔ .drag`) or play the save
  / cancel teardown animation.
- Save and Cancel are valid from any sub-mode — the state diagram
  above only draws them from `.resize` for legibility, but both
  transitions are equally valid from `.drag`.

### 4.3 Runtime auto-width behavior

At runtime, the notch width is computed every frame as:

```
clampedWidth = max(minIdleWidth,
                   min(desiredContentWidth, store.customization.maxWidth))
```

- `minIdleWidth = 140pt` — a hard floor chosen to guarantee that the
  notch never becomes narrower than "pet icon + 3-char status label
  + 1-tiny-indicator" at the default font scale. This is smaller than
  any realistic idle content, so the clamp effectively lets the notch
  shrink tight around actual content (the user's reference screenshot
  at 260pt still has plenty of headroom above 140pt).
- `desiredContentWidth` — measured via `GeometryReader` +
  `PreferenceKey` from the actual rendered notch content. **Includes
  the current font scale's effect on text sizing** — see the font
  scale interaction rule below.
- Width changes are animated with `.spring(response: 0.35,
  dampingFraction: 0.8)` so transitions are smooth.
- When `desiredContentWidth > maxWidth`, the offending text uses
  `.lineLimit(1).truncationMode(.tail)` to render with an ellipsis.

#### Font scale × auto-width interaction

**`maxWidth` is sacrosanct** — it is the user's explicit cap and is
never auto-bumped by a font scale change. The interaction rules:

1. When the user switches font scale (Appearance picker), text re-lays
   out at the new size. `GeometryReader` re-measures
   `desiredContentWidth` on the next frame.
2. The new desired width flows through the same clamp formula. If the
   scaled content now fits within the user's `maxWidth`, the notch
   grows to fit it (up to `maxWidth`).
3. If the scaled content exceeds `maxWidth`, truncation with tail
   ellipsis kicks in immediately. The notch width stays pinned at
   `maxWidth`; the user sees more `…` in long messages.
4. The clamp transition is animated with the same spring, so font
   size changes look smooth even when they trigger width changes.

To get more room at XL scale, the user must explicitly enter live edit
mode and bump `maxWidth`. There is no "effective max width = maxWidth
× fontScale" scaling — that would make the `maxWidth` setting
confusing ("why is my 440pt notch now 572pt at XL?").

Effect: idle state shrinks the notch tightly around its sparse content,
solving the "huge empty middle" problem in the user's screenshot.

### 4.4 Theme switching

Switching the theme picker immediately mutates
`store.customization.theme`. All views reading palette colors re-render.

#### Animation scoping (critical)

Naïvely applying `.animation(.easeInOut(duration: 0.3), value: theme)`
at the `NotchView` root would stack on top of the width spring and
could visually interfere with in-flight geometry animations. Instead,
color interpolation is scoped **only to color-bearing modifiers**
via a pair of dedicated view modifiers:

```swift
// Applied once at the NotchView root — animates the base fg/bg pair.
struct NotchPaletteModifier: ViewModifier {
    @EnvironmentObject var store: NotchCustomizationStore
    func body(content: Content) -> some View {
        content
            .foregroundStyle(store.palette.fg)
            .background(store.palette.bg)
            .animation(.easeInOut(duration: 0.3), value: store.customization.theme)
    }
}

// Applied at call sites that need the dimmer secondary color
// (timestamps, "85% · 2h" indicators, etc.).
// It uses the SAME animation scope so secondary text crossfades
// in lockstep with primary text and background.
struct NotchSecondaryForegroundModifier: ViewModifier {
    @EnvironmentObject var store: NotchCustomizationStore
    func body(content: Content) -> some View {
        content
            .foregroundStyle(store.palette.secondaryFg)
            .animation(.easeInOut(duration: 0.3), value: store.customization.theme)
    }
}

extension View {
    /// Root modifier — apply once at NotchView.
    func notchPalette() -> some View { modifier(NotchPaletteModifier()) }

    /// Call-site modifier for dimmer secondary text.
    /// Inherits the same 0.3s theme crossfade as `notchPalette()`.
    func notchSecondaryForeground() -> some View {
        modifier(NotchSecondaryForegroundModifier())
    }
}
```

Because both modifiers use the `.animation(_:value:)` variant with a
`value` parameter, each triggers only when `theme` changes and each
re-animates only the color-bearing properties it scopes. Geometry
animations (width spring) are not retriggered by theme switches.
Theme transitions for primary text, background, and secondary text
all interpolate simultaneously over 0.3s, and geometry transitions
can happen on top without interfering.

**Call-site rules:**
- Apply `.notchPalette()` **once** at the `NotchView` root.
- Any child view rendering secondary / dimmer text uses
  `.notchSecondaryForeground()` instead of calling
  `store.palette.secondaryFg` directly, so the animation is applied
  consistently.
- Status colors (success / warning / error) come from Asset Catalog
  entries under `NotchStatus/` and are **not** palette-controlled —
  they preserve semantic meaning across themes and therefore need
  no theme-scoped animation.

### 4.5 Localized strings

All new user-facing strings go into the existing localization catalog
(`ClaudeIsland/.../Localizable.xcstrings` — path matches existing
convention). Keys and default English values:

| Key | Default EN | Used in |
|---|---|---|
| `notch_section_header` | Notch | Settings Appearance tab sub-header |
| `notch_theme` | Theme | Theme picker label |
| `notch_theme_classic` | Classic | Theme display name |
| `notch_theme_paper` | Paper | Theme display name |
| `notch_theme_neonLime` | Neon Lime | Theme display name |
| `notch_theme_cyber` | Cyber | Theme display name |
| `notch_theme_mint` | Mint | Theme display name |
| `notch_theme_sunset` | Sunset | Theme display name |
| `notch_font_size` | Font Size | Font scale picker label |
| `notch_font_small` | S | Segmented picker item |
| `notch_font_default` | M | Segmented picker item |
| `notch_font_large` | L | Segmented picker item |
| `notch_font_xlarge` | XL | Segmented picker item |
| `notch_show_buddy` | Show Buddy | Visibility toggle |
| `notch_show_usage_bar` | Show Usage Bar | Visibility toggle |
| `notch_hardware_mode` | Hardware Notch | Mode picker label |
| `notch_hardware_auto` | Auto | Mode option |
| `notch_hardware_force_virtual` | Force Virtual | Mode option |
| `notch_customize_button` | Customize Size & Position… | Entry button |
| `notch_edit_save` | Save | Live edit Save button |
| `notch_edit_cancel` | Cancel | Live edit Cancel button |
| `notch_edit_notch_preset` | Notch Preset | Live edit Preset button |
| `notch_edit_drag_mode` | Drag Mode | Live edit Drag Mode button |
| `notch_edit_preset_disabled_tooltip` | Your device doesn't have a hardware notch | Help tooltip |

Simplified Chinese translations (matching existing `zh-Hans`
localization) are added in the same file, using the repo's
established translation voice.

### 4.6 Accessibility

All new controls carry VoiceOver labels:

- **Arrow buttons (◀ ▶):** `.accessibilityLabel("Shrink notch")` /
  `.accessibilityLabel("Grow notch")`, plus
  `.accessibilityHint("Hold Command for a larger step, hold Option for a finer step.")`
- **Theme dropdown rows:** each row uses
  `.accessibilityLabel("\(themeName) theme")` so VoiceOver announces
  "Neon Lime theme" rather than just "Neon Lime" which could be any
  arbitrary UI element.
- **Theme row color swatches:** `.accessibilityHidden(true)` because
  the swatch is decorative; the label already covers semantics.
- **Font Size segmented picker:** each segment uses
  `.accessibilityLabel(...)` with the full localized name ("Small",
  "Default", "Large", "Extra Large") rather than the short single-letter
  display label.
- **Customize Size & Position button:** explicit
  `.accessibilityHint("Opens live edit mode for resizing and positioning the notch directly.")`
- **Live edit overlay:**
  - Save: `.accessibilityLabel("Save notch customization")`.
  - Cancel: `.accessibilityLabel("Cancel notch customization")`.
  - Notch Preset: `.accessibilityLabel("Reset to hardware notch width")`.
  - Drag Mode: `.accessibilityLabel("Toggle drag mode")` +
    `.accessibilityValue(editSubMode == .drag ? "On" : "Off")`.
- **Simulated content** in the notch during live edit is
  `.accessibilityHidden(true)` — it's a visual preview only, not real
  session content to announce.
- **Dashed border + green pulse animation** in live edit has no ARIA
  role; the hint on the Customize button already tells VoiceOver
  users what to expect.

## 5. Architecture

### 5.1 State model

A single value type persists all notch customization state:

```swift
struct NotchCustomization: Codable, Equatable {
    var theme: NotchThemeID = .classic
    var fontScale: FontScale = .default
    var showBuddy: Bool = true
    var showUsageBar: Bool = true
    var maxWidth: CGFloat = 440
    var horizontalOffset: CGFloat = 0
    var hardwareNotchMode: HardwareNotchMode = .auto

    static let `default` = NotchCustomization()
}

enum NotchThemeID: String, Codable, CaseIterable, Identifiable {
    case classic, paper, neonLime, cyber, mint, sunset
    var id: String { rawValue }
}

enum FontScale: String, Codable, CaseIterable {
    case small    = "small"
    case `default` = "default"
    case large    = "large"
    case xLarge   = "xLarge"

    var multiplier: CGFloat {
        switch self {
        case .small:    return 0.85
        case .default:  return 1.0
        case .large:    return 1.15
        case .xLarge:   return 1.3
        }
    }
}

enum HardwareNotchMode: String, Codable {
    case auto          // detect via NSScreen.safeAreaInsets
    case forceVirtual  // ignore any hardware notch, draw a virtual overlay
}
```

### 5.2 Store

```swift
import OSLog

@MainActor
final class NotchCustomizationStore: ObservableObject {
    static let shared = NotchCustomizationStore()
    private static let log = Logger(subsystem: "com.codeisland.app", category: "notchStore")

    @Published private(set) var customization: NotchCustomization
    @Published var isEditing: Bool = false

    private var editDraftOrigin: NotchCustomization?
    private let defaultsKey = "notchCustomization.v1"

    private init() {
        if let loaded = Self.loadFromDefaults() {
            self.customization = loaded
        } else {
            // No v1 key yet. Migrate from legacy, then write v1 BEFORE
            // removing legacy keys so the migration is idempotent on
            // crash: if writing v1 fails, legacy keys stay intact and
            // next launch retries from scratch.
            self.customization = Self.readLegacyOrDefault()
            if self.saveAndVerify() {
                Self.removeLegacyKeys()
            } else {
                Self.log.error("Initial v1 write failed; legacy keys retained for retry on next launch")
            }
        }
    }

    func update(_ mutation: (inout NotchCustomization) -> Void) {
        mutation(&customization)
        save()
    }

    func enterEditMode() {
        editDraftOrigin = customization
        isEditing = true
    }

    func commitEdit() {
        editDraftOrigin = nil
        isEditing = false
        save()
    }

    func cancelEdit() {
        if let origin = editDraftOrigin {
            customization = origin
            save()
        }
        editDraftOrigin = nil
        isEditing = false
    }

    @discardableResult
    private func save() -> Bool {
        do {
            let data = try JSONEncoder().encode(customization)
            UserDefaults.standard.set(data, forKey: defaultsKey)
            return true
        } catch {
            Self.log.error("save failed: \(error, privacy: .public)")
            return false
        }
    }

    /// Save and roundtrip-verify by reading back. Used by migration
    /// so we only delete legacy keys after confirming persistence.
    private func saveAndVerify() -> Bool {
        guard save() else { return false }
        return Self.loadFromDefaults() != nil
    }

    private static func loadFromDefaults() -> NotchCustomization? {
        guard let data = UserDefaults.standard.data(forKey: "notchCustomization.v1") else { return nil }
        return try? JSONDecoder().decode(NotchCustomization.self, from: data)
    }

    /// Pull legacy @AppStorage values into a new NotchCustomization
    /// WITHOUT deleting the source keys. Deletion is a separate step
    /// that only runs after the v1 key is successfully written.
    private static func readLegacyOrDefault() -> NotchCustomization {
        var c = NotchCustomization.default
        let d = UserDefaults.standard
        if d.object(forKey: "usePixelCat") != nil {
            c.showBuddy = d.bool(forKey: "usePixelCat")
        }
        // ... any additional legacy keys added here follow the same pattern
        return c
    }

    private static func removeLegacyKeys() {
        UserDefaults.standard.removeObject(forKey: "usePixelCat")
        // ... any additional legacy keys added here follow the same pattern
    }
}
```

Key design choices:

- **Pure value type** for the customization. Codable roundtrip is
  trivial, testing needs no mocks, and any mutation produces a single
  atomic `@Published` notification — no "half-updated theme" frames.
- **`update` closure API** funnels every mutation through one place so
  `save()` is called exactly once per change.
- **Live edit uses a snapshot**, not a diff log. Cancel is a single
  assignment back to the snapshot — no per-field undo.
- **Versioned UserDefaults key** (`notchCustomization.v1`) leaves room
  for future schema migrations via `.v2`, `.v3` etc.
- **Legacy migration is one-shot and destructive.** After the first
  successful save to `v1`, legacy keys (`usePixelCat`) are removed so
  they can't diverge.

### 5.3 Theme module

```swift
struct NotchPalette: Equatable {
    let bg: Color
    let fg: Color
    let secondaryFg: Color
}

extension NotchPalette {
    static func `for`(_ id: NotchThemeID) -> NotchPalette {
        switch id {
        case .classic:  return NotchPalette(bg: .black,               fg: .white,               secondaryFg: Color(white: 1, opacity: 0.4))
        case .paper:    return NotchPalette(bg: .white,               fg: .black,               secondaryFg: Color(white: 0, opacity: 0.55))
        case .neonLime: return NotchPalette(bg: Color(hex: "CAFF00"), fg: .black,               secondaryFg: Color(white: 0, opacity: 0.55))
        case .cyber:    return NotchPalette(bg: Color(hex: "7C3AED"), fg: Color(hex: "F0ABFC"), secondaryFg: Color(hex: "C4B5FD"))
        case .mint:     return NotchPalette(bg: Color(hex: "4ADE80"), fg: .black,               secondaryFg: Color(white: 0, opacity: 0.55))
        case .sunset:   return NotchPalette(bg: Color(hex: "FB923C"), fg: .black,               secondaryFg: Color(white: 0, opacity: 0.5))
        }
    }
}
```

**`Color(hex:)` helper.** CodeIsland already has a `Color(hex: String)`
initializer (currently defined inside
`ClaudeIsland/Services/Session/BuddyReader.swift:17`). As part of this
feature, the helper is **lifted** to its own file
`ClaudeIsland/UI/Helpers/Color+Hex.swift` and the existing call sites
in `BuddyReader.swift` are updated to use the extracted extension.
This is a small scoped cleanup justified by the new feature's heavy
use of the helper; no API or behavior change.

Status colors live in Asset Catalog under `NotchStatus/`:

```
NotchStatus/
  Success.colorset  →  #4ADE80
  Warning.colorset  →  #FB923C
  Error.colorset    →  #F87171
```

Views use `Color("NotchStatus/Success")` etc. These are **not** in the
palette and do not change with theme — they preserve semantic meaning
(approval-needed is always a warning color regardless of theme).

### 5.4 Font scaling

All notch text uses a helper that multiplies the base size by the
current scale:

```swift
extension View {
    func notchFont(_ baseSize: CGFloat, weight: Font.Weight = .medium, design: Font.Design = .monospaced) -> some View {
        self.modifier(NotchFontModifier(baseSize: baseSize, weight: weight, design: design))
    }
}

struct NotchFontModifier: ViewModifier {
    @EnvironmentObject var store: NotchCustomizationStore
    let baseSize: CGFloat
    let weight: Font.Weight
    let design: Font.Design

    func body(content: Content) -> some View {
        content.font(.system(size: baseSize * store.customization.fontScale.multiplier, weight: weight, design: design))
    }
}
```

All existing `.font(.system(size: N, ...))` calls in the notch tree
are replaced with `.notchFont(N, ...)`. A single grep pass identifies
every call site. Scale changes take effect immediately via the
`@EnvironmentObject` dependency.

**`@EnvironmentObject` in auxiliary windows.** Because
`NotchLiveEditPanel` is a separate `NSWindow`, its content view's
SwiftUI environment does not automatically inherit the
`@EnvironmentObject` injected at the main scene root. The
`NotchLiveEditPanel`'s hosting view must explicitly re-inject the
store:

```swift
let hostingView = NSHostingView(
    rootView: NotchLiveEditOverlay()
        .environmentObject(NotchCustomizationStore.shared)
)
panel.contentView = hostingView
```

Same applies to any future auxiliary SwiftUI window.

### 5.5 Window geometry & hardware-notch detection

**Subscription ownership:** `NotchWindowController` is the sole owner
of the `store.$customization` subscription. It stores a
`Combine.AnyCancellable` as a private property:

```swift
private var customizationCancellable: AnyCancellable?

func attachStore(_ store: NotchCustomizationStore) {
    customizationCancellable = store.$customization
        .receive(on: DispatchQueue.main)
        .sink { [weak self] _ in self?.applyGeometry() }
}
```

The cancellable is released when `NotchWindowController` deinits —
matching the window lifetime. `WindowManager` owns the
`NotchWindowController` instance and is responsible for calling
`attachStore(...)` once after creation, but `WindowManager` itself
holds no subscription.

**Computation flow (on every customization change):**

```
hasHardwareNotch =
    switch hardwareNotchMode:
        .auto           → NSScreen.main?.safeAreaInsets.top > 0
        .forceVirtual   → false

baseNotchSize = hasHardwareNotch
    ? screen hardware notch dimensions from safeAreaInsets
    : synthetic default size (180pt × 37pt)

runtimeWidth = clamp(measuredContentWidth,
                     minIdleWidth,
                     store.customization.maxWidth)

baseX = (screen.width - runtimeWidth) / 2
clampedOffset = clamp(store.customization.horizontalOffset,
                      -baseX,
                      screen.width - baseX - runtimeWidth)
finalX = baseX + clampedOffset

notchY = screen top (always pinned)
```

**`horizontalOffset` clamp semantics:** the clamp is applied at
render time only — the stored value is never written back. Rationale:
if a user sets offset +300 on a wide external display and later
switches to a 1280pt built-in display where the legal max is +200,
the stored value is silently clamped to +200 for the duration they
use the smaller screen, but restored to +300 when they plug the
external display back in. This is the intentional behavior. The clamp
is stateless; the store is not mutated by render-time math.

**External monitor plug / unplug:** The existing `ScreenObserver`
already subscribes to
`NSApplication.didChangeScreenParametersNotification`. Its handler
now:

1. Calls `notchWindowController.applyGeometry()` to re-detect the
   active screen's notch + re-layout.
2. **If `NotchCustomizationStore.shared.isEditing == true` at the
   moment of the screen change, auto-cancels live edit mode** by
   calling `NotchCustomizationStore.shared.cancelEdit()` directly.
   This tears down the `NotchLiveEditPanel` overlay and reverts any
   draft changes. Rationale: attempting to migrate the overlay to a
   new screen mid-edit is complex and error-prone, and auto-committing
   unconfirmed changes would violate user intent. Auto-cancel is the
   safe default — the user can re-enter live edit mode on the new
   active screen.

**How `ScreenObserver` reaches the store.** The existing
`ScreenObserver` (see `ClaudeIsland/App/ScreenObserver.swift`) is a
plain `class`, not `@MainActor` and not a singleton — it is
instantiated with a closure callback and holds an `NSNotificationCenter`
observer registered on `queue: .main`. Because the notification queue
is `.main`, the callback closure itself runs on the main thread at
runtime, but the closure is not statically `@MainActor`-isolated in
Swift's type system.

For this feature, the handler needs to touch the `@MainActor`
`NotchCustomizationStore`. The spec-approved pattern is:

```swift
// in ScreenObserver's callback (or in the closure passed to it)
MainActor.assumeIsolated {
    let store = NotchCustomizationStore.shared
    notchWindowController.applyGeometry()
    if store.isEditing {
        store.cancelEdit()
    }
}
```

`MainActor.assumeIsolated` is a zero-cost statement of fact — we
know from the `queue: .main` registration that we are already on the
main thread; this closure is how we tell Swift's concurrency checker
the same thing. It produces no runtime work and compiles cleanly in
both Swift 5 and strict-concurrency Swift 6 modes.

No subscription or dependency injection is needed. There is no
circular dependency because `NotchCustomizationStore` never
references `ScreenObserver`.

### 5.6 New files

```
ClaudeIsland/
  Models/
    NotchCustomization.swift         ← value type, enums
    NotchTheme.swift                  ← palette definitions, NotchThemeID
  Services/State/
    NotchCustomizationStore.swift     ← ObservableObject store
  UI/Helpers/
    Color+Hex.swift                   ← existing String-based Color(hex:) lifted here
    NotchFontModifier.swift           ← font scaling helper
    NotchPaletteModifier.swift        ← NotchPaletteModifier + NotchSecondaryForegroundModifier + extension View
  UI/Views/
    NotchLiveEditPanel.swift          ← auxiliary NSPanel subclass
    NotchLiveEditOverlay.swift        ← SwiftUI controls inside the panel
    NotchLiveEditSimulator.swift      ← rotating simulated content
```

### 5.7 Files modified

- `ClaudeIsland/App/ClaudeIslandApp.swift` — inject
  `NotchCustomizationStore.shared` as an `@EnvironmentObject` at the
  scene root.
- `ClaudeIsland/UI/Views/NotchView.swift` — apply `.notchPalette()`
  modifier **once** at the root so primary fg and bg transitions are
  scoped; replace any remaining hardcoded primary colors (`.black`,
  `.white`) with implicit palette inheritance (i.e., rely on the
  root's `foregroundStyle`). For any text that was previously dimmed
  (e.g. `.white.opacity(0.4)`, `.gray`), apply
  `.notchSecondaryForeground()` at that call site so secondary text
  also animates on theme change. Replace `.font(.system(size:))`
  with `.notchFont(...)`. Thread the store through via
  `@EnvironmentObject`.
- `ClaudeIsland/UI/Views/ClaudeInstancesView.swift` — gate buddy and
  usage bar visibility on `store.customization.showBuddy` /
  `.showUsageBar`.
- `ClaudeIsland/UI/Components/BuddyASCIIView.swift` — **buddy rarity
  colors are preserved** (common / uncommon / rare / epic / legendary
  are semantic and should stay consistent across themes; a user who
  earned a legendary buddy always sees it in its legendary color). The
  only changes are: (a) replace the hardcoded `.background(Color.black)`
  on line ~623 with `palette.bg`; (b) apply `.notchFont(...)` to the
  text labels; (c) the error indicator `.red` at line ~503 moves to
  `Color("NotchStatus/Error")` since it is a semantic error state.
  Rarity colors themselves (`buddy.rarity.color`) are NOT touched.
- `ClaudeIsland/UI/Views/SystemSettingsView.swift` — add the new Notch
  subsection inside the Appearance tab, add the "Customize Size &
  Position…" entry point.
- `ClaudeIsland/Core/WindowManager.swift` and
  `ClaudeIsland/UI/Views/NotchWindowController.swift` — apply geometry
  from the store, subscribe to store changes.
- `ClaudeIsland/Services/ScreenObserver.swift` — reapply geometry on
  screen-change notifications.
- `ClaudeIsland/Assets.xcassets/` — add `NotchStatus/` color set.

## 6. Interaction flow diagrams

### 6.1 Enter edit mode

```
User taps "Customize Size & Position…"
  → SystemSettingsView.onCustomize()
  → store.enterEditMode()                       ← snapshot taken, isEditing = true
  → SystemSettingsWindow.hide()
  → NotchView observes isEditing
  → renders NotchLiveEditOverlay over notch
  → NotchLiveEditSimulator starts rotating fake content
```

### 6.2 Resize via arrow button

```
User clicks ◀
  → NotchLiveEditOverlay.onLeftArrow()
  → store.update { $0.maxWidth = max(minWidth, $0.maxWidth - 2) }
  → save() fires
  → NotchWindowController observes customization change
  → applyGeometry() recalculates and animates frame
```

### 6.3 Cancel

```
User clicks Cancel
  → NotchLiveEditOverlay.onCancel()
  → store.cancelEdit()
  → customization = editDraftOrigin
  → save() fires with original values
  → NotchWindowController applyGeometry() returns to pre-edit
  → SystemSettingsWindow.show() restores Settings
  → NotchLiveEditOverlay disappears (driven by isEditing = false)
```

## 7. Testing strategy

### 7.1 Unit tests

```
ClaudeIslandTests/
  NotchCustomizationTests.swift
    - Codable roundtrip preserves every field
    - Decoding missing fields uses defaults (forward-compat)
    - FontScale.multiplier mapping (0.85 / 1.0 / 1.15 / 1.3)
    - FontScale.rawValue stability (e.g. case .small encodes as "small" — any future rename would break persistence)
    - All HardwareNotchMode cases decode

  NotchCustomizationStoreTests.swift
    - init reads v1 from UserDefaults when present
    - init migrates from usePixelCat legacy key when v1 missing
    - init returns default when no keys exist
    - update(_:) closure mutates and saves exactly once
    - enterEditMode snapshots draft origin
    - commitEdit clears origin, persists changes
    - cancelEdit restores origin and persists
    - Concurrent update calls do not corrupt state (main-actor isolated)

  NotchThemeTests.swift
    - All 6 NotchThemeID cases produce valid, equatable palettes
    - Palettes do not contain status colors
    - Theme raw strings match their enum case names

  AutoWidthTests.swift
    - clampedWidth ≤ maxWidth for all desiredContentWidth
    - clampedWidth ≥ minIdleWidth for all desiredContentWidth
    - Truncation predicate triggers when content > maxWidth
    - Width responds to store mutations
```

### 7.2 Snapshot tests

**Pre-flight check for the plan:** before writing implementation
tasks, grep the project for an existing snapshot testing dependency
(`swift-snapshot-testing`, `SnapshotTesting`, custom `SnapshotBuddy`).
If none exists, snapshot coverage is descoped to a best-effort
manual QA pass — don't add a test-only dependency as part of this
feature.

If a snapshot library is already present, render these baselines:

- **6 themes at default scale** (6 images) — verifies every palette
  renders without crash and text is readable.
- **Classic theme × 4 font scales** (4 images) — verifies scaling
  doesn't break layout.
- **3 edit-mode states** — resize sub-mode, drag sub-mode, Notch
  Preset marker visible.

**Total: 13 snapshots** (down from a naïve 6×4 = 24 matrix that would
have been expensive to maintain for a palette of 3 colors). The
cross-product is covered by unit tests on palette lookup and scale
application, not by image diffs.

### 7.3 Manual QA checklist

Written to `docs/qa/notch-customization.md`:

- [ ] Enter edit mode → arrow buttons resize symmetrically → Save →
      close & relaunch app → width preserved.
- [ ] Enter edit mode → drag an edge → Cancel → width reverts.
- [ ] Enter edit mode → Notch Preset → width snaps to hardware notch
      width + 20pt → dashed marker flashes for 2s.
- [ ] On a MacBook Air without a hardware notch (or with Hardware
      Notch set to Force Virtual) → Notch Preset button disabled
      with help tooltip.
- [ ] Drag Mode → click → notch flashes → dragging moves horizontally
      only, y locked.
- [ ] Switch between all 6 themes → transition animates ≤ 0.3s,
      no flicker.
- [ ] Change font size to XL → all text (including buddy) scales
      proportionally, no layout breakage.
- [ ] Disable Show Buddy → pet disappears, surrounding layout
      collapses cleanly without gaps.
- [ ] Disable Show Usage Bar → usage bar disappears, idle-state notch
      becomes narrower.
- [ ] Idle state with only icon + time visible → notch auto-shrinks
      tight around content (the screenshot case).
- [ ] Claude sends a very long message → notch expands to configured
      maxWidth, then truncates with ellipsis.
- [ ] Plug in external monitor → notch migrates per Hardware Notch
      Mode setting without restart.
- [ ] Enter edit mode → toggle Drag Mode → drag horizontally to offset
      the notch → Cancel → horizontal offset AND any width changes
      revert to pre-edit values (covers the round-1 cancel-from-drag
      state machine path).
- [ ] Enter edit mode → plug or unplug an external monitor → live
      edit auto-cancels, `NotchLiveEditPanel` tears down, draft
      reverts (covers the round-1 external-monitor-during-edit path).
- [ ] Notch Preset button on a Mac with a hardware notch: click →
      width snaps to hardware notch + 20pt → dashed width marker
      appears below the notch (opacity 0→1 over 0.2s, hold 1.6s,
      1→0 over 0.2s) → marker fully gone after 2s.

## 8. Migration & rollout

### 8.1 User data migration

On first launch after upgrade:

1. `NotchCustomizationStore.init` checks for `notchCustomization.v1`.
2. If absent, it calls `readLegacyOrDefault()` (non-destructive read):
   - Reads `usePixelCat` → `showBuddy` if the key exists.
   - Returns a `NotchCustomization` with defaults for all other
     fields. Legacy keys are NOT deleted at this step.
3. Calls `saveAndVerify()` — encodes to JSON, writes to
   `notchCustomization.v1`, reads back to confirm. Only on success,
   proceeds to step 4.
4. Calls `removeLegacyKeys()` to purge the legacy `usePixelCat`
   (and any other future legacy keys).

If step 3 fails (e.g., UserDefaults I/O error, encoding crash), legacy
keys stay intact and the next launch retries from step 1. Migration
is fully idempotent.

**`showUsageBar` has no legacy key.** There was no previous setting
for usage-bar visibility — it was always visible. Existing users
therefore inherit the new default `true`, which matches their
pre-upgrade experience exactly. No migration work needed for this
field.

### 8.2 Release

- Single PR against `main` targeting **v1.10.0**.
- Bumped `MARKETING_VERSION` and `CURRENT_PROJECT_VERSION`.
- **Before cutting the release**, re-check Apple Developer Programs
  Support case `102860621331`. Two branches:
  - **Case still open (error 7000 unresolved):** v1.10.0 ships as a
    pre-release `v1.10.0-rc1` "signed but not notarized" via
    GitHub Releases, mirroring the v1.9.0-rc1 pattern. Homebrew cask
    in `xmqywx/homebrew-codeisland` is updated with the new version
    + sha256 + the existing postflight `xattr -dr
    com.apple.quarantine` hook stays in place.
  - **Case resolved:** v1.10.0 ships as a regular Release. Homebrew
    cask is updated to the new version + sha256, AND the postflight
    `xattr` hook is removed at the same time.
- README install notice and Homebrew README already cover the
  unnotarized state generically and need no changes.

## 9. Open questions

None. All clarifying questions from the brainstorming session have
been answered and incorporated.

## 10. Appendix: brainstorming decisions trace

| # | Feature | Decision |
|---|---|---|
| Scope | 7 features in one release | Chosen: A (all in one design + implementation) |
| #4 Drag | Drag semantics | B — slide along top edge only (not free-floating) |
| #3 Camera mode | Meaning of "camera mode" | Interpretation 1 — has-notch vs no-notch modes, virtual fallback for no-notch |
| #3 Size UX | Size adjustment surface | Live edit mode in-place on the notch itself, not a separate mockup page |
| #3 Height | Vertical resize? | Not adjustable — height is the visual signature |
| #3 Save semantics | What Save persists | Save max width (auto-width runtime uses it as the ceiling) |
| #3 Simulated content | What edit mode previews | Rotating fake Claude messages (short/medium/long) |
| #3 Notch Preset | On no-notch Macs | Disabled + help tooltip |
| #3 Cancel | Rollback granularity | Snapshot at enter; restore on cancel |
| #5 Themes | Preset count | 6 (Classic, Paper, Neon Lime, Cyber, Mint, Sunset) |
| #5 Transition | Switching animation | 0.3s fade |
| #5 Scope | Status color semantics | Status colors preserved, not overridden by theme |
| #6 Auto-width | Behavior at idle | Shrink to content; expand up to user's saved maxWidth on demand |
| #6 Overflow | When content > maxWidth | Single-line truncation with tail ellipsis |
| #7 Font | Scale vs absolute | Relative scale factor (0.85 / 1.0 / 1.15 / 1.3) |
| #7 UI | Control type | Segmented picker, 4 discrete steps |
| Arch | State management | Centralized `NotchCustomizationStore` (Y), not scattered AppStorage (X), not Redux (Z) |
| Arch | Persistence | Single versioned UserDefaults key (`notchCustomization.v1`) |
| Arch | Refactoring scope | Only notch-related AppStorage; leave notification/codelight/behavior untouched |

## 11. Spec review revisions (round 1)

Issues surfaced by the spec-document-reviewer subagent and resolved
before the spec was approved:

1. **Live edit overlay window model** was unspecified. Now
   Section 4.2 defines `NotchLiveEditPanel`, a new auxiliary
   `NSPanel` subclass with `canBecomeKey = true`, distinct from
   `NotchPanel`, positioned over the notch but sized to the full
   screen width so floating controls can live outside the notch
   bounds.
2. **`HardwareNotchMode` 3-case contradictions.** Simplified from
   `.auto / .forceOn / .forceOff` to `.auto / .forceVirtual`. The
   dropped `.forceOn` case had no user scenario and was creating
   inconsistent semantics. Notch Preset is now unambiguously
   enabled iff effective `hasHardwareNotch == true`.
3. **Simulated content rotation** now specifies `TimelineView`
   driver, view-lifetime scope, pause during active gesture with
   0.8s debounce, and a fixed 5-fixture rotation.
4. **Font scale × auto-width interaction** now explicitly states
   `maxWidth` is sacrosanct — font scale changes can trigger
   truncation but never auto-bump the user's saved max.
5. **Cancel during drag sub-mode** now explicitly defined: Save
   and Cancel work from any sub-mode; `editSubMode` is transient
   and dies with the overlay. A state diagram is included.
6. **Theme switching animation** now scoped to a dedicated
   `NotchPaletteModifier` using `.animation(_:value:)` so color
   transitions do not stack on geometry springs.
7. **`save()` migration idempotency** fixed: `init` writes v1
   before deleting legacy keys, uses a `saveAndVerify()` read-back
   check, and logs on failure. If v1 write fails, legacy keys
   stay untouched and next launch retries.
8. **External monitor disconnect during live edit** now defined:
   `ScreenObserver` auto-cancels live edit mode on screen change,
   tearing down `NotchLiveEditPanel` and reverting the draft.
9. **`horizontalOffset` render-time clamp** now documented as
   intentional: stored value preserved, clamp applied per-render,
   no write-back.
10. **`minIdleWidth`** lowered from 200pt to 140pt to match the
    "tight around content" requirement in QA and justified inline.
11. **`WindowManager` vs `NotchWindowController` subscription
    ownership** now assigned: `NotchWindowController` owns the
    `store.$customization` sink via a private `AnyCancellable`;
    `WindowManager` calls `attachStore(...)` once after creation.
12. **Edit sub-mode state machine** diagram added. Flash animation
    for sub-mode toggle specified concretely (opacity
    `1.0 → 0.4 → 1.0` over 0.3s `.easeInOut`).
13. **`@EnvironmentObject` injection for auxiliary `NSWindow`s**
    documented: the store must be re-injected into the
    `NotchLiveEditPanel`'s hosting view since `@EnvironmentObject`
    does not cross `NSWindow` boundaries.
14. **Snapshot test matrix** reduced from 24 to 13 images and
    made conditional on existing snapshot library detection.
15. **Release section** now has a pre-flight check on Apple case
    `102860621331` with distinct paths for "case still open" vs
    "case resolved".

## 12. Spec review revisions (round 2)

Second round of spec review feedback, resolved before the spec was
approved:

1. **`Color(hex:)` uses String, not integer.** All six palette
   definitions updated from `Color(hex: 0xNNN)` to
   `Color(hex: "NNN")` to match the existing CodeIsland helper
   at `BuddyReader.swift:17`. The helper is lifted to
   `UI/Helpers/Color+Hex.swift` as a scoped cleanup.
2. **`Log.error(...)` doesn't exist.** Replaced with Apple's
   `OSLog.Logger` (`category: "notchStore"`), which is a standard
   facility available without new dependencies.
3. **Menu-bar pass-through for the full-width edit panel.** Replaced
   the incorrect "`ignoresMouseEvents` per subview" wording with a
   concrete `NSView.hitTest(_:)` override on the panel's
   `contentView` that returns `nil` for points outside any control
   subview, ensuring clicks on the menu bar still reach the system.
4. **`FontScale` raw value type changed from `CGFloat` to `String`.**
   Cases now encode as `"small"` / `"default"` / `"large"` /
   `"xLarge"`, with a computed `multiplier: CGFloat` property. This
   eliminates the fragile `CGFloat` Codable round-trip and makes
   the persistence format future-proof.
5. **`BuddyASCIIView` palette integration disambiguated.** Buddy
   rarity colors (common / uncommon / rare / epic / legendary)
   are PRESERVED — they are semantic. Only the hardcoded
   `.background(Color.black)` and the `.red` error indicator move
   to palette / Asset Catalog status colors respectively.
6. **Localized strings enumerated** (new Section 4.5). 25+ new
   string keys listed with default English values; Simplified
   Chinese translations added in the same catalog file.
7. **Accessibility spec added** (new Section 4.6). VoiceOver labels,
   hints, and hidden flags specified for every new control.
8. **QA checklist gaps filled.** Added items for (a) Cancel after
   drag sub-mode, (b) external monitor plug/unplug during live
   edit, (c) Notch Preset marker fade animation timing.
9. **`showUsageBar` no-legacy-key migration note added.** Explicitly
   documents that existing users inherit the new default `true`,
   matching their pre-upgrade (non-configurable) experience.
10. **`NotchPaletteModifier` root application** now called out
    explicitly in Section 5.7's `NotchView.swift` bullet, so the
    implementer knows the `.notchPalette()` modifier must be
    applied at the root for scoped theme animations to work.
11. **`ScreenObserver` → store access pattern** spelled out:
    reads `NotchCustomizationStore.shared` directly since both
    are `@MainActor` singletons; no subscription or DI needed.
12. **Notch Preset dashed width marker** animation made concrete:
    opacity 0→1 (0.2s easeIn), hold 1.6s, 1→0 (0.2s easeOut),
    positioned 8pt below the notch frame.
13. **`hardwareNotchWidth` computation** now explicitly defined as
    `screen.frame.width - safeAreaInsets.left - safeAreaInsets.right`.
14. **State diagram** caveat added: Save/Cancel work from `.drag`
    sub-mode too, even though they're drawn only from `.resize` for
    visual clarity.

## 13. Spec review revisions (round 3)

Round 3 review surfaced 2 final issues, both resolved:

1. **`ScreenObserver` threading claim was factually wrong.** The
   spec had claimed `ScreenObserver` was a `@MainActor` singleton;
   actually it is a plain `class` instantiated with a closure
   callback and holds an `NSNotificationCenter` observer registered
   on `queue: .main`. The notification callback therefore runs on
   the main thread at runtime, but is not statically isolated.
   Section 5.5 is rewritten to: (a) correctly describe the existing
   `ScreenObserver` structure, and (b) mandate the
   `MainActor.assumeIsolated { ... }` pattern inside the handler
   before touching the store. This compiles cleanly in both Swift 5
   and strict-concurrency Swift 6 modes.

2. **`NotchPaletteModifier` didn't cover `secondaryFg`.** The
   original modifier animated only `fg` and `bg`, but the palette
   also has `secondaryFg` for dimmed text. Views reading
   `palette.secondaryFg` directly would have gotten the new color
   immediately without the 0.3s crossfade. Section 4.4 is expanded
   to introduce a second companion modifier
   `NotchSecondaryForegroundModifier` (applied at call sites via
   `.notchSecondaryForeground()`) that inherits the same animation
   scope. Section 5.7 updates the `NotchView.swift` bullet to use
   the new modifier at all dimmed-text call sites. Section 5.6 adds
   the second modifier type to `NotchPaletteModifier.swift`.
