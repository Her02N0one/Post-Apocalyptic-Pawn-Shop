# Zone Editor — Control Flow & Architecture

## Overview

`zone_editor.py` is a standalone application (~1020 lines) that wraps two existing subsystems:

1. **Zone3DEditor** (`editor/view_3d/editor.py`, ~1960 lines) — a software-rendered 3D wireframe editor that draws to a `pygame.Surface`. It has its own camera, tool system, picking, undo/redo, and HUD drawn directly onto the surface.

2. **RayRenderer** (`systems/ray_renderer.py` + C extension) — a 2.5D raycaster that renders a first-person preview to a `pygame.Surface`.

The zone editor composites one of these onto a fullscreen OpenGL quad, then overlays ImGui panels on top. Input routing switches between two states: **captured** (viewport owns all input) and **released** (ImGui owns all input).

---

## Architectural Layers

```
┌──────────────────────────────────────────────────────────┐
│ zone_editor.py   ZoneEditorApp                           │
│   ┌──────────┐  ┌──────────────────────────────────────┐ │
│   │ ImGui UI │  │ Fullscreen GL Quad (viewport)        │ │
│   │ (panels) │  │   ┌──────────┐  ┌─────────────────┐ │ │
│   │          │  │   │Zone3DEdit│  │ RayRenderer     │ │ │
│   │          │  │   │  or      │  │ (Tab toggle)    │ │ │
│   │          │  │   └──────────┘  └─────────────────┘ │ │
│   └──────────┘  └──────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────┘
```

### What Each Layer Owns

| Layer | Owns | Does NOT own |
|-------|------|-------------|
| **ZoneEditorApp** | Window, GL context, ImGui lifecycle, input routing, mouse capture/release, mode toggle, zone load/save/create, raycaster camera state | 3D wireframe rendering, 3D tool logic, picking, undo internals |
| **Zone3DEditor** | 3D camera (pos/yaw/pitch), tool system, aimed cell, WASD+mouse movement (`update()`), event dispatch (`handle_event()`), wireframe drawing (`draw()`), undo/redo stack, HUD/help overlays, zone mutations | Window, input capture, GL, ImGui, raycaster |
| **RayRenderer** | Raycasting, floor/wall/ceiling rendering, collision checks | Camera state (passed in each frame), input |

---

## Input State Machine

There are exactly **two states**:

```
                  LMB click (not over ImGui panel)
   ┌──────────┐ ──────────────────────────────────→ ┌──────────────┐
   │ RELEASED │                                      │  CAPTURED    │
   │          │ ←────────────────────────────────── │              │
   └──────────┘         Escape key                   └──────────────┘
```

### RELEASED State (`mouse_captured = False`)

- **Cursor**: visible, not grabbed
- **All pygame events** → `imgui_impl.process_event(event)`
- **WASD / mouse movement**: ignored (camera frozen)
- **LMB click on viewport area** (where `io.want_capture_mouse` is False): transitions to CAPTURED
- **Escape**: quits the application
- **Tab / Ctrl+S**: still work as global shortcuts (after being fed to ImGui)
- **ImGui panels**: fully interactive (buttons, checkboxes, zone list clicks, dialogs)
- **Viewport**: shows a "Click viewport to edit | Esc = quit" hint overlay

### CAPTURED State (`mouse_captured = True`)

- **Cursor**: hidden, grabbed (`set_grab(True)`)
- **No events** go to `imgui_impl.process_event()` — ImGui is deaf
- **Escape**: transitions to RELEASED (does NOT quit)
- **Tab**: toggles between 3D editor and raycaster (stays captured)
- **Ctrl+S**: saves (stays captured)
- **All KEYDOWN events** → forwarded to `editor_3d.handle_event()` or `_raycaster_key()`
- **All MOUSEBUTTONDOWN events** → forwarded to `editor_3d.handle_event()`
  - LMB (button 1) = tool primary action
  - RMB (button 3) = tool secondary action
  - MMB (button 2) = paint
- **All MOUSEWHEEL events** → forwarded to `editor_3d.handle_event()`
- **WASD / mouse delta / Space / C** → consumed by `editor_3d.update(dt, True)` (3D mode) or `_update_raycaster(dt)` (raycaster mode)
- **ImGui panels**: still rendered visually but inert (cannot receive clicks or keys)

---

## Main Loop (per frame)

```python
while running:
    dt = clock.tick(60) / 1000.0          # 1. Tick

    running = _process_events()            # 2. Events — routes to ImGui OR viewport

    if mouse_captured:                     # 3. Update
        if view_mode == "3d":
            editor_3d.update(dt, True)     #    camera movement + aim raycast
        elif view_mode == "2d":
            _update_raycaster(dt)          #    WASD walk + mouse look
    # else: no update, camera frozen

    _render_frame()                        # 4. Render
    #   a) Zone3DEditor.draw() or RayRenderer.render()
    #      → pygame.Surface (full window size)
    #   b) Upload surface → GL texture
    #   c) Draw fullscreen GL quad
    #   d) ImGui: new_frame → build_ui → render → draw

    pygame.display.flip()                  # 5. Swap
```

