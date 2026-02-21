# First-Person Editor — Design Document

## Philosophy

The FP editor is a **Minecraft-Creative-mode-like** experience inside the
map editor. The user walks around inside the world they're building and
places / removes / edits tiles by pointing and clicking. It must feel
immediate and spatial — no menu-hunting, no modal interruptions, no
cognitive overhead about "modes" or "placement targets."

**Core principle:** The crosshair points at a thing. Left-click changes
that thing. That's it.

---

## Modes of Operation

### 1. PIP Preview (read-only)

| Aspect       | Value                                          |
|--------------|------------------------------------------------|
| Enter        | Press **P** from the 2D editor                |
| Display      | Small overlay in the top-right corner of canvas |
| Interaction  | WASD + arrow keys for movement/look            |
| Editing      | None — view only                               |
| Exit         | **Esc** → close PIP, **F** → enter fullscreen  |

Purpose: Quick sanity check — "does this room look right from inside?"

### 2. Fullscreen Edit Mode

| Aspect       | Value                                                  |
|--------------|--------------------------------------------------------|
| Enter        | Press **F** from 2D editor (auto-opens PIP + fullscreen) or **Tab** from PIP |
| Display      | Raycaster fills the entire canvas area                 |
| Interaction  | Mouse-look (grabbed), WASD movement, full editing      |
| Exit         | **Esc** → back to PIP, **Esc** again (or P) → close   |

This is where all editing happens. The mouse cursor is hidden and
grabbed. The player looks around with the mouse and moves with WASD.

---

## Crosshair & Target System

The crosshair is always at screen center. A single DDA ray determines
what the user is pointing at. There are exactly **two target states**:

### A. Aiming at a Wall / Solid

The ray hit a wall cell. The crosshair reports:

- **Target cell** `(r, c)` — the wall tile that was hit.
- **Ghost cell** `(r, c)` — the empty cell just *before* the wall
  (the last non-solid cell the ray passed through).

### B. Aiming at Open Space (floor/ceiling)

The ray didn't hit a wall within MAX_DEPTH. The crosshair reports:

