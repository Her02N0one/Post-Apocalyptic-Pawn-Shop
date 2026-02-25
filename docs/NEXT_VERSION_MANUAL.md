# Post-Apocalyptic Pawn Shop — Zone Editor v2.0
## Idealistic Design Manual & Control Flow Blueprint

> **Purpose of this document:** This is not a description of the current software. This is an **exhaustive, idealistic design specification** for the next version of the zone editor — a version that solves every control flow problem, surfaces every hidden option, eliminates guesswork, and transforms the editor from a functional tool into a genuinely pleasant creative environment. Every section describes **what should exist**, **why it should exist**, and **exactly how it should behave**, down to individual pixel interactions and state transitions. Where the current version falls short, the gap is named explicitly and the solution is described in full.

---

## Table of Contents

### Part I — Philosophy & Principles
1. [Design Philosophy](#1-design-philosophy)
2. [The Three Laws of Editor UX](#2-the-three-laws-of-editor-ux)
3. [Control Flow Principles](#3-control-flow-principles)

### Part II — Application Shell
4. [Window & Layout Architecture](#4-window--layout-architecture)
5. [The Capture/Release Model (Reimagined)](#5-the-capturerelease-model-reimagined)
6. [Menu Bar & Global Commands](#6-menu-bar--global-commands)

### Part III — Left Panel (Toolbox)
7. [Tool Selection & Visual Feedback](#7-tool-selection--visual-feedback)
8. [The Brush Bar (Always Visible)](#8-the-brush-bar-always-visible)
9. [Texture Palette](#9-texture-palette)
10. [Model/Preset Palette](#10-modelpreset-palette)
11. [Snap Height Selector](#11-snap-height-selector)
12. [Contextual Controls Panel](#12-contextual-controls-panel)
13. [Display Toggles](#13-display-toggles)
14. [Zone Browser](#14-zone-browser)

### Part IV — Right Panel (Inspector)
15. [Zone Header & Metadata](#15-zone-header--metadata)
16. [Cell Inspector (Live)](#16-cell-inspector-live)
17. [Face Detail Inspector](#17-face-detail-inspector)
18. [Zone Settings (Editable)](#18-zone-settings-editable)
19. [Camera Info](#19-camera-info)

### Part V — Status Bar
20. [Status Bar — The Constant Truth](#20-status-bar--the-constant-truth)

### Part VI — Viewport & Interaction Model
21. [Viewport Rendering](#21-viewport-rendering)
22. [Crosshair & Aim Feedback](#22-crosshair--aim-feedback)
23. [The Action Context Display](#23-the-action-context-display)
24. [Ghost Preview System](#24-ghost-preview-system)

### Part VII — Tool-by-Tool Specification
25. [Sculpt Tool — Complete Specification](#25-sculpt-tool--complete-specification)
26. [Paint Tool — Complete Specification](#26-paint-tool--complete-specification)
27. [Fill Tool — Complete Specification](#27-fill-tool--complete-specification)
28. [Eraser Tool — Complete Specification](#28-eraser-tool--complete-specification)
29. [Segment (Detail) Tool — Complete Specification](#29-segment-detail-tool--complete-specification)
30. [Select Tool — Complete Specification](#30-select-tool--complete-specification)
31. [Stamp (Model) Tool — Complete Specification](#31-stamp-model-tool--complete-specification)

### Part VIII — Raycaster Preview Mode
32. [Preview Mode — First Person Walkthrough](#32-preview-mode--first-person-walkthrough)

### Part IX — Dialogs, Modals, and Overlays
33. [New Zone Dialog](#33-new-zone-dialog)
34. [Save / Save As Dialogs](#34-save--save-as-dialogs)
35. [Unsaved Changes Guard](#35-unsaved-changes-guard)
36. [Preset Capture Dialog](#36-preset-capture-dialog)

### Part X — Proposed New Features
37. [Light Level Painting Tool](#37-light-level-painting-tool)
38. [Entity Placement Tool](#38-entity-placement-tool)
39. [Portal Editor](#39-portal-editor)
40. [Zone Resize & Crop Tool](#40-zone-resize--crop-tool)
41. [Multi-Cell Stamp (Blueprint)](#41-multi-cell-stamp-blueprint)
42. [Overlay Wall Tool](#42-overlay-wall-tool)
43. [Autosave & Session Recovery](#43-autosave--session-recovery)

### Part XI — Keyboard & Mouse Reference
44. [Complete Keyboard Shortcut Table](#44-complete-keyboard-shortcut-table)
45. [Complete Mouse Action Table](#45-complete-mouse-action-table)

### Part XII — Architecture & Implementation Notes
46. [State Machine Diagram](#46-state-machine-diagram)
47. [Event Routing Priority](#47-event-routing-priority)
48. [Undo/Redo Architecture](#48-undoredo-architecture)
49. [Performance Budget](#49-performance-budget)

---

## Part I — Philosophy & Principles

---

### 1. Design Philosophy

The zone editor is where every room, every corridor, every pit, every rooftop, and every wall texture in the game is born. It is the most-used tool in the entire development pipeline. Every friction point in the editor multiplies across thousands of interactions. Every hidden option costs the user seconds of hunting that accumulate into hours of lost creative flow.

**The ideal zone editor should feel like sculpting clay with your hands, not operating laboratory equipment with tweezers.**

The current editor is functional. It has all the tools. But it hides critical information behind collapsed panels, forces the user to remember which scroll direction does what, shows tool state in tiny text that disappears when the mouse is captured, and provides no preview of what a click will actually do. The next version must fix all of this — not incrementally, but by rethinking the information architecture from the ground up.

The guiding metaphor is **a potter's wheel**: the material is always visible, the tools are always within reach, your hands always know what they're touching, and the result of every motion is immediately apparent. You never have to stop sculpting to open a cabinet and find the right tool. You never have to guess whether pressing down will raise or lower the clay. You never lose track of what color glaze is on your brush.

#### Core Tenets

1. **No hidden state — for things that change.** If something affects the next click and the user might have changed it recently, it must be visible on screen. The current texture, the current snap height, the current tool — these shift constantly and must always be shown. However, stable behaviors that rarely change (like "Shift + Eraser = clear textures only") are acceptable candidates for memorization. The line is: **if the user set it, show it; if the user learned it, trust them.**

2. **No ambiguous actions.** Before theegible.

3. **No wasted clicks.** Every mouse click and every key press should accomplish something the user intended.

4. **No modal confusion.** The user should always know whether they're in captured mode or released mode, and the transition between them should be effortless and forgiving. Accidental escapes from edit mode should never cause data loss.

5. **Progressive disclosure, not hidden disclosure.** Rarely-used options can be tucked away, but they should be *discoverable* — visible as collapsed sections or grayed-out labels, not invisible until you happen to know the keyboard shortcut.

#### The Memorization Budget

Every professional tool has a learning curve. Blender has thousands of shortcuts. Unity hides entire subsystems behind menus. Photoshop expects you to memorize brush modifiers. This is not a flaw — it's a tradeoff between **screen space** and **information density**.

The zone editor should be honest about what it expects the user to memorize and what it keeps on screen:

| **Always on screen** | **Acceptable to memorize** |
|---|---|
| Current tool (affects every click) | Tool number keys (1-7) |
| Current texture/preset (changes often) | Modifier combos (Shift+U, Ctrl+U) |
| Current snap height (changes often) | Camera controls (WASD, Space, C) |
| Aimed cell coordinates | View toggles (F2/F3/F4, V) |
| Dirty/saved state | Per-tool secondary actions (T=toggle ceiling, R=reset) |
| Edit vs Panel mode indicator | Escape priority chain |

The rule of thumb: **if the user sets a value, show the value. If the user triggers an action, they can memorize the trigger.** A texture selection is a *value* — it persists and affects future clicks, so show it. A keyboard shortcut is an *action* — it fires once, so it's fine to memorize. The Controls section in the left panel bridges this gap by listing the current tool's shortcuts, giving users a reference while they're still learning.

---

### 2. The Three Laws of Editor UX

These three laws govern most design decisions in the next version. They're guidelines, not absolutes — screen space is finite and learning curves are real. But when something *can* be shown without sacrificing layout, it should be. Apply them in order when deciding how a feature should surface:

#### Law 1: The Screen Never Lies

> **State that the user actively changes should be visible on screen. Stable behaviors can live in muscle memory.**

This law applies to **mutable state** — things the user has recently changed or might change at any moment. It does *not* mean every possible shortcut or secondary action needs a permanent label. The user can be expected to learn that `T` toggles ceilings — that's muscle memory, not hidden state. But the user should NOT have to remember which texture they scrolled to 30 seconds ago.

Violations in the current version (things that *should* be visible but aren't):
- When the mouse is captured, the ImGui panels are visible but inert. The user can see the panel contents (texture palette, cell inspector) but the information may be stale because the panels don't update in real time during captured mode. **Fix:** Panels must update every frame, even during capture. They are read-only during capture but always current.
- When scrolling to cycle textures in captured mode, the only feedback is the HUD text in the top-left corner (e.g., "Tex: brick_dark"). This text is small, in a corner the user isn't looking at (they're focused on the crosshair at center-screen), and it updates silently. **Fix:** A prominent floating label must appear near the crosshair whenever the selection changes, with a brief fade-out animation. The palette in the left panel must also scroll to keep the selected texture visible.
- The snap height is shown in the status bar as a bare number (e.g., "Snap: 0.25"). This is easy to miss and hard to interpret at a glance. **Fix:** The snap row in the left panel must always be visible (not inside a collapsing section), and the selected snap must have a distinct visual highlight. A preview line at the snap height should optionally appear on the aimed cell.

#### Law 2: Every Click is a Sentence

> **The user should be able to describe what will happen before they click, and the editor should confirm it after they click.**

The ideal user experience is:
1. **Before click:** "I am about to raise this floor by 0.25." (Crosshair shows floor, action label says "Raise Floor +0.25", ghost preview shows the new height.)
2. **During click:** The floor rises visually.
3. **After click:** The cell inspector updates to show the new height. A subtle flash on the cell confirms the edit. The undo stack gains an entry described as "Raise floor (3, 7) → 0.75".

Violations in the current version:
- The sculpt tool's scroll-extend feature changes the floor height by `snap_y` per scroll tick, but there's no preview of the new height before the scroll is committed. The height just changes. **Fix:** Hold Shift to show a "target height" line on the cell, then scroll to adjust, then release Shift (or click) to commit. Or at minimum, display the resulting height in the action context near the crosshair.
- The erase tool's Shift+LMB variant (clear textures only) is discoverable only by reading the TOOL_HINTS dict or the documentation. The button label just says "ERASER" with no indication that Shift changes its behavior. **Fix:** When Shift is held with the erase tool selected, the action label near the crosshair should change from "Reset Cell" to "Clear Textures Only". The tool button itself could show a modifier badge.

#### Law 3: Tools Don't Hide

> **If a tool exists, the user should be able to find it by looking at the screen, not by reading documentation.**

Violations in the current version:
- The upper-wall-height adjustment (U / Shift+U / Ctrl+U) is a critical sculpting feature with no UI representation whatsoever. It only appears in the context hints if you're using the sculpt tool and aiming at a ceiling. A new user will never discover it. **Fix:** When aimed at a ceiling with the sculpt tool, the inspector should show an "Upper Wall" slider or the action context should explicitly list "U: Upper Wall ▲".
- The T key (toggle ceiling on/off) only works in the sculpt tool and is only documented in the hints. **Fix:** The cell inspector should have a clickable "Has Ceiling" toggle.
- The select tool's X key (toggle floor/ceiling mode) is visually indicated but only by a small colored word in a section that may be scrolled out of view. **Fix:** The mode toggle should be a prominent badge at the top of the select tool's section, ideally with a visual indicator showing which surfaces will be affected.

---

### 3. Control Flow Principles

The current editor's control flow can be summarized as: "click to enter, Escape to exit, everything else depends on which tool is selected and what you're aiming at." This is mostly fine, but the details create constant friction. The next version should follow these principles:

#### Principle 1: Predictable Mode Transitions

The editor has exactly two interaction modes: **Panel Mode** (mouse free, ImGui active) and **Edit Mode** (mouse captured, all input goes to viewport). The transitions must be:

| From | To | Trigger | What Happens |
|------|----|---------|-------------|
| Panel | Edit | Click on viewport area | Cursor hides, mouse grabs. **The click that triggers capture ALSO performs a tool action** — no wasted first click. |
| Panel | Edit | Press Enter or F5 | Same as clicking viewport. Enables keyboard-only workflow. |
| Edit | Panel | Press Escape | Cursor appears, mouse ungrabs. If a selection is active, Escape first cancels the selection (second Escape exits edit mode). |
| Edit | Panel | Press Tab (to toggle view) | Mouse stays captured, view switches. |
| Panel | Quit | Press Escape (no zone loaded) | Application exits. |
| Panel | Quit | Press Escape (zone loaded, clean) | Prompts "Quit editor?" |
| Panel | Quit | Press Escape (zone loaded, dirty) | Prompts "Save changes to [zone]?" with Save / Discard / Cancel. |

**Critical improvement: The first click into the viewport should not be wasted.** The current behavior captures the mouse but discards the click event. In the next version, when the user clicks a viewport area from Panel Mode, the editor should:
1. Immediately capture the mouse.
2. Compute what cell/face the click would have hit (using the click's screen position projected through the camera).
3. Perform the tool action on that cell/face.

This eliminates the "click to enter, now click again to actually do something" friction that plagues every capture-based editor.

#### Principle 2: Context Flows Downward

Information should flow from general to specific as you scan the screen from top to bottom and from the panels inward toward the viewport:

```
Menu Bar          → Global commands (File, Edit, View)
Left Panel Top    → Active tool (WHAT you're doing)
Left Panel Middle → Active brush/texture/preset (WHAT you're applying)
Left Panel Bottom → Display toggles, zone list (WHAT you're looking at)
Status Bar        → Current state summary (WHERE you are, WHAT tool, WHAT texture)
Viewport Center   → Crosshair + action label (WHAT will happen next)
Right Panel       → Aimed cell detail (WHAT you're pointing at)
```

This hierarchy means the user can answer any question by looking at the right place:
- "What tool am I using?" → Top of left panel (always visible).
- "What texture will I paint?" → Brush bar in left panel (always visible, never collapsed).
- "What cell am I aiming at?" → Right panel cell inspector (auto-updates).
- "What will my next click do?" → Action label near crosshair.
- "What's the current snap height?" → Snap row in left panel + status bar.

#### Principle 3: Scroll Always Shows Its Effect

When the user scrolls while captured (editing), something in the UI must change visibly to confirm the scroll was received and show its effect. The current version updates the HUD text, but this is inadequate because:

1. The HUD is in the corner while the user's eyes are on the crosshair.
2. The text change is subtle (just a name swap, no animation or emphasis).
3. The palette list in the left panel doesn't track the scroll.

**Proposed solution: The Transient Indicator**

Whenever a scroll event cycles a value (texture, preset, snap), a **transient indicator** appears near the crosshair for 1.5 seconds:

```
┌────────────────────────┐
│ ■  brick_dark  (4/23)  │
│ ←  scroll to cycle     │
└────────────────────────┘
```

- The `■` square is a color swatch matching the texture color.
- The name is shown in high-contrast text.
- The position indicator (4/23) tells the user where they are in the palette.
- The hint "scroll to cycle" fades after the first few uses (teaching moment).
- The palette list in the left panel also scrolls to center the new selection, even during captured mode.

For snap height changes:

```
┌──────────────────┐
│ Snap: 1/4  ●     │
│ ○ ○ ● ○ ○       │
└──────────────────┘
```

- The five dots represent the five snap options.
- The filled dot shows the current selection.
- The numeric label confirms the value.

For preset changes:

```
┌──────────────────────────┐
│ ◆  Brick Room  (2/7)    │
│  Category: Walls         │
└──────────────────────────┘
```

These indicators overlay the viewport at approximately 70% opacity and fade out smoothly. They never block the crosshair itself.

#### Principle 4: Panels Update During Capture

In the current version, ImGui panels are rendered during captured mode (they're visually present) but the user can't interact with them. However, they should still **update their content every frame** based on the editor_3d's current state.

This means:
- The **texture palette** will highlight the currently selected texture and scroll to it when the user scrolls through the palette with the mouse wheel.
- The **cell inspector** will update to reflect the cell currently under the crosshair, even as the user pans around.
- The **snap selector** will highlight the current snap value when the user cycles it with Shift+Scroll.
- The **tool bar** will highlight the active tool when the user switches with number keys.

The panels are **read-only during capture** (you can't click them — the mouse is grabbed) but they serve as a **live dashboard** of current editing state. This solves the "information hidden during editing" problem that currently forces users to exit edit mode just to see what texture they have selected.

---

## Part II — Application Shell

---

### 4. Window & Layout Architecture

#### Window Configuration

| Property | Value | Notes |
|----------|-------|-------|
| Default size | 1600 × 900 | Comfortable on 1080p and larger |
| Minimum size | 1024 × 640 | Below this, controls start to clip |
| Resizable | Yes | Panels scale proportionally with window width |
| Title bar | "Zone Editor — [zone_name]" | Asterisk (*) suffix when dirty |
| Icon | moonPAPS.png | Set from `assets/textures/icon/` |
| Frame rate | 60 FPS cap | `clock.tick(60)` |
| VSync | Off (pygame controls frame rate) | Avoids double-capping |

#### Panel Layout

The window is divided into five regions:

```
┌──────────────────────────────────────────────────────────────────┐
│ MENU BAR (22px)                                          FPS    │
├─────────────┬──────────────────────────────────┬─────────────────┤
│             │                                  │                 │
│   LEFT      │          VIEWPORT                │     RIGHT       │
│   PANEL     │                                  │     PANEL       │
│  (280px     │    (remaining space)              │    (250px       │
│   default)  │                                  │     default)    │
│             │                                  │                 │
│             │                                  │                 │
│             │                                  │                 │
├─────────────┴──────────────────────────────────┴─────────────────┤
│ STATUS BAR (28px)                                                │
└──────────────────────────────────────────────────────────────────┘
```

#### Panel Resizing

Both panels have **draggable splitter handles** on their inner edges (8px grip zone). Constraints:

| Panel | Minimum | Maximum |
|-------|---------|---------|
| Left | 200px | 50% of window width − 50px |
| Right | 200px | 50% of window width − 50px |

When the window is resized, panel widths scale proportionally:
```python
new_panel_w = max(min_w, min(max_w, int(old_panel_w * (new_win_w / old_win_w))))
```

The viewport always gets the remaining horizontal space. Its minimum implicit width is `window_width - left_panel - right_panel`, which is guaranteed to be ≥ 50px by the max constraints on panels.

#### Scaling Philosophy

Unlike the 2D editor (which uses a `Layout.s()` scale factor tied to window height), the zone editor's ImGui panels use ImGui's own DPI-aware scaling. Font sizes, button heights, and spacing are controlled through ImGui style variables. The viewport (3D wireframe / raycaster) renders to whatever pixel dimensions are available and handles its own aspect ratio.

---

### 5. The Capture/Release Model (Reimagined)

The current capture/release model works but has rough edges. This section describes the improved version.

#### State Machine

```
                    Click on viewport / Enter / F5
    ┌──────────┐ ─────────────────────────────────────→ ┌──────────────┐
    │  PANEL   │                                         │    EDIT      │
    │  MODE    │ ←──────────────────────────────────── │    MODE      │
    └──────────┘     Escape (no active selection)        └──────────────┘
         │                                                     │
         │ Escape (no zone)                                    │ Tab
         ↓                                                     ↓
    ┌──────────┐                                         ┌──────────────┐
    │   QUIT   │                                         │  EDIT MODE   │
    │  DIALOG  │                                         │ (other view) │
    └──────────┘                                         └──────────────┘
```

#### Panel Mode

In Panel Mode, the cursor is visible and all input routes to ImGui. The user can:
- Click tool buttons, texture swatches, zone list entries, checkboxes
- Adjust zone settings (anchor, first_person flag)
- Open dialogs (New Zone, Save As)
- Use menu bar (File, Edit, View)
- See a "Click viewport to edit | Enter = start | Esc = quit" hint centered on the viewport

**New in v2:** The viewport still renders the 3D view in real time (camera is frozen but the scene is drawn), and the right panel's cell inspector says "Aim at a cell to inspect" because no cell is being aimed at. When hovering over the viewport area (but not clicking), a subtle crosshair could optionally appear showing where the camera is pointing, giving the user a preview of where they'll start editing.

#### Edit Mode

In Edit Mode, the cursor is hidden and grabbed. All input routes to the 3D editor (or raycaster). The user can:
- Move camera with WASD + mouse
- Use tools with LMB/RMB/MMB
- Scroll to cycle palette, extend heights, or adjust selection
- Press number keys to switch tools
- Press Escape to return to Panel Mode (or cancel selection first)
- Press Tab to toggle between 3D editor and raycaster preview

**Critical change: The panels remain visible and continue to update in real time.** They reflect:
- The currently aimed cell (inspector)
- The current tool (tool bar highlight)
- The current texture/snap/preset (left panel sections)
- The zone dirty state (status bar)

The panels are **visually muted** during Edit Mode (perhaps a subtle darkening or reduced opacity on the panel backgrounds) to indicate they're read-only. But their content is always fresh.

#### The First-Click Problem: Solved

When the user clicks on the viewport from Panel Mode:

1. The click position is recorded: `(mouse_x, mouse_y)`.
2. The mouse is captured (hidden, grabbed).
3. A one-time ray is cast from the camera through the click position to determine what cell/face was clicked.
4. The appropriate tool action is performed on that cell/face.
5. The user is now in Edit Mode with the tool action already completed.

This eliminates the "wasted first click" problem. The user clicks a cell — the cell gets edited — and they're now in Edit Mode to continue editing.

**Edge case:** If the click position doesn't hit any cell (e.g., the user clicked on empty sky), the transition to Edit Mode still occurs but no tool action is performed. This is still better than the current behavior because it's at least consistent: "clicking the viewport means start editing, and if you happened to click something, it gets edited."

#### Escape Priority Chain

When Escape is pressed in Edit Mode, it should be processed in this priority order:

1. **Active selection in select tool?** → Cancel selection. Stay in Edit Mode.
2. **Any other tool state to cancel?** → Cancel it. Stay in Edit Mode.
3. **Nothing to cancel?** → Return to Panel Mode.

When Escape is pressed in Panel Mode:

1. **Dialog open?** → Close dialog. Stay in Panel Mode.
2. **Zone loaded and dirty?** → Show "Save changes?" dialog.
3. **Zone loaded and clean?** → Show "Quit editor?" confirmation.
4. **No zone loaded?** → Quit immediately.

This chain is crucial for preventing accidental data loss. The current version goes directly from Panel Mode Escape → `QUIT` with no confirmation, which is dangerous.

---

### 6. Menu Bar & Global Commands

The menu bar spans the full window width and contains three menus plus a right-aligned FPS counter.

#### File Menu

| Item | Shortcut | Action |
|------|----------|--------|
| New Zone... | — | Opens New Zone dialog |
| Open Zone... | — | Opens a zone browser (could be a file picker or an expanded zone list) |
| Save | Ctrl+S | Saves current zone. If untitled, prompts Save As. |
| Save As... | Ctrl+Shift+S | Prompts for a new name |
| — separator — | | |
| Export as JSON | — | *(Proposed)* Export zone in human-readable JSON format for external tools |
| — separator — | | |
| Quit | Escape | Exits (with unsaved changes guard) |

#### Edit Menu

| Item | Shortcut | Action |
|------|----------|--------|
| Undo | Ctrl+Z | Undo last edit |
| Redo | Ctrl+Y | Redo last undo |
| — separator — | | |
| Select All | Ctrl+A | *(Proposed)* Select entire zone grid |
| Deselect | Escape | *(Proposed)* Clear selection |
| — separator — | | |
| Zone Settings... | — | *(Proposed)* Opens a dedicated zone settings dialog with all editable properties |

#### View Menu

| Item | Shortcut | Current State |
|------|----------|---------------|
| 3D Editor | Tab | Checkmark when active |
| Raycaster Preview | Tab | Checkmark when active |
| — separator — | | |
| Show Axes | F4 | Toggle checkmark |
| Show Walls | V | Toggle checkmark |
| Show Ceiling Grid | F3 | Toggle checkmark |
| Show Floor Grid | F2 | Toggle checkmark |
| — separator — | | |
| *(Proposed)* Show Lighting | L | Toggle light level visualization |
| *(Proposed)* Show Entity Markers | E | Toggle entity position markers |
| *(Proposed)* Show Portal Markers | P | Toggle portal trigger zone highlights |

#### FPS Counter (Right-Aligned)

Color-coded based on frame time:
| Frame Time | Color | Meaning |
|------------|-------|---------|
| < 10ms | Green | Smooth (100+ FPS) |
| 10–20ms | Yellow | Acceptable (50–100 FPS) |
| > 20ms | Red | Slow (< 50 FPS) |

Format: `{fps:.0f} FPS  {frame_ms:.1f}ms`

---

## Part III — Left Panel (Toolbox)

The left panel is the user's primary control surface. It must be organized so that **every section the user needs during active editing is visible without scrolling** for a typical 900px+ window height. Sections are separated by tinted headers with subtle underlines.

---

### 7. Tool Selection & Visual Feedback

The tool bar is the **first section** in the left panel, immediately visible without scrolling.

#### Layout

Seven tool buttons arranged in a 3-column grid (3 + 3 + 1 = 7):

```
┌──────────┬──────────┬──────────┐
│1 SCULPT  │2 PAINT   │3 FILL    │
├──────────┼──────────┼──────────┤
│4 ERASER  │5 DETAIL  │6 SELECT  │
├──────────┼──────────┼──────────┤
│7 MODEL   │          │          │
└──────────┴──────────┴──────────┘
```

#### Visual States

Each button has three visual states:

| State | Background | Text | Border |
|-------|-----------|------|--------|
| **Active** (currently selected) | Tool color at 55% opacity | White, bold weight | Subtle 1px glow in tool color |
| **Hovered** (mouse over, not selected) | Default button color, slightly lighter | Light gray | None |
| **Idle** (not selected, not hovered) | Default dark button color | Dimmed gray (65% white) | None |

The tool's color is derived from `TOOL_COLORS` — each tool has a unique tint:
- Sculpt: warm amber `(220, 160, 60)`
- Paint: soft purple `(200, 120, 220)`
- Fill: teal `(80, 200, 200)`
- Eraser: danger red `(220, 80, 80)`
- Detail: orange `(255, 180, 60)`
- Select: gold `(255, 220, 100)`
- Model: violet `(180, 140, 255)`

#### Tool Switch Feedback

When the user switches tools (via button click or number key), the following should happen simultaneously:
1. The button highlight animates (instant snap — no lerp, this must feel crisp).
2. The **Brush Bar** updates to show the appropriate context (texture for paint/fill/detail/select, preset for model, nothing for sculpt/erase).
3. The **Controls** section updates to show the new tool's actions.
4. The **crosshair color** changes to match the tool color.
5. The **action context label** near the crosshair updates.
6. The **status bar** tool indicator updates.

All of these changes happen in a single frame. There should be zero lag between pressing "2" and seeing the entire UI update to reflect the Paint tool.

---

### 8. The Brush Bar (Always Visible)

**This is one of the most important changes from the current version.**

In the current editor, the texture palette is inside a collapsing header ("Textures") that only appears for certain tools. If you switch to the sculpt or erase tool, the palette disappears entirely. When you switch back to paint, you have to remember which texture you had selected. Worse, when the palette header is collapsed, there's no indication of the current texture at all.

**In v2, the Brush Bar is an always-visible section that shows the current selection regardless of tool.**

#### Structure

```
┌──────────────────────────────────┐
│ ▁ BRUSH                         │  ← Section header
│ ┌──┐                            │
│ │  │ brick_dark     (4 / 23)    │  ← 20px color swatch + name + position
│ └──┘                            │
│ Category: Walls                  │  ← Category label (for presets)
└──────────────────────────────────┘
```

For **texture-using tools** (Paint, Fill, Detail, Select): Shows the current texture name, color swatch, and palette position.

For **the Model tool**: Shows the current preset name, category, and a preset-colored swatch.

For **non-brush tools** (Sculpt, Eraser): Shows the last-used texture in a dimmed/grayed style with the label "Brush: brick_dark (not active)" — so the user always knows what texture they'll get if they switch to a painting tool.

This section is **never hidden, never collapsed, and never empty.** The user can always see what brush/texture/preset is selected.

---

### 9. Texture Palette

The texture palette is a scrollable list below the Brush Bar. It appears for texture-using tools.

#### Layout

```
┌──────────────────────────────┐
│ ┌──┐                        │
│ │  │ sand                    │  ← 12px swatch + name
│ └──┘                        │
│ ┌──┐                        │
│ │  │ concrete            ←  │  ← Selected item (highlighted)
│ └──┘                        │
│ ┌──┐                        │
│ │  │ brick_light             │
│ └──┘                        │
│ ...                          │
└──────────────────────────────┘
```

#### Behavior

| Interaction | Effect |
|-------------|--------|
| Click a texture | Sets it as the current texture immediately. If in Edit Mode, the brush updates. |
| Scroll (in panel) | Scrolls the list. Does NOT change the selected texture. |
| Scroll (in viewport, Edit Mode) | Cycles the selected texture. The palette list auto-scrolls to keep the selection visible. |
| Type in a filter field *(proposed)* | Filters the list by name substring. |

#### Auto-Scroll Behavior

When the selected texture changes (via scroll-in-viewport or number key), the palette list should auto-scroll to center the selected item. This ensures the user can always see which texture is active by glancing at the panel, even during captured editing.

**Current issue:** The palette doesn't auto-scroll during capture. Proposed fix: On every frame during which `ed.tex_idx` has changed since last frame, call `imgui.set_scroll_here_y(0.5)` on the newly selected item in the palette child.

#### Palette Ordering

Textures should be sorted with walls first, then floors, then miscellaneous. Within each group, alphabetical order. This is the current behavior and it works well.

---

### 10. Model/Preset Palette

When the Model (Stamp) tool is active, the texture palette is replaced by the preset palette.

#### Layout

```
┌──────────────────────────────┐
│ ▁ MODEL                     │
│ ◆  Brick Wall      (2/7)     │  ← Current preset with icon
│   Category: Walls            │
│                              │
│ ┌─                          ─┐
│ │ brick_wall             ← │ │  ← Scrollable list
│ │ interior_room              │
│ │ open_ground                │
│ │ segmented_brick            │
│ │ stone_platform             │
│ │ wooden_counter             │
│ │ captured_3_5               │
│ └─                          ─┘
└──────────────────────────────┘
```

#### Preset Display Information

Each preset in the list should show:
- **Name** (display name, not ID)
- **Category badge** (colored text: "Walls" in amber, "Rooms" in blue, "Custom" in green)
- **Brief description** *(proposed field)*: A one-line description like "1-high brick wall with concrete floor"

#### Preset Capture Feedback

When the user captures a cell as a new preset (RMB with Model tool), the following should happen:
1. A subtle "Captured!" toast appears near the crosshair for 1 second.
2. The new preset appears in the palette list, auto-selected.
3. The Brush Bar updates to show the new preset name.
4. *(Proposed)* A capture dialog optionally appears (can be suppressed via preference) allowing the user to name and categorize the preset before it's saved.

---

### 11. Snap Height Selector

The snap selector controls how much the floor/ceiling changes per click or scroll tick. It must always be visible because it affects the sculpt tool's behavior.

#### Layout

```
┌──────────────────────────────┐
│ ▁ SNAP                      │
│ ┌─────┬─────┬─────┬─────┬─────┐
│ │1/16 │ 1/8 │ 1/4 │ 1/2 │  1  │
│ └─────┴─────┴─────┴─────┴─────┘
└──────────────────────────────┘
```

#### Visual States

- **Selected**: Green-tinted background (`#387D5A`), white text
- **Unselected**: Default dark button, gray text
- **Hovered**: Slightly lighter background

The five options represent actual height values: `0.0625, 0.125, 0.25, 0.5, 1.0`. The display labels use fractions because they're more intuitive than decimals for level designers thinking in "quarter-tile" and "half-tile" increments.

#### Keyboard Shortcut

The `G` key cycles through snap values (forward). `Shift+G` *(proposed)* cycles backward. Each press updates the visual highlight immediately. The transient indicator near the crosshair should confirm the change.

---

### 12. Contextual Controls Panel

This section dynamically shows what the current tool's mouse buttons and modifier keys do. It replaces the old TOOL_HINTS system with a more readable and always-visible layout.

#### Layout (Example: Sculpt tool, aiming at floor)

```
┌──────────────────────────────┐
│ ▁ CONTROLS                  │
│ LMB      Raise floor         │
│ RMB      Lower floor         │
│ Scroll   Extend              │
│ Sh+Scrl  Snap grid           │
│                              │
│ T=ceil  R=reset  Del=clear   │
│ G=snap                       │
└──────────────────────────────┘
```

#### Context Sensitivity

The controls section changes based on:
1. **Current tool** — Each tool has different LMB/RMB/MMB/Scroll meanings.
2. **Current aim target** — The sculpt tool shows different actions for floor vs. ceiling.
3. **Current selection state** — The select tool shows different actions depending on whether 0, 1, or 2 corners are set.

#### Visual Formatting

- **Key labels** (LMB, RMB, Scroll, etc.) are shown in warm gold text (`#CCC080`) at the left, with a fixed width column (72px).
- **Descriptions** are shown in default text, right of the key column, with word wrapping.
- **Extra shortcuts** (T=ceil, R=reset, etc.) are shown in a dimmer olive text on a separate line.

This section is **not** inside a collapsing header. It is always visible and always up-to-date. It is the user's cheat sheet — the thing they look at when they forget what RMB does.

---

### 13. Display Toggles

Display toggles control what visual elements overlay the 3D viewport. They are presented as a compact 2-column checkbox layout:

```
┌──────────────────────────────┐
│ ▁ DISPLAY                   │
│ ☑ Walls         ☑ Floor Grid │
│ ☑ Ceil Grid     ☐ Axes       │
└──────────────────────────────┘
```

Each checkbox is labeled concisely. They are **always visible** (not inside a collapsing header). They correspond to:

| Checkbox | State Variable | Keyboard | Default |
|----------|---------------|----------|---------|
| Walls | `ed.show_walls` | V | On |
| Floor Grid | `ed.show_grid` | F2 | On |
| Ceil Grid | `ed.show_ceiling_grid` | F3 | Off |
| Axes | `ed.show_axes` | F4 | Off |

*(Proposed additions for v2:)*
| Checkbox | State Variable | Keyboard | Default |
|----------|---------------|----------|---------|
| Light Levels | `ed.show_light` | L | Off |
| Entity Markers | `ed.show_entities` | — | Off |
| Portal Zones | `ed.show_portals` | — | Off |

---

### 14. Zone Browser

The zone browser is a scrollable list of all `.zone` files in the `zones/` directory. It allows the user to switch between zones without using the file system.

#### Layout

```
┌──────────────────────────────┐
│ ▁ ZONES                     │
│ [+ New Zone                 ]│
│   campsite                   │
│   crossroads                 │
│ ▸ pawn_shop                  │  ← Currently loaded (gold text, arrow prefix)
│   playground                 │
│   showcase                   │
│   ...                        │
└──────────────────────────────┘
```

#### Behavior

| Interaction | Effect |
|-------------|--------|
| Click a zone name | If the current zone is dirty, show "Save changes?" dialog. Then load the clicked zone. |
| Click "+ New Zone" | Opens New Zone dialog. |
| Double-click a zone | *(Proposed)* Loads the zone AND enters Edit Mode immediately. |
| Right-click a zone | *(Proposed)* Context menu: Rename, Duplicate, Delete, Show in Explorer. |

#### Dirty Guard

**Critical improvement:** In the current version, clicking a different zone in the list immediately loads it, discarding unsaved changes with no warning. In v2, switching zones with unsaved changes must trigger the Unsaved Changes Guard (Section 35).

---

## Part IV — Right Panel (Inspector)

The right panel provides detailed read-only information about the zone and the cell currently under the crosshair. It should update every frame during Edit Mode to always reflect the current aim target.

---

### 15. Zone Header & Metadata

Always visible at the top of the right panel:

```
┌──────────────────────────────┐
│ pawn_shop •                  │  ← Zone name + dirty bullet
│ 20 × 20                     │  ← Dimensions
├──────────────────────────────┤
```

- The zone name is shown in warm gold text.
- A bullet (`•`) suffix appears when dirty (unsaved changes).
- Dimensions are shown in gray text below.
- A horizontal separator line divides this from the cell inspector.

---

### 16. Cell Inspector (Live)

The cell inspector is the heart of the right panel. It shows every property of the cell currently under the crosshair, updating in real time as the user moves the camera.

#### When No Cell is Aimed

```
┌──────────────────────────────┐
│ Aim at a cell to inspect     │  ← Gray hint text
└──────────────────────────────┘
```

#### When a Cell is Aimed

```
┌──────────────────────────────────┐
│ ▼ Cell (3, 7)                    │  ← Collapsing header, default open
│                                  │
│ grass                 OPEN       │  ← Tile name + type badge
│                                  │
│ Floor    0.25                    │  ← Green text if at ground level
│ Ceil     SKY                     │  ← Blue "SKY" badge if sky
│ Gap      9.75                    │  ← Red if < 0.5
│                                  │
│ Upper wall   0.00                │  ← Only if > 0
│                                  │
│ Wall   brick_dark                │  ← Texture override (or "—" if none)
│ Floor  concrete                  │
│ Ceil   —                         │
│                                  │
│   N  brick_dark                  │  ← Per-face overrides
│   S  brick_light                 │
│   E  —                           │
│   W  —                           │
│                                  │
│ ▶ Segments (2 faces)             │  ← Collapsed by default, auto-opens if segments present
│     N  brick_dark @ 0.25         │
│     N  concrete @ 0.50           │
│                                  │
│ ▸ Floor Surface ◄                │  ← Aimed surface indicator (colored)
│   Brush: brick_dark              │  ← What would be painted
│   Current: concrete              │  ← What's currently on this surface
└──────────────────────────────────┘
```

#### Color Coding

| Value | Color | Condition |
|-------|-------|-----------|
| Floor height | Green | At ground (0.00) |
| Floor height | Blue | Negative (below ground) |
| Floor height | Default | Positive |
| Ceil height | Blue | "SKY" when ≥ 9.99 |
| Gap | Red | < 0.5 (too small for player) |
| Type badge "WALL" | Red-ish | Wall cell |
| Type badge "OPEN" | Green | Open (floor) cell |
| Texture names | Default | When present |
| Texture names "—" | Dim gray | When no override |

#### Aimed Surface Indicator

At the bottom of the cell inspector, a colored line shows exactly which surface the crosshair is pointing at:

- **Floor surface**: Green text "▸ Floor Surface"
- **Ceiling surface**: Blue text "▸ Ceiling Underside"
- **Wall face (N/S/E/W)**: Amber text "▸ N Wall Face"
- **Floor step face**: Green text "▸ Floor N Step"
- **Ceiling step face**: Blue text "▸ Ceil S Step"

If the paint tool is active, also show:
- **Brush:** (what the user's current texture is)
- **Current:** (what texture is currently on this surface)

This dual display is critical for previewing paint actions — the user can see "I'm about to paint brick_dark on a surface that currently has concrete" before clicking.

---

### 17. Face Detail Inspector

*(Proposed for v2 — current version doesn't have this)*

When the user is aimed at a face that has segments, an expanded view shows each segment band:

```
┌───────────────────────────────┐
│ ▼ Segments — N Face           │
│                               │
│ Band 0: brick_dark            │
│    0.00 → 0.25                │
│ Band 1: concrete    ◄         │  ← Currently aimed band
│    0.25 → 0.50                │
│ Band 2: brick_light           │
│    0.50 → 1.00                │
└───────────────────────────────┘
```

The currently aimed band (determined by crosshair Y) is highlighted with a `◄` marker. Each band shows its texture and its Y range.

---

### 18. Zone Settings (Editable)

The zone settings section is now **default-open** (was collapsed by default in the current version). It contains editable fields for zone-level properties.

#### Layout

```
┌──────────────────────────────┐
│ ▼ Zone Settings              │
│                              │
│ Size      20 × 20            │  ← Read-only display
│                              │
│ Anchor                       │
│   Row  [  10.0  ]            │  ← Input fields
│   Col  [  10.0  ]            │
│ [Set to Camera]              │  ← Button
│                              │
│ ☑ First Person               │  ← Checkbox
│                              │
│ *(Proposed)*                 │
│ ☐ Interior                   │  ← Controls raycaster interior mode
│ [Resize Zone...]             │  ← Opens resize dialog
└──────────────────────────────┘
```

All editable fields set `self.dirty = True` on change, which the existing code already handles.

The "Set to Camera" button copies the 3D editor's camera XZ position to the spawn anchor — useful for placing the spawn point exactly where the user is standing.

---

### 19. Camera Info

The camera info section shows the 3D editor camera's position and orientation. It is **default-open** (was collapsed by default in the current version).

#### Layout

```
┌──────────────────────────────┐
│ ▼ Camera                     │
│                              │
│ X     5.23                   │
│ Y     0.50                   │
│ Z     7.89                   │
│ Yaw   135°                   │
│ Pitch -12°                   │
└──────────────────────────────┘
```

Values update every frame during Edit Mode. Useful for debugging spawn points and for level designers who need to reproduce exact camera positions.

---

## Part V — Status Bar

---

### 20. Status Bar — The Constant Truth

The status bar is a 28px strip at the bottom of the window. It serves as a **persistent truth line** — a glance-friendly summary of the most important state:

#### Layout

```
┌──────────────────────────────────────────────────────────────────┐
│ pawn_shop•  20×20  3D EDITOR  SCULPT  Snap:1/4  Tex:brick_dark  │  ← Left-aligned items
│                                                     ● EDITING  │  ← Right-aligned
└──────────────────────────────────────────────────────────────────┘
```

Each item uses `same_line()` spacing (no hard-coded pixel positions — they flow left to right with spacing between them). Items that don't fit the current window width are gracefully hidden (right-side items first).

#### Status Bar Elements

| Element | Color | Shown When |
|---------|-------|------------|
| Zone name | Warm gold `(0.90, 0.85, 0.65)` | Always (if zone loaded) |
| Dirty bullet `•` | Same as name | When unsaved changes exist |
| Dimensions `20×20` | Gray disabled text | Always |
| View mode `3D EDITOR` / `RAYCASTER` | Blue `(0.45, 0.75, 1.0)` | Always |
| Tool name `SCULPT` | Tool color | 3D mode only |
| Snap value `Snap:1/4` | Gray disabled | 3D mode only |
| Current texture `Tex:brick_dark` | Gray disabled | When using texture tools |
| Current preset `Model:Brick Room` | Gray disabled | When using model tool |
| Aimed cell `Cell:(3,7)` | Gray disabled | When aiming at a cell |
| Noclip badge `NOCLIP` | Red | Raycaster mode, noclip active |
| Edit mode badge `● EDITING` | Bright green | When mouse is captured |
| *(No zone)* `Select or create a zone to begin` | Gray disabled | When no zone is loaded |

The `● EDITING` badge is right-aligned using `imgui.calc_text_size()` to compute the label width, ensuring it doesn't overlap with other items regardless of window width.

---

## Part VI — Viewport & Interaction Model

---

### 21. Viewport Rendering

The viewport fills all space between the left panel, right panel, menu bar, and status bar. It renders one of two views:

#### 3D Wireframe Editor

The primary editing view. Software-rendered filled boxes with face shading, backface culling, and depth sorting. Shows:
- Grid lines (floor and/or ceiling)
- Cell boxes with per-face coloring based on texture
- Segment boundary markers (orange rings)
- Selection highlight (gold overlay)
- Crosshair with tool-colored tinting
- Action context text near crosshair
- HUD *(optional — may be replaced by ImGui panels)*

#### Raycaster Preview

A 2.5D first-person view rendered by the C raycaster extension. Shows:
- Textured walls, floors, and ceilings as they appear in-game
- Step geometries (raised floors, lowered ceilings)
- Segment texturing (multi-band walls)
- Player collision (with noclip toggle)

The raycaster renders to a smaller surface (640×360 by default) which is then scaled up to fill the viewport. This keeps the raycaster fast even on large viewports.

---

### 22. Crosshair & Aim Feedback

The crosshair is the center point of the viewport. It tells the user what they're pointing at and what will happen when they click.

#### Crosshair Appearance

- **Shape:** A small cross (`+`) with a 2px gap at center (so the exact center pixel is visible).
- **Color:** Matches the current tool's color.
- **Size:** 12px arms (24px total span).

#### Aim Indicator

Below and/or to the right of the crosshair, the **aimed cell** and **aimed surface** are shown in small text:

```
         +            ← Crosshair (tool colored)
     (3, 7) floor     ← Cell and part (small white text)
```

This is drawn directly onto the viewport surface by `_draw_action_context()`.

---

### 23. The Action Context Display

The **Action Context Display** is a small, context-sensitive label rendered near the crosshair that tells the user exactly what their next click will do. This is the most important visibility improvement proposed for v2.

#### Examples by Tool

| Tool | Aim Target | Action Context |
|------|-----------|---------------|
| Sculpt | Floor | `▲ Raise Floor +0.25` (for LMB) |
| Sculpt | Ceiling | `▼ Lower Ceiling −0.25` (for LMB) |
| Paint | Wall N face | `🎨 Paint: brick_dark → N Face` |
| Fill | Floor surface | `🪣 Fill: brick_dark` |
| Erase | Any cell | `✖ Reset Cell (3, 7)` |
| Detail | Wall N face | `✂ Split at Y=0.37` |
| Select | No selection | `◻ Set Corner 1` |
| Select | 1 corner set | `◻ Set Corner 2` |
| Select | Active selection | `◻ Fill: brick_dark (24 cells)` |
| Model | Any cell | `⬢ Stamp: Brick Room` |

The action context uses simple icons (Unicode characters) and concise descriptions. It's rendered in a semi-transparent background pill so it's legible against any viewport content.

#### Positioning

The action context should appear **below and slightly right** of the crosshair, with enough offset to not overlap the crosshair itself:

```
              +
                ┌─────────────────────┐
                │ ▲ Raise Floor +0.25 │
                └─────────────────────┘
```

It's rendered directly on the viewport surface (not as ImGui), so it's always visible during Edit Mode.

---

### 24. Ghost Preview System

*(Proposed for v2 — would require rendering additions)*

Ghost previews show the user what the result of their click will look like *before* they click. This is most important for the sculpt and stamp tools.

#### Sculpt Ghost

When the sculpt tool is active and aiming at a floor, a **translucent green plane** appears at the height the floor will reach after LMB click:

```
Current floor: 0.25
Snap: 0.25
Ghost shows a plane at: 0.50 (current + snap)
```

When aiming at a ceiling, a **translucent blue plane** appears at the new ceiling height.

#### Stamp Ghost

When the model tool is active, the aimed cell's box could be overlaid with a **translucent preview** of what the preset will produce — showing the resulting heights, wall type, and dominant texture color.

#### Paint Ghost

When the paint tool is active, the aimed face could briefly flash the current texture's color swatch, providing a "before painting" indication. This is less critical than sculpt/stamp ghosts but still useful.

---

## Part VII — Tool-by-Tool Specification

Each tool section below describes:
- **Purpose**: What the tool is for.
- **Mouse Actions**: What each mouse button does.
- **Scroll Actions**: What scrolling does.
- **Key Modifiers**: What Shift/Ctrl/Alt change.
- **Visual Feedback**: What the user sees while using the tool.
- **Edge Cases**: Unusual behaviors and boundary conditions.
- **Current Limitations**: What doesn't work yet and should.
- **Proposed Improvements**: What v2 should add.

---

### 25. Sculpt Tool — Complete Specification

**Purpose:** Shape the 3D geometry of cells by raising/lowering floors and ceilings.

**Number Key:** 1

**Crosshair Color:** Warm amber `(220, 160, 60)`

#### Mouse Actions

| Button | Floor Target | Ceiling Target | No Target |
|--------|-------------|---------------|-----------|
| **LMB** | Raise floor by `snap_y` | Lower ceiling by `snap_y` | No action |
| **RMB** | Lower floor by `snap_y` | Raise ceiling by `snap_y` (caps at SKY_HEIGHT) | No action |
| **MMB** | Paint aimed face with current texture | Paint aimed face with current texture | No action |

#### Scroll Actions

| Scroll | Floor Target | Ceiling Target | +Shift |
|--------|-------------|---------------|--------|
| **Up** | Extend floor upward by `snap_y` | Raise upper wall height | Cycle snap up |
| **Down** | Extend floor downward by `snap_y` | Lower upper wall height | Cycle snap down |

**Extend** is distinct from raise/lower: it changes height without triggering auto-segmentation and without pushing the opposite surface. It's a "smooth adjust" operation.

#### Key Modifiers

| Key | Condition | Action |
|-----|-----------|--------|
| `T` | Aimed at any cell | Toggle ceiling: if sky → create ceiling at DEFAULT_CEIL. If ceiling exists → set to SKY_HEIGHT (remove). |
| `R` | Aimed at floor | Reset floor to DEFAULT_FLOOR (0.0). Clear floor step segments. |
| `R` | Aimed at ceiling | Reset ceiling to DEFAULT_CEIL (1.0). Clear upper wall height. |
| `U` | Aimed at ceiling | Raise upper wall height by snap_y. |
| `Shift+U` | Aimed at ceiling | Lower upper wall height by snap_y. |
| `Ctrl+U` | Aimed at ceiling | Reset upper wall height to 0.0. |
| `Delete` | Any aimed cell | Full cell reset (flat ground, sky, clear all textures/segments). |

#### Visual Feedback

- **Crosshair:** Amber cross at viewport center.
- **Face highlight:** Translucent white overlay on the aimed face/segment.
- **Height markers:** Green wireframe ring at non-default floor heights, blue ring at ceiling heights.
- **Action context:** Shows "▲ Raise Floor +0.25" or "▼ Lower Ceiling −0.25" etc.
- **Inspector:** Right panel shows floor/ceiling heights, gap, and type badge in real time.

#### Edge Cases

| Condition | Behavior |
|-----------|----------|
| Floor raised to meet ceiling | Cell becomes geometry-solid (impassable). Auto-converts to wall tile. |
| Floor lowered to 0.0 | All floor step segments and textures are cleared (they exist below ground and would be invisible). |
| Ceiling raised to SKY_HEIGHT | Ceiling step segments and textures are cleared. Upper wall height is cleared. Cell becomes open-sky. |
| Floor raised above ceiling | Ceiling is pushed upward to maintain at least `snap_y` gap (prevents impossible geometry). |
| Ceiling lowered below floor | **Not allowed.** Lower is capped at floor + 0.01. |

#### Segment Auto-Management

When the floor is raised, the sculpt tool automatically adds a segment boundary at the old floor height on all four floor step faces. This ensures the newly exposed step wall has a visible texture division at the transition point. The auto-segmentation uses the current texture for the new top band and preserves the old texture for the lower band.

When the floor is lowered, segment boundaries above the new floor height are trimmed:
- Boundaries that were between old_floor and new_floor are removed.
- The topmost remaining segment's upper bound is clamped to the new floor height.
- If the floor returns to ground level (0.0), all floor step segments are cleared entirely.

Analogous rules apply for ceiling raise/lower and ceiling step segments.

#### Current Limitations

1. No preview of the resulting height (ghost plane) before clicking.
2. Extend-floor via scroll has no undo grouping — each scroll tick is a separate undo entry. Should group rapid scrolls into one entry.
3. Upper wall height adjustment (U key) is not discoverable — needs UI representation.

#### Proposed Improvements

1. **Height preview:** Show a translucent plane at the target height before clicking.
2. **Scroll undo grouping:** If multiple scroll ticks occur within 500ms, group them into one undo entry.
3. **Upper wall slider:** In the inspector, show an editable slider for upper wall height when aimed at a ceiling.
4. **Multi-cell sculpt:** Hold Ctrl and drag to raise/lower a line of cells in one stroke.

---

### 26. Paint Tool — Complete Specification

**Purpose:** Apply textures to cell surfaces without changing geometry.

**Number Key:** 2

**Crosshair Color:** Soft purple `(200, 120, 220)`

#### Mouse Actions

| Button | Action |
|--------|--------|
| **LMB** | Paint the aimed face with the current texture. Supports **click-and-drag**: holding LMB and moving the camera paints every face the crosshair passes over, as one undo group. |
| **RMB** | Erase the texture override on the aimed face (revert to default/empty string). |
| **MMB** | Eyedropper: pick the texture from the aimed face and set it as the current texture. The palette scrolls to the picked texture. |

#### Scroll Actions

| Scroll | Action |
|--------|--------|
| **Up** | Cycle to next texture in palette |
| **Down** | Cycle to previous texture in palette |

#### Click-and-Drag Painting

This is one of the most important features of the paint tool. When the user holds LMB and moves the camera, every face that passes under the crosshair gets painted. The entire drag stroke counts as **one undo operation** — undoing it reverts all painted faces at once.

**Implementation:** On LMB down, `_push_undo()` is called once. Then `_lmb_held = True`. On every `update()` frame where `_lmb_held` is True, `_paint_continuous()` is called, which paints without pushing another undo. On LMB up, `_lmb_held = False`.

#### Paint Target Resolution

The paint tool is context-aware about which surface/face it paints:

| Aim Target | What Gets Painted |
|------------|------------------|
| Wall cell, face N/S/E/W | `face_textures[r][c][face_idx]` |
| Wall cell, face N/S/E/W with segments | The specific segment band at the crosshair's Y height |
| Open cell, floor top surface | `floor_textures[r][c]` |
| Open cell, ceiling bottom surface | `ceil_textures[r][c]` |
| Open cell, floor step face N/S/E/W | `floor_step_textures[r][c][face_idx]` |
| Open cell, floor step face with segments | The specific floor step segment band |
| Open cell, ceiling step face N/S/E/W | `ceil_step_textures[r][c][face_idx]` |
| Open cell, ceiling step face with segments | The specific ceiling step segment band |
| Ground (no cell) | No action |

#### Visual Feedback

- **Crosshair:** Purple cross.
- **Face highlight:** White translucent overlay on the aimed face/segment band.
- **Action context:** "🎨 Paint: brick_dark → Floor Surface" or similar.
- **Brush bar:** Shows current texture name and swatch.
- **Inspector:** Shows "Brush: brick_dark" and "Current: concrete" at the bottom of the cell inspector.

#### Current Limitations

1. `wall_textures[r][c]` is updated alongside `face_textures` on wall cells (for backwards compatibility). This is wasteful and could be simplified.
2. No visual preview of the texture on the face before painting (the face highlights in white, not in the texture color).
3. Can't paint multiple disconnected faces in one stroke (e.g., painting one face, lifting over a gap, painting another face — each creates a separate undo group).

#### Proposed Improvements

1. **Texture preview on face:** When hovering over a face with the paint tool, show the texture's color swatch on the face highlight instead of white.
2. **Multi-select paint:** After making a rectangular selection with the select tool, switching to paint and clicking could paint all selected cells at once.
3. **Recent textures:** A "recently used" row above the palette for quick access to the last 5-10 textures.

---

### 27. Fill Tool — Complete Specification

**Purpose:** Flood-fill connected surfaces of the same height with a texture.

**Number Key:** 3

**Crosshair Color:** Teal `(80, 200, 200)`

#### Mouse Actions

| Button | Action |
|--------|--------|
| **LMB** | Flood fill: paint all connected same-texture cells with the current texture. |
| **RMB** | Flood clear: reset all connected same-texture cells to empty string. |

#### Scroll Actions

| Scroll | Action |
|--------|--------|
| **Up/Down** | Cycle texture palette (same as paint tool). |

#### Flood Fill Algorithm (BFS)

1. Determine the **fill mode** from the aim target (floor_top, ceil_top, wall_face, floor_step, ceil_step).
2. Record the **origin texture** (what the aimed cell currently has).
3. Record the **reference height** (floor or ceiling height of the aimed cell).
4. BFS outward from the aimed cell to all adjacent cells that satisfy ALL of:
   - Same fill mode is applicable (e.g., both cells have floor surfaces).
   - Same reference height (within 0.01 tolerance).
   - Same origin texture (only fills same-colored regions).
   - Same wall/open status (fill doesn't cross wall/open boundaries).
   - No segment boundaries on the shared face between the two cells.
   - Within grid bounds.
5. Write the current texture to every cell in the fill region.
6. Push one undo entry covering the entire fill.

#### Fill Stops At

| Boundary | Reason |
|----------|--------|
| Height discontinuity | Floors or ceilings at different levels are different surfaces. |
| Wall/open transition | A wall cell next to an open cell are fundamentally different. |
| Segment boundary | If the shared face between two cells has segments, the fill stops (the boundary is "textured" differently). |
| Grid edge | Can't fill outside the map. |
| Different origin texture | Only fills cells that match the clicked cell's current texture. |

#### Visual Feedback

- **Crosshair:** Teal cross.
- **Action context:** "🪣 Fill: brick_dark" or "🪣 Clear" for RMB.
- **No preview** of the fill region before clicking. *(Proposed improvement: show a highlighted boundary of the fill region on hover.)*

#### Current Limitations

1. No preview of how many cells will be affected.
2. Fill on wall faces only fills the same face direction (e.g., all North faces). It doesn't wrap around corners.
3. Large fills on big zones could be slow (BFS is pure Python).

#### Proposed Improvements

1. **Fill preview:** When hovering (not clicking), show a translucent overlay on all cells that would be filled. This could be computed lazily (only when the aimed cell changes) and cached.
2. **Fill metrics:** Show "Would fill 15 cells" in the action context.
3. **Connected fill mode option:** Fill across height differences (useful for painting large multi-level floors the same color).

---

### 28. Eraser Tool — Complete Specification

**Purpose:** Quickly reset cells to default state.

**Number Key:** 4

**Crosshair Color:** Danger red `(220, 80, 80)`

#### Mouse Actions

| Button | Modifier | Action |
|--------|----------|--------|
| **LMB** | None | Full cell reset: flat ground (0.0), sky ceiling (10.0), clear all textures, clear all segments, convert to open tile. |
| **LMB** | Shift | Texture-only reset: clear all texture overrides on the cell (face textures, wall texture, floor texture, ceiling texture, step textures). Geometry unchanged. |
| **RMB** | None | Height-only reset: if aimed at ceiling → set to SKY_HEIGHT and clear ceil segments. If aimed at floor → set to DEFAULT_FLOOR and clear floor segments. Textures unchanged. |

#### Visual Feedback

- **Crosshair:** Red cross — clearly signaling destructive action.
- **Action context:** "✖ Reset Cell (3, 7)" for LMB, "✖ Reset Heights" for RMB, "✖ Clear Textures" for Shift+LMB.
- **Modifier awareness:** When Shift is held, the action context should change to preview the modified action.

#### Current Limitations

1. Shift+LMB variant is not discoverable (no UI indicator that Shift modifies the eraser).
2. No way to erase only floor or only ceiling textures individually.

#### Proposed Improvements

1. **Modifier badge:** When Shift is held, the ERASER tool button in the left panel should show a small "TEX" badge indicating the modified mode.
2. **Confirmation for multi-erase:** If the select tool has an active selection and the user presses Delete, show a count "Reset 24 cells?" before proceeding.
3. **Undo preview:** Before erasing, briefly highlight the cell in red to confirm the target.

---

### 29. Segment (Detail) Tool — Complete Specification

**Purpose:** Subdivide cell faces vertically into multiple texture bands ("segments"), enabling multi-texture walls like wainscoting, brick-over-plaster, or facade patterns.

**Number Key:** 5

**Crosshair Color:** Orange `(255, 180, 60)`

#### Mouse Actions

| Button | Action |
|--------|--------|
| **LMB** | Split: add a new horizontal divider at the crosshair's Y position (snapped to snap_y grid). Creates two bands where there was one. |
| **RMB** | Merge: remove the horizontal divider nearest to the crosshair's Y position. Collapses two bands into one (keeping the lower band's texture). |
| **MMB** | Paint: apply the current texture to the specific segment band that the crosshair is inside of. |

#### Scroll Actions

| Scroll | Action |
|--------|--------|
| **Up/Down** | Cycle texture palette. |

#### Segment Data Model

Each cell face (N, S, E, W) has a list of segments. Each segment is `[texture_key, y_top]`. The list is sorted bottom-to-top. The bottom of the first segment is the face's base height (floor height or ceiling height). The top of the last segment is the face's top height.

```
Face: North wall, height 0.0 to 1.0
Segments: [
    ["brick_dark", 0.5],     ← Bottom half: brick_dark (0.0 to 0.5)
    ["plaster_white", 1.0],  ← Top half: plaster_white (0.5 to 1.0)
]
```

An empty segments list `[]` means the face has no subdivisions (uses the face's single texture override).

Segments exist on three types of faces:
- **Wall segments** (`wall_segments`): On wall cells' N/S/E/W faces.
- **Floor step segments** (`floor_step_segments`): On the vertical step walls created when a floor is raised above ground.
- **Ceiling step segments** (`ceil_step_segments`): On the vertical step walls created when a ceiling is lowered.

#### Split Constraints

- The split Y must be at least 0.01 above the face bottom and 0.01 below the face top.
- The split Y is snapped to the current snap_y grid.
- If the split Y coincides with an existing boundary (within 0.01), the split is rejected (no duplicate boundaries).

#### Merge Behavior

- Finds the existing boundary nearest to the crosshair Y.
- Removes that boundary, merging the two adjacent bands.
- The merged band inherits the **lower** band's texture.
- If removing the boundary leaves only one band, the segments list for that face is cleared entirely (reverts to single-texture mode).

#### Visual Feedback

- **Crosshair:** Orange cross.
- **Segment boundary markers:** Orange horizontal rings on all faces that have segments.
- **Aimed segment highlight:** The specific band the crosshair is inside gets a white translucent overlay.
- **Action context:** "✂ Split at Y=0.37" or "⊕ Merge boundary" or "🎨 Paint band #2".
- **Inspector:** Shows segment details (band list, textures, Y ranges).

#### Current Limitations

1. No visual preview of where the split will occur (no horizontal line at the proposed split Y).
2. Segment textures don't have per-segment color visualization in the 3D wireframe — they all show the base wall color. Only the raycaster preview shows actual textures.
3. Floor step segments require floor height > 0.02. Ceiling step segments require ceiling mass depth > 0.02. These minimums are not communicated to the user.
4. No way to move/adjust a split boundary after creation — must merge and re-split.

#### Proposed Improvements

1. **Split preview line:** When hovering with the segment tool, show a horizontal dashed line at the snap-aligned Y position where the split would occur.
2. **Segment colors in 3D:** Render each segment band with its texture's color swatch in the wireframe view (currently only one color per face).
3. **Boundary drag:** Hold LMB on a boundary marker to drag it to a new Y position. This is more intuitive than merge + re-split.
4. **Copy segment pattern:** Ctrl+Click to copy one face's segment pattern/textures to another face.

---

### 30. Select Tool — Complete Specification

**Purpose:** Define rectangular regions and perform batch operations on them.

**Number Key:** 6

**Crosshair Color:** Gold `(255, 220, 100)`

#### Mouse Actions — Three-Phase Workflow

| Phase | LMB | RMB | Scroll |
|-------|-----|-----|--------|
| **No selection** | Set first corner at aimed cell | — | Cycle texture (for later fill) |
| **1 corner set** | Set second corner (completes rectangle) | — | Cycle texture |
| **Active selection** | Fill all selected cells/faces with current texture | Clear all texture overrides in selection | Raise/lower all selected heights by snap_y |

#### Floor/Ceiling Mode Toggle

The `X` key toggles between **Floor Mode** and **Ceiling Mode**. This affects:
- Scroll (raises/lowers floors vs ceilings)
- Fill (paints floor surfaces vs ceiling surfaces)
- Delete (which heights get reset)

The current mode is indicated by a colored badge in the left panel:
- `FLOOR MODE` in green text
- `CEILING MODE` in blue text

#### Delete In Selection

`Delete` / `Backspace` with an active selection resets ALL cells in the selection via `reset_cell()`:
- Floor → 0.0
- Ceiling → SKY_HEIGHT (10.0)
- All textures → cleared
- All segments → cleared
- Tile → open

#### Visual Feedback

- **Selection highlight:** A gold wireframe overlay on all selected cells, visible from any angle.
- **Corner markers:** Bright nodes at the selection's corners.
- **Area count:** "◻ 24 cells selected" in the controls section.
- **Mode indicator:** "FLOOR MODE" or "CEILING MODE" badge.

#### Height Adjustment Rules

When scrolling with an active selection:
- **Floor mode, scroll up:** Raise all selected floors by `snap_y`. If any floor meets its ceiling, the ceiling is pushed up too.
- **Floor mode, scroll down:** Lower all selected floors by `snap_y`. Floors are clamped to `FLOOR_MIN`.
- **Ceiling mode, scroll up:** Raise all selected ceilings by `snap_y`. Ceilings are capped at `SKY_HEIGHT`.
- **Ceiling mode, scroll down:** Lower all selected ceilings by `snap_y`. Ceilings are clamped above their floors.

#### Current Limitations

1. No selection preview (no visual indication of the selection shape before completing it).
2. Can't resize a selection after setting both corners — must cancel and restart.
3. No copy/paste of selected regions.
4. No move/shift of selected region heights relative to their current values (only absolute set).

#### Proposed Improvements

1. **Selection resize handles:** Drag corners/edges to resize the selection after creation.
2. **Copy/Paste:** Ctrl+C copies the selected region's geometry + textures. Ctrl+V enters a "paste mode" where the mouse cursor becomes a stamp and clicking places the copied region.
3. **Selection operations menu:** Right-click on selection → context menu with: Fill, Clear, Reset, Raise +0.25, Lower -0.25, Set Height To..., Mirror Horizontal, Mirror Vertical.
4. **Additive selection:** Shift+Click to add cells to the existing selection (non-rectangular).

---

### 31. Stamp (Model) Tool — Complete Specification

**Purpose:** Apply saved cell presets ("models") to cells, or capture cells as new presets.

**Number Key:** 7

**Crosshair Color:** Violet `(180, 140, 255)`

#### Mouse Actions

| Button | Action |
|--------|--------|
| **LMB** | Apply: stamp the current preset onto the aimed cell using the active apply mode. |
| **RMB** | Capture: begin naming a new preset from the aimed cell. Type a name and press Enter to save. |

#### Scroll Actions

| Scroll | Action |
|--------|--------|
| **Up** | Cycle to next preset in palette |
| **Down** | Cycle to previous preset in palette |

#### Key Actions

| Key | Action |
|-----|--------|
| **M** | Cycle apply mode: replace → stack\_floor → stack\_ceil → merge |

#### Apply Modes

| Mode | Behavior |
|------|----------|
| `replace` | Overwrite the cell with all non-None preset fields. Default mode. |
| `stack_floor` | Add the preset's `floor_height` on top of the cell's current floor. Creates a step segment at the old floor height. Good for platforms, counters. |
| `stack_ceil` | Subtract the preset's `floor_height` from the ceiling downward. Creates a hanging segment. |
| `merge` | Only apply fields that are currently at their default values in the cell. Non-default fields are left untouched. |

The current mode is shown in the HUD below the preset name.

#### Apply Behavior

`apply_preset(zone, r, c, preset, mode_override=...)` dispatches to one of four mode functions. Each writes non-None preset fields to the cell. The fields include:

| Preset Field | Zone Target |
|-------------|-------------|
| `floor_height` | `floor_heights[r][c]` ; also derives tile type (wall when floor ≥ ceil) |
| `floor_height` | `floor_heights[r][c]` |
| `ceil_height` | `ceil_heights[r][c]` |
| `upper_wall_height` | `upper_wall_height[r][c]` |
| `floor_texture` | `floor_textures[r][c]` |
| `ceil_texture` | `ceil_textures[r][c]` |
| `wall_texture` | `wall_textures[r][c]` |
| `face_textures` | `face_textures[r][c]` |
| `floor_step_textures` | `floor_step_textures[r][c]` |
| `ceil_step_textures` | `ceil_step_textures[r][c]` |
| `wall_segments` | `wall_segments[r][c]` |
| `floor_step_segments` | `floor_step_segments[r][c]` |
| `ceil_step_segments` | `ceil_step_segments[r][c]` |

This "None = leave unchanged" design allows presets that only affect certain aspects of a cell — e.g., a "brick walls" preset that changes wall textures and segments but leaves heights alone.

#### Capture Behavior

`capture_preset()` reads every field from the aimed cell and creates a `CellPreset` object. Capture is **intentional** — it requires naming:

1. Press RMB → editor enters capture-naming mode.
2. HUD shows **CAPTURE NAME:** with a blinking cursor.
3. Type a name and press Enter (or Escape to cancel).
4. The preset is assigned the current apply mode.
5. Registered in `PRESET_REGISTRY`.
6. Saved to disk as `data/presets/{id}.toml`.
7. Auto-selected in the palette.

Empty names cancel the capture. This friction prevents accidental preset proliferation.

#### Visual Feedback

- **Crosshair:** Violet cross.
- **HUD panel:** Shows current preset name, apply mode (`M` to cycle), and capture-name prompt when active.
- **Action context:** "⬢ Stamp: Brick Wall" for LMB, "📷 Capture → name" for RMB.

#### Current Limitations

1. **Single-cell only:** Presets capture and apply exactly one cell. No multi-cell stamps.
2. **No preview:** No visual indication of what the stamp will produce.
3. **No editing presets:** Once captured, a preset can't be renamed or re-categorized from the editor. Must edit the TOML file manually.
4. **No delete:** Can't delete presets from within the editor.
5. **No undo for capture:** Registering a preset writes to disk immediately. Can't undo.

#### Proposed Improvements

1. **Multi-cell blueprint:** Capture a rectangular selection as a multi-cell preset ("blueprint"). Apply by clicking the top-left corner and stamping the entire region. This would make the stamp tool genuinely powerful for room construction.
2. **Capture dialog:** When RMB captures a cell, show a small dialog: "Name: [___] Category: [dropdown] [Save] [Cancel]". With a dismiss option for power users who want instant capture.
3. **Preset editor:** A collapsible section in the left panel where the user can rename, re-categorize, and delete presets.
4. **Stamp preview:** When aimed at a cell with the model tool, overlay a translucent preview (colored wireframe) of what the preset will produce at that location.
5. **Preset thumbnails:** *(Advanced)* Render a small 3D thumbnail of each preset for the palette list.

---

## Part VIII — Raycaster Preview Mode

---

### 32. Preview Mode — First Person Walkthrough

The raycaster preview lets the user walk through their zone in first-person to check sightlines, proportions, lighting, and textures.

#### Entering/Exiting

| Trigger | From | To |
|---------|------|----|
| Tab | 3D Editor (Edit Mode) | Raycaster Preview (Edit Mode) |
| Tab | Raycaster Preview (Edit Mode) | 3D Editor (Edit Mode) |

Camera position transfers between views (with coordinate system adjustments).

#### Controls

| Input | Action |
|-------|--------|
| W/A/S/D | Walk forward/strafe/backward/strafe |
| Mouse | Look around (yaw + pitch) |
| Shift | Sprint (2× speed) |
| Ctrl | Slow walk (0.3× speed) |
| I | Toggle interior rendering |
| G | Toggle noclip (walk through walls) |

#### Collision System

- Circle-vs-grid collision (radius 0.2 tiles).
- X and Z axes tested independently (allows wall-sliding).
- Floor height tracking with smooth lerp (camera doesn't snap).
- Step-up tolerance: can climb steps ≤ 0.5 height units.
- Head clearance check: ≥ 0.4 height units of space required.

#### Pitch Limits

Pitch is clamped to ±54° (π × 0.30 radians) to prevent extreme distortion at high angles. When switching from 3D editor (which allows ±81° pitch), the pitch is clamped on entry.

#### Visual Information

The raycaster view is pure rendering — no editing. The user can only observe. The status bar shows position coordinates, noclip state, and "RAYCASTER" mode label.

#### Proposed Improvements

1. **Click-to-select in preview:** LMB in raycaster mode casts a DDA ray and selects the hit cell in the inspector. This enables "walk around and inspect" workflows without switching back to 3D.
2. **Editing in preview mode:** The FP_EDITOR_DESIGN doc describes a complete first-person editing system with Minecraft-style controls. Implementing even basic LMB=paint / RMB=pick / MMB=erase would dramatically improve the preview mode's utility.
3. **Minimap overlay:** A small top-down view showing the player's position and facing direction.
4. **Ambient occlusion preview:** *(Advanced)* Approximate AO to show how the zone will look with the game's lighting model.

---

## Part IX — Dialogs, Modals, and Overlays

---

### 33. New Zone Dialog

A centered modal dialog for creating blank zones.

```
┌──────────── New Zone ─────────────┐
│                                   │
│  Create a new blank zone:         │
│  You can name it when you save.   │
│                                   │
│  Width   [  20  ]                 │
│  Height  [  20  ]                 │
│                                   │
│  ┌─────────────┐ ┌─────────────┐  │
│  │   Create    │ │   Cancel    │  │
│  └─────────────┘ └─────────────┘  │
└───────────────────────────────────┘
```

- Width and height are clamped to 5–100.
- Default values: 20×20.
- "Create" creates the zone and loads it (replacing any current zone).
- "Cancel" dismisses the dialog.
- **Proposed:** If the current zone is dirty, show the unsaved changes guard before creating.

---

### 34. Save / Save As Dialogs

**Save (Ctrl+S):** If the zone has a name (not "untitled"), saves immediately. If untitled, opens Save As.

**Save As:**

```
┌────────── Save As ──────────────┐
│                                 │
│  Save zone as:                  │
│                                 │
│  Name   [_______________]       │
│                                 │
│  ⚠ Will overwrite existing zone │  ← Only if name matches existing
│                                 │
│  ┌───────────┐ ┌───────────┐    │
│  │   Save    │ │  Cancel   │    │
│  └───────────┘ └───────────┘    │
└─────────────────────────────────┘
```

- Name is trimmed of whitespace.
- If the name matches an existing zone, a yellow warning appears.
- If the name is blank, the Save button is grayed out.
- On save: writes to `zones/{name}.zone`, updates title bar, clears dirty flag, refreshes zone list.

---

### 35. Unsaved Changes Guard

**This is a critical missing feature in the current version.** Every action that would discard unsaved changes should first show this dialog:

```
┌───────── Save Changes? ──────────┐
│                                  │
│  You have unsaved changes to     │
│  "pawn_shop". What would you     │
│  like to do?                     │
│                                  │
│  ┌────────┐ ┌─────────┐ ┌──────┐│
│  │  Save  │ │ Discard │ │Cancel││
│  └────────┘ └─────────┘ └──────┘│
└──────────────────────────────────┘
```

Triggers:
- **Quit** (Escape from Panel Mode with dirty zone) → Save/Discard/Cancel
- **Load different zone** (click zone in list with dirty zone) → Save/Discard/Cancel
- **New Zone** (click New Zone with dirty zone) → Save/Discard/Cancel

"Save" saves the current zone, then proceeds with the original action.
"Discard" proceeds without saving.
"Cancel" aborts the original action and returns to the editor.

---

### 36. Preset Capture Dialog

*(Implemented — inline HUD naming)*

When the user captures a cell as a preset (RMB with Model tool), the HUD enters naming mode:

```
┌─── HUD ──────────────────────┐
│  Tool: MODEL                 │
│  Model: (current preset)     │
│  Mode: replace  (M)          │
│                              │
│  CAPTURE NAME:               │
│  > my_custom_wall_           │
│                              │
│  Enter=Save  Esc=Cancel      │
└──────────────────────────────┘
```

The name typed becomes the preset's display name and (slugified) its file ID. Empty names cancel. The current apply mode is saved with the captured preset.

---

## Part X — Proposed New Features

---

### 37. Light Level Painting Tool

**Purpose:** Paint per-cell `light_levels` (0.0 to 1.0) for atmospheric control. The raycaster uses light levels to darken/brighten cells.

**Implementation:**
- New tool added to TOOLS tuple: `"light"` (key 8).
- LMB: increase light level by 0.1 (cap at 1.0).
- RMB: decrease light level by 0.1 (floor at 0.0).
- Scroll: adjust brush intensity increment.
- Display option: "Show Lighting" overlays colored cells in the wireframe (yellow = bright, blue = dark).

The zone already has a `light_levels` grid — this tool just provides a way to edit it.

---

### 38. Entity Placement Tool

**Purpose:** Place, move, and configure entities (NPCs, items, doors, containers) in the zone.

**Implementation:**
- New tool: `"entity"` (key 9).
- LMB: place entity at aimed cell.
- RMB: select/inspect entity at aimed cell.
- Entity palette in left panel (lists available entity types from `data/custom_entities.toml`).
- Inspector shows selected entity's properties (type, position, name, dialogue trigger, etc.).
- Drag to move entities.
- Delete removes the selected entity.

This tool would unify entity placement (currently only manageable through external files or the old 2D editor) into the 3D editor.

---

### 39. Portal Editor

**Purpose:** Define portal zones (cells that teleport the player to a different zone) and configure their destinations.

**Implementation:**
- New tool: `"portal"` (key 0).
- LMB: toggle a cell as a portal trigger.
- Inspector shows portal properties: target zone (dropdown), target position (row, col), exit direction.
- Portals are visualized as colored overlays in the 3D view (like selection highlights but in a portal color).
- Display option: "Show Portals" toggle.

---

### 40. Zone Resize & Crop Tool

**Purpose:** Change the dimensions of an existing zone without creating a new one.

**Implementation:**
- Menu: Edit → Resize Zone...
- Dialog with current size, new size (width, height), and an anchor point (where the existing data is placed within the new grid).
- Expansion fills new cells with default values (grass, flat ground, open sky).
- Cropping truncates cells outside the new bounds (with confirmation).
- Entire operation is one undo entry.

---

### 41. Multi-Cell Stamp (Blueprint)

**Purpose:** Capture and apply rectangular regions as multi-cell presets.

**Implementation:**
- With the select tool, create a rectangular selection.
- Press Ctrl+C (or menu Edit → Copy Selection) to capture the entire region as a blueprint.
- Switch to stamp tool — the blueprint is available in the preset palette.
- LMB applies the blueprint with the click position as the top-left corner.
- Blueprints are saved as TOML files with nested cell arrays.

This would enable "rooms" — pre-built rectangular assemblies of cells that can be stamped repeatedly.

---

### 42. Overlay Wall Tool

**Purpose:** Place free-form wall segments that don't align to the grid (fences, diagonal walls, thin partitions).

**Implementation:**
- New tool: `"overlay"` (key combination TBD).
- Click two points to define a wall segment.
- Properties: texture, height_scale, transparency, blocks_movement.
- Data stored in `zone.overlay_walls[]`.
- Visualized as colored lines in 3D wireframe.
- Raycaster renders them as textured vertical strips.

This tool would enable non-grid-aligned architecture — a major upgrade for level design expressiveness.

---

### 43. Autosave & Session Recovery

**Purpose:** Prevent data loss from crashes, accidental quits, or power outages.

**Implementation:**
- Every 2 minutes (configurable), if the zone is dirty, save a copy to `zones/.autosave/{zone_name}.zone`.
- On launch, if an autosave exists for a zone, show: "An autosave was found for '{zone_name}'. Load autosave? [Yes] [No, load saved version]"
- Autosave is deleted when the user manually saves.
- Additionally, the undo stack could be serialized to a temp file for cross-session undo persistence.

---

## Part XI — Keyboard & Mouse Reference

---

### 44. Complete Keyboard Shortcut Table

#### Global (Always Available)

| Key | Action |
|-----|--------|
| `1` | Switch to Sculpt tool |
| `2` | Switch to Paint tool |
| `3` | Switch to Fill tool |
| `4` | Switch to Eraser tool |
| `5` | Switch to Detail (Segment) tool |
| `6` | Switch to Select tool |
| `7` | Switch to Model (Stamp) tool |
| `F2` | Toggle floor grid |
| `F3` | Toggle ceiling grid |
| `F4` | Toggle axes |
| `G` | Cycle snap height forward |
| `V` | Toggle wall visibility |
| `Tab` | Toggle 3D editor / raycaster preview |
| `Ctrl+S` | Save zone |
| `Ctrl+Z` | Undo |
| `Ctrl+Y` or `Ctrl+Shift+Z` | Redo |
| `Escape` | Context-dependent (see §5) |
| `Delete` / `Backspace` | Clear aimed cell (or batch clear selection) |

#### Sculpt Tool Only

| Key | Condition | Action |
|-----|-----------|--------|
| `T` | Aimed at cell | Toggle ceiling on/off |
| `R` | Aimed at floor | Reset floor to 0.0 |
| `R` | Aimed at ceiling | Reset ceiling to default + clear upper wall |
| `U` | Aimed at ceiling | Raise upper wall height by snap |
| `Shift+U` | Aimed at ceiling | Lower upper wall height by snap |
| `Ctrl+U` | Aimed at ceiling | Reset upper wall height to 0.0 |

#### Select Tool Only

| Key | Action |
|-----|--------|
| `X` | Toggle floor/ceiling mode |
| `Escape` | Cancel selection (if active) |

#### Camera (Edit Mode Only)

| Key | Action |
|-----|--------|
| `W/A/S/D` | Fly camera (forward/left/back/right) |
| `Space` | Fly up |
| `C` | Fly down |
| `Q/E` | Keyboard yaw (rotate left/right) |
| `Shift` | Sprint (2.5× speed) |
| `Ctrl` | Slow (0.25× speed) |

#### Raycaster Preview Only

| Key | Action |
|-----|--------|
| `I` | Toggle interior rendering |
| `G` | Toggle noclip |
| `Shift` | Sprint |
| `Ctrl` | Slow walk |

#### Proposed New Shortcuts

| Key | Action |
|-----|--------|
| `Enter` / `F5` | Enter Edit Mode from Panel Mode (instead of mouse click) |
| `Shift+G` | Cycle snap height backward |
| `L` | Toggle light level display |
| `Ctrl+A` | Select all cells |
| `Ctrl+C` | Copy selection |
| `Ctrl+V` | Paste clipboard |
| `Ctrl+Shift+S` | Save As |

---

### 45. Complete Mouse Action Table

#### 3D Editor — Per-Tool

| Tool | LMB | RMB | MMB | Scroll | Shift+Scroll |
|------|-----|-----|-----|--------|-------------|
| Sculpt (floor) | Raise floor | Lower floor | Paint face | Extend floor | Cycle snap |
| Sculpt (ceiling) | Lower ceiling | Raise ceiling | Paint face | Adjust upper wall | Cycle snap |
| Paint | Paint (drag) | Erase texture | Eyedropper | Cycle palette | — |
| Fill | Flood fill | Flood clear | — | Cycle palette | — |
| Eraser | Reset cell | Reset height | — | — | — |
| Eraser (Shift) | Clear textures | — | — | — | — |
| Detail | Split face | Merge segment | Paint segment | Cycle palette | — |
| Select (no sel) | Set corner 1 | — | — | Cycle palette | — |
| Select (1 corner) | Set corner 2 | — | — | Cycle palette | — |
| Select (active) | Fill texture | Clear textures | — | Adjust height | — |
| Model | Apply preset | Capture cell | — | Cycle presets | — |

#### Raycaster Preview

| Button | Action |
|--------|--------|
| Mouse movement | Look (yaw + pitch) |
| LMB | *(Proposed)* Select cell in inspector |
| RMB | *(Proposed)* Eyedropper |

#### Panel Mode

| Button | Action |
|--------|--------|
| LMB on viewport | Enter Edit Mode + perform tool action |
| LMB on panel | Interact with panel widget |
| Scroll on panel | Scroll panel contents |

---

## Part XII — Architecture & Implementation Notes

---

### 46. State Machine Diagram

The complete state machine for the zone editor application:

```
                                ┌─────────────────┐
                ┌───────────────│  APPLICATION    │──────────────┐
                │               │  STARTUP        │              │
                │               └────────┬────────┘              │
                │                        │                       │
                │               Create default zone              │
                │               └→ Load CLI zone if given        │
                │                        │                       │
                │                        ▼                       │
                │               ┌─────────────────┐              │
           ┌────┴───────────────│   PANEL MODE    │──────┐       │
           │                    │   (mouse free)   │      │       │
           │                    └────────┬────────┘      │       │
           │                             │               │       │
           │    Click viewport           │  Escape       │       │
           │    / Enter / F5             │  (dirty)      │       │
           │         │                   │               │       │
           │         ▼                   ▼               │       │
           │    ┌────────────┐    ┌────────────┐        │       │
           │    │  EDIT MODE │    │ SAVE       │        │       │
           │    │  (captured)│    │ DIALOG     │        │       │
           │    └─────┬──────┘    └────────────┘        │       │
           │          │                                  │       │
           │    Escape│    Tab                           │       │
           │    (no   │    │                             │       │
           │    sel)  │    ▼                             │       │
           │          │  ┌────────────┐                  │       │
           │          │  │ EDIT MODE  │                  │       │
           │          │  │ (other     │                  │       │
           │          │  │  view)     │                  │       │
           │          │  └────────────┘                  │       │
           │          │                                  │       │
           │          ▼                                  │       │
           └──────────┘                                  │       │
                                                         │       │
                                          Escape (clean) │       │
                                          or Discard     │       │
                                                ▼        │       │
                                         ┌───────────┐   │       │
                                         │  QUIT     │───┘       │
                                         │  CONFIRM  │           │
                                         └───────────┘           │
                                                                 │
                                         ┌───────────┐           │
                                         │  EXIT     │◄──────────┘
                                         └───────────┘
```

---

### 47. Event Routing Priority

When a pygame event is received, it is processed through this priority chain:

#### Panel Mode (mouse not captured):

```
1. QUIT event           → exit application
2. VIDEORESIZE          → rescale panels, invalidate viewport surface
3. Key: Escape          → quit (with unsaved guard)
4. Key: Tab             → toggle view mode
5. Key: Ctrl+S          → save
6. Mouse click on       → if not io.want_capture_mouse: enter Edit Mode
   viewport                + perform tool action
7. Everything else      → imgui_impl.process_event(event)
```

#### Edit Mode (mouse captured):

```
1. Key: Escape          → if tool has cancelable state: cancel it
                           else: exit to Panel Mode
2. Key: Tab             → toggle view mode (stay captured)
3. Key: Ctrl+S          → save (stay captured)
4. Key: 1-7             → switch tool
5. Key: other           → forward to editor_3d.handle_event()
                           or raycaster_key()
6. Mouse button down    → forward to editor_3d.handle_event()
7. Mouse button up      → forward to editor_3d.handle_event()
8. Mouse wheel          → forward to editor_3d.handle_event()
9. Mouse motion         → consumed by update() for camera look
```

---

### 48. Undo/Redo Architecture

#### Current Implementation

Full-zone snapshots. Before each mutation, the entire mutable state of the zone is deep-copied:

```python
snapshot = {
    "tiles": deep_copy(zone.tiles),
    "floor_heights": deep_copy(zone.floor_heights),
    "ceil_heights": deep_copy(zone.ceil_heights),
    "floor_textures": deep_copy(zone.floor_textures),
    "ceil_textures": deep_copy(zone.ceil_textures),
    "wall_textures": deep_copy(zone.wall_textures),
    "face_textures": deep_copy(zone.face_textures),
    "wall_segments": deep_copy(zone.wall_segments),
    "floor_step_textures": deep_copy(zone.floor_step_textures),
    "ceil_step_textures": deep_copy(zone.ceil_step_textures),
    "floor_step_segments": deep_copy(zone.floor_step_segments),
    "ceil_step_segments": deep_copy(zone.ceil_step_segments),
    "upper_wall_height": deep_copy(zone.upper_wall_height),
    "light_levels": deep_copy(zone.light_levels),
    "rotations": deep_copy(zone.rotations),
}
```

- Stack depth: max 50 entries.
- Redo stack is cleared on new mutation.
- Continuous paint (LMB drag) pushes one snapshot for the entire stroke.

#### Memory Cost

For a 20×20 zone, each snapshot copies ~20×20 = 400 cells across ~15 arrays, each containing various nested lists. Rough estimate: ~200KB per snapshot × 50 max = ~10MB maximum undo memory. Acceptable for small zones, but a 100×100 zone would be ~250MB for the undo stack alone.

#### Proposed Improvements

1. **Delta-based undo:** Instead of full snapshots, record only the cells that changed. Each undo entry stores `[(r, c, field, old_value, new_value), ...]`. This reduces memory by 95%+ for single-cell edits.

2. **Undo entry descriptions:** Each stack entry should have a human-readable label: "Raise floor (3,7) → 0.50", "Fill 15 cells with brick_dark", "Delete 6 cells". This enables an undo history panel.

3. **Undo grouping:** Multiple rapid edits of the same type (e.g., scroll-extending a floor) should be grouped into one undo entry with a timeout (e.g., group if less than 500ms apart).

4. **Persistent undo:** Serialize the undo stack to a temp file so undo history survives editor restarts.

---

### 49. Performance Budget

#### Target Frame Time

| Component | Budget | Notes |
|-----------|--------|-------|
| Event processing | < 0.5ms | Pure Python, fast |
| Camera update | < 0.2ms | Math-only |
| 3D wireframe rendering | < 8ms | Software renderer bottleneck |
| Raycaster rendering | < 5ms | C extension, fast |
| GL texture upload | < 2ms | `glTexImage2D` full-window |
| ImGui rendering | < 1ms | Already fast |
| **Total** | **< 16.6ms** | **60 FPS target** |

#### Current Bottlenecks

1. **3D wireframe rendering (Python):** The filled-box rendering with per-face coloring, depth sorting, and polygon projection is entirely software-rendered in Python. For a 20×20 zone with height variations, this can easily exceed 10ms. **Proposed fix:** Frustum culling (only render cells within the camera's view frustum) and LOD (distant cells rendered as simpler shapes or skipped).

2. **Full GL texture upload every frame:** Even when nothing has changed, the viewport surface is re-uploaded to the GPU every frame. **Proposed fix:** Dirty flag on the viewport — only upload when the zone, camera, or display state has changed. Use `glTexSubImage2D` for partial updates.

3. **Python deep copy for undo:** Each `_push_undo()` does a nested deep copy of all zone arrays. For large zones, this can spike the frame time. **Proposed fix:** Delta-based undo (only copy changed cells).

4. **No frustum culling:** Every cell in the zone is projected and tested for rendering, even cells behind the camera. **Proposed fix:** Cull cells outside a ±90° horizontal and ±70° vertical frustum cone from the camera.

---

## Final Notes

This manual describes an **idealistic** next version. Not every feature needs to ship simultaneously. The recommended implementation priority is:

### Priority 1 — Control Flow Fixes (Immediate)
- [ ] Unsaved changes guard
- [ ] First-click performs tool action (not wasted)
- [ ] Panels update during Edit Mode
- [ ] Transient indicators near crosshair on scroll
- [ ] Escape priority chain (cancel selection → release mouse → quit guard)

### Priority 2 — Visibility Improvements (Short-term)
- [ ] Always-visible Brush Bar
- [ ] Display toggles as inline checkboxes (not collapsed)
- [ ] Zone Settings and Camera default-open
- [ ] Status bar with flexible spacing and full context
- [ ] Action context labels near crosshair

### Priority 3 — Quality-of-Life (Medium-term)
- [x] Preset capture dialog with naming (inline HUD naming)
- [x] Apply modes for stamp tool (replace, stack_floor, stack_ceil, merge)
- [ ] Preset delete from editor
- [ ] Autosave
- [ ] Undo grouping for rapid scrolls
- [ ] Keyboard shortcut to enter Edit Mode (Enter / F5)

### Priority 4 — New Tools (Long-term)
- [ ] Light level painting
- [ ] Entity placement
- [ ] Portal editor
- [ ] Zone resize
- [ ] Multi-cell stamp (blueprints)
- [ ] Overlay wall tool

### Priority 5 — Performance (Ongoing)
- [ ] Frustum culling
- [ ] Dirty-flag texture upload
- [ ] Delta-based undo
- [ ] Python → C migration for rendering hot paths

---

*This document was written as a design target for the zone editor's evolution. It reflects the current codebase's strengths (solid tool system, clean mixin architecture, comprehensive zone data model) while addressing its weaknesses (hidden state, collapsed panels, wasted clicks, no save guards, poor scroll feedback). Every proposed change is grounded in real user friction observed during editing sessions.*