---

## Render Pipeline

```
Zone3DEditor.draw(surface)         ← Software-rendered wireframe
        │  OR
RayRenderer.render(px,py,angle,h)  ← C raycaster → small surface → scale
        │
        ▼
pygame.Surface (win_w × win_h)
        │
        ▼  pygame.image.tostring("RGBA", flipped=False)
        │
        ▼  glTexImage2D (upload to GL texture)
        │
        ▼  _draw_fullscreen_quad() — maps UV correctly:
        │    v=0 (pygame row 0 = top) → GL top (+1)
        │    v=1 (pygame last row = bottom) → GL bottom (-1)
        │
        ▼  ImGui overlay panels drawn on top (semi-transparent bg)
        │
        ▼  pygame.display.flip() → GL buffer swap
```

### UV Mapping Detail

`pygame.image.tostring(surface, "RGBA", False)` encodes row 0 first. OpenGL texture coordinate v=0 maps to the first row of data. The GL quad maps:

| Texcoord | Screen position | Pygame row |
|----------|----------------|------------|
| (0, 0) | top-left (+1 Y) | row 0 (top) |
| (0, 1) | bottom-left (-1 Y) | last row (bottom) |
| (1, 0) | top-right (+1 Y) | row 0 (top) |
| (1, 1) | bottom-right (-1 Y) | last row (bottom) |

This means pygame's top→bottom maps to GL's top→bottom, the image is right-side-up.

---

## Tool System (Zone3DEditor side)

Five tools selected by keys 1–5:

| Tool | LMB (btn 1) | RMB (btn 3) | MMB (btn 2) | Scroll | T key | R key |
|------|-----------|-----------|-----------|--------|-------|-------|
| **Wall** | Place wall | Remove wall | Paint | Cycle texture | — | — |
| **Floor** | Raise floor | Lower floor | Paint | Cycle snap-Y | Toggle floor | Reset floor |
| **Ceiling** | Lower ceiling | Raise ceiling | Paint | Cycle snap-Y | Toggle ceiling | Reset ceiling |
| **Paint** | Paint face | Paint face | Paint face | Cycle texture | — | — |
| **Segment** | Split segment | Merge segment | Paint segment | Cycle texture | — | — |

Other keys in 3D mode: G (cycle snap), V (toggle wall visibility), F1-F4 (display toggles), H (HUD), U (upper wall height), Ctrl+Z/Y (undo/redo).

---

## View Mode Toggle (Tab)

Camera position is transferred when switching:

```
3D → Raycaster:
    px = editor_3d.cam_x
    py = editor_3d.cam_z          (3D Z → raycaster Y)
    angle = yaw + π/2             (coordinate system offset)
    cam_h = floor_height + 0.5

Raycaster → 3D:
    cam_x = px
    cam_y = cam_h                 (preserve eye height)
    cam_z = py                    (raycaster Y → 3D Z)
    yaw = angle - π/2
    pitch = 0
```

On switch to raycaster: `renderer.update_zone()` is called to sync any geometry edits. On switch to 3D: no update needed (editor reads zone data directly).

---

## ImGui Panel Layout

```
┌─ Menu Bar ───────────────────────────────────── FPS ──┐
│                                                       │
├── Tools ──┤                          ├── Properties ──┤
│ [1] WALL  │                          │ Cell (r, c)   │
│ [2] FLOOR │                          │ Tile: name    │
│ [3] CEIL  │    3D VIEWPORT           │ Heights:      │
│ [4] PAINT │    (fullscreen GL quad   │   Floor: ...  │
│ [5] SEG   │     behind all panels)   │   Ceil: ...   │
│           │                          │ Textures: ... │
│ Snap: ... │                          │ Segments: ... │
│ Tab: mode │                          │ Aimed: ...    │
│ Display   │                          │               │
├── Zones ──┤                          │               │
│ + New Zone│                          │               │
│ showcase  │                          │               │
│ tutorial  │                          │               │
├───────────┴──────────────────────────┴───────────────┤
│ Status: zone* | 20x20 | 3D EDITOR | EDITING | WALL  │
└──────────────────────────────────────────────────────┘
```

Panel positions are absolute, not dockable. Left panels split 55%/45% of available height.

---

## Known Weaknesses & Missing Features

### Control Flow Issues

1. **Panel clicks steal first capture click** — When clicking on the viewport while released, the click transitions to CAPTURED but never reaches `editor_3d.handle_event()`. The first click is "wasted" just to enter capture mode. The user must then click again to perform a tool action.

2. **Dirty flag only set from 3D editor** — `self.dirty` is set when `editor_3d.dirty` is True, but if the user modifies zone properties through hypothetical future ImGui property editors, the dirty flag won't be set.

3. **No unsaved-changes prompt on quit** — Escape from RELEASED state immediately quits. No confirmation dialog if `self.dirty` is True.

4. **No unsaved-changes prompt on zone switch** — Clicking a different zone in the Zones panel loads it immediately, discarding edits.