- **Target cell** — the floor cell 2 tiles ahead in the look direction.
- **Ghost cell** — same as target cell (they're the same when looking at floor).

In both cases the ghost cell is always the **cell that would receive a
new block placement**.

---

## Click Actions

There are exactly **three** mouse buttons. Each does one thing.
No modes, no Q/E toggles. The action depends only on what you're
aiming at.

### Left Click — PLACE / PAINT

| Aiming At    | Action                                                |
|--------------|-------------------------------------------------------|
| Wall / solid | Paint the selected tile onto the **ghost cell** (the empty cell in front of the wall). This builds a new block. |
| Open floor   | Paint the selected tile onto the **target floor cell**. This replaces the floor texture. |

> **Why always the ghost cell for walls?** Because when building, you
> want to *extend* walls, not repaint existing ones. If you aim at a
> brick wall, you want to place the next brick *in front of it*, not
> change that brick. Repainting existing walls is what the eyedropper +
> second click is for.

### Right Click — EYEDROPPER (Pick)

Always picks the *aimed-at tile* (the actual wall or floor under the
crosshair). Sets `selected_tile` to its ID.

This combines naturally with left-click: right-click a wall to grab
its type, then left-click elsewhere to paint it.

### Middle Click — ERASE

| Aiming At    | Action                                                |
|--------------|-------------------------------------------------------|
| Wall / solid | Replace the **aimed wall cell** with `erase_tile` (default: grass). This removes the block. |
| Open floor   | Replace the **target floor cell** with `erase_tile`. |

> Erasing always targets the thing you're looking at, not the ghost.
> When you want to delete a wall, you click *on* the wall.

---

## Tile Selection — The Hotbar

Scroll-cycling through 34 tiles is terrible UX. Instead, the FP editor
uses a **hotbar** — a row of 10 tile slots rendered at the bottom center
of the screen, like Minecraft's hotbar.

### Hotbar Behavior

| Control      | Action                                           |
|--------------|--------------------------------------------------|
| **1–9, 0**   | Select hotbar slot 1–10 directly                 |
| **Scroll ↑/↓** | Move to next/previous hotbar slot              |
| **Right-click** | Eyedropper — picks tile AND places it into the current hotbar slot |
| **T**        | Open tile picker overlay                         |

The hotbar is persistent state — it survives between FP sessions. It
starts pre-loaded with the most commonly needed tiles:

```
Slot 1: wall        Slot 6: door
Slot 2: brick_wall  Slot 7: wood_floor
Slot 3: stone       Slot 8: carpet
Slot 4: grass       Slot 9: sand
Slot 5: concrete    Slot 0: void
```

### Tile Picker Overlay (T key)

When the user presses **T**, a translucent overlay appears showing
**all tiles grouped by category** in a grid. The user clicks a tile
to assign it to the current hotbar slot, then the overlay closes.
Mouse-look is paused while the picker is open. **Esc** closes without
selecting.

This is NOT a modal dialog — it's a lightweight in-viewport overlay
that doesn't break the FP immersion.

---

## Ghost Preview

The ghost block preview shows **exactly what will happen** when the user
left-clicks.

### When Aiming at a Wall

A translucent column appears in the **ghost cell** (the empty cell in
front of the wall). It uses the actual tile texture from the atlas,
scaled to the correct projected size, with a pulsing outline.

### When Aiming at Floor

A translucent square appears on the **floor** of the target cell.
It uses the tile's floor texture, projected onto the ground plane
at the correct perspective, with a pulsing outline.

### Ghost Always Matches Click Target

The ghost never lies. If the ghost shows a block appearing at cell
`[5,3]`, then left-clicking paints to `[5,3]`. No exceptions.

---

## Movement & Physics

| Control          | Action                                  |
|------------------|-----------------------------------------|
| **W / S**        | Move forward / backward                 |
| **A / D**        | Strafe left / right                     |
| **Mouse X**      | Turn left / right (mouse-look)          |
| **C**            | Toggle noclip (pass through walls)      |
| **Shift**        | Sprint (2× move speed)                  |

Collision is on by default with a margin of 0.2 tiles from walls.
Noclip lets you fly through walls for quick repositioning.

---

## HUD Layout

```
┌───────────────────────────────────────────────────────────────────┐
│  (12.3, 7.8)                                                      │
│  Looking at: Brick Wall [5,3]                                     │
│  Ghost: [4,3]                                           NOCLIP    │
│                                                                   │
│                                                                   │
│                                                                   │
│                           +                                       │
│                                                                   │
│                                                                   │
│                                                                   │
│                                                                   │
│                                                                   │
│  ┌───┬───┬───┬───┬───┬───┬───┬───┬───┬───┐                       │
│  │ 1 │ 2 │ 3 │ 4 │ 5 │ 6 │ 7 │ 8 │ 9 │ 0 │                     │
│  │ ## │ ## │ ## │ ## │ ## │ ## │ ## │ ## │ ## │ ## │               │
│  └───┴───┴───┴───┴───┴───┴───┴───┴───┴───┘                       │
│              WASD=Move  C=Noclip  T=Tiles  Esc=Exit               │
└───────────────────────────────────────────────────────────────────┘
```

- **Top-left**: Coordinates, target info, ghost cell. Minimal font.
- **Top-right**: NOCLIP indicator (when active), red/bold.
- **Center**: Crosshair.
- **Bottom-center**: Hotbar with 10 texture swatches. Active slot has
  an accent border. Slot numbers shown above each swatch.
- **Bottom**: Controls hint in dim text.

The hotbar swatches render the tile's actual texture (from the atlas)
at a small thumbnail size (e.g. 32×32, scaled to DPI). The selected
slot has a bright accent border; others have a dim border.

---

## Undo / Redo

| Control       | Action |
|---------------|--------|
| **Ctrl+Z**    | Undo   |
| **Ctrl+Y**    | Redo   |

Each left-click or middle-click pushes one undo snapshot. Holding
the button and dragging does NOT create new snapshots — only the
initial click does. This matches the 2D editor behaviour.

---

## Complete Keybind Reference

| Key         | Context      | Action                              |
|-------------|--------------|-------------------------------------|
| **P**       | 2D Editor    | Toggle PIP preview                  |
| **F**       | 2D Editor    | Enter fullscreen FP edit mode       |
| **Esc**     | Fullscreen   | Exit to PIP                         |
| **Esc**     | PIP          | Close FP preview                    |
| **Tab**     | PIP          | Enter fullscreen                    |
| **W/A/S/D** | FP active    | Move                                |
| **Shift**   | FP active    | Sprint                              |
| **Mouse X** | Fullscreen   | Look                                |
| **LClick**  | Fullscreen   | Place / paint tile                  |
| **RClick**  | Fullscreen   | Eyedropper (pick tile → hotbar)     |
| **MClick**  | Fullscreen   | Erase tile                          |
| **1–9, 0**  | Fullscreen   | Select hotbar slot                  |
| **Scroll**  | Fullscreen   | Cycle hotbar slot                   |
| **T**       | Fullscreen   | Open tile picker overlay            |
| **C**       | Fullscreen   | Toggle noclip                       |
| **Ctrl+Z**  | Fullscreen   | Undo                                |
| **Ctrl+Y**  | Fullscreen   | Redo                                |

### Removed Controls

| Old Control    | Reason                                           |
|----------------|--------------------------------------------------|
| **Q/E modes**  | Eliminated — placement is always contextual now  |
| **Scroll=Cycle all tiles** | Replaced by hotbar (10 slots)          |
| **Arrow keys** | Removed from FP — only WASD. Arrow keys conflict with 2D editor |

---

## State to Add

```python
# On FPPreview:
self.hotbar: list[str]          # 10 tile IDs
self.hotbar_slot: int           # 0–9, active slot
self.tile_picker_open: bool     # T-key overlay state
self.sprint: bool               # Shift held
```

The hotbar replaces `state.selected_tile` as the source of truth for
what to paint in FP mode. When the user right-clicks (eyedropper), the
picked tile goes into the *current hotbar slot*, and `state.selected_tile`
is also synced so the 2D editor stays in sync.

When entering FP mode, `hotbar[hotbar_slot]` is synced to
`state.selected_tile`. When exiting, `state.selected_tile` is synced
back from the hotbar.

---

## Implementation Plan

1. **Add hotbar state** to `FPPreview.__init__` — list of 10 tile IDs +
   active slot index.
2. **Rewrite scroll handler** — scroll cycles `hotbar_slot` (0–9), not
   through all tiles.
3. **Add number key handling** — 1–9, 0 directly select hotbar slots.
4. **Remove Q/E placement modes** — left-click always paints ghost cell
   for walls, target cell for floors. Middle-click always erases the
   aimed cell. No mode toggle needed.
5. **Update right-click** — eyedropper sets the picked tile into the
   current hotbar slot AND syncs `state.selected_tile`.
6. **Draw hotbar** — 10 textured swatches at bottom-center of screen.
7. **Add tile picker overlay** — T key opens a category-grouped grid.
   Click to assign tile to current slot. Esc to close.
8. **Add sprint** — Shift key doubles MOVE_SPEED while held.
9. **Simplify crosshair targeting** — remove all "place_mode" logic.
   Left-click always writes to ghost_rc (builds) when aiming at walls,
   or target_rc (paints floor) when aiming at open space.
10. **Update HUD** — draw hotbar, remove mode indicators, clean up hints.