5. **Zone list not refreshed after external changes** — `self.all_zones` is populated at init and when creating zones. If the user adds zone JSON files externally, they won't appear until restart.

6. **Ctrl+S handled in both the editor AND zone_editor** — `editor_3d._on_keydown` also handles Ctrl+S (calls `_save()` internally). Since zone_editor intercepts Ctrl+S before forwarding to the editor, the editor's internal save handler never fires. This works but is fragile — if the interception order changes, double-saves could occur.

### Editing Gaps

7. **No direct property editing in panels** — The Properties panel is read-only. Heights, textures, and tile types can only be changed with the 3D tool-and-crosshair system. Adding ImGui sliders/inputs for floor height, ceiling height, and texture selection would be much faster for precise edits.

8. **No multi-cell selection** — Every tool operates on one cell at a time. No rectangle fill, no flood fill, no "paint bucket."

9. **No texture preview** — The current texture name is shown in the status bar / HUD but there's no visual preview of what it looks like.

10. **No tile type indicator in 3D** — Walls are visually distinct in 3D (tall boxes), but there's no way to see tile names/IDs without aiming at each cell one by one.

11. **Raycaster mode is view-only** — You can look around but can't edit anything. No way to click-to-select a cell from the FP view.

12. **No zone resize** — Can create new zones with specified dimensions, but can't resize an existing zone.

13. **No delete zone** — Can create but not delete zones from within the editor.

### UI/UX Issues

14. **Panel widths are fixed** — LEFT_PANEL_W=220, RIGHT_PANEL_W=250 hardcoded. No resizing or collapsing panels to see more of the viewport on smaller screens.

15. **No keyboard shortcut to capture** — Must use mouse click. There's no "press Enter to start editing" or similar.

16. **Status bar overflows on narrow windows** — `same_line()` positions are hardcoded. On a window narrower than ~600px, items overlap.

17. **No indication of current texture** — The panels show what texture the _aimed cell_ has, but not what texture is _selected_ for painting (the palette index). The user has to scroll to find it in the 3D HUD.

18. **Capture hint overlaps content** — The "Click viewport to edit" hint is centered in the viewport but doesn't check if it overlaps meaningful content.

### Rendering Issues

19. **Full-window surface allocation every frame** — `_get_vp_surface()` creates a full-resolution surface. This is wasteful for the 3D wireframe editor which doesn't need alpha/transparency. Consider using `convert()` or reusing the surface more efficiently.

20. **No dirty-rect optimization** — The entire surface is re-rendered every frame even if nothing changed (no camera movement, no edits). The 3D editor's Python software renderer is the bottleneck.

21. **Zone3DEditor's built-in HUD is disabled but still compiled** — We set `show_hud=False` at load but the draw method still checks the flag. Minor, but the editor renders its own crosshair/tool hints onto the surface regardless, creating visual overlap with ImGui panels (the crosshair is always centered in the viewport, while the ImGui panels sit on the sides).

22. **glTexImage2D every frame** — Even when the viewport content hasn't changed, we re-upload the full texture. `glTexSubImage2D` with a dirty flag would be cheaper.

### Data/Persistence

23. **JSON save format** — zone_editor uses `editor_3d._save()` which writes JSON. This is the correct format but the path is determined by `editor_3d` internally (uses `_core_paths.ZONES_DIR`). If the editor's path logic changes, saves could silently go to the wrong place.

24. **No autosave** — One accidental Escape-from-release = immediate quit, all edits lost.

25. **Undo stack is per-session only** — No persistent undo across loads or across editor restarts.

---

## Data Flow Summary

```
Zone JSON on disk
    │
    ▼  load_zone(name) → Zone object (in-memory)
    │
    ├──→ Zone3DEditor(zone) reads zone.tiles, zone.floor_heights, etc.
    │        mutates zone properties directly on tool actions
    │        _push_undo() snapshots before each mutation
    │
    ├──→ RayRenderer(zone, atlas) reads zone data for rendering
    │        .update_zone() called on Tab switch to sync
    │
    └──→ ImGui panels read zone properties for display (read-only)

    User presses Ctrl+S → editor_3d._save() → writes zone JSON
```

All three consumers share the same `Zone` object. Mutations by Zone3DEditor are immediately visible to the RayRenderer (after `update_zone()`) and to ImGui panels (next frame).

---

## File Inventory

| File | Lines | Role |
|------|-------|------|
| `zone_editor.py` | ~1020 | This application: ImGui, GL, input routing, raycaster camera |
| `editor/view_3d/editor.py` | ~1960 | Zone3DEditor: 3D camera, tools, wireframe rendering |
| `editor/view_3d/math3d.py` | ~200 | Projection matrices, 3D→2D, line clipping |
| `editor/view_3d/picking.py` | ~120 | AABB ray intersection, CellHit dataclass |
| `editor/fly_camera.py` | ~100 | WASD+mouse movement helpers |
| `systems/ray_renderer.py` | ~300 | Python wrapper around C raycaster |
| `systems/_ray_render.c` | ~2000 | C raycaster extension |
| `core/zones.py` | ~200 | Zone dataclass, load/save, list_zones() |
