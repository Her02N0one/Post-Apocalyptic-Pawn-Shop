"""editor2/hud.py — Viewport HUD overlay builder.

Builds a list of ``(text, (r, g, b))`` lines for the viewport's
on-screen overlay.  Keeps rendering logic out of the main window.

Usage::

    from editor2.hud import build_hud_lines
    lines = build_hud_lines(editor_state, hit)
    viewport.hud_lines = lines
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from editor2.tools.sculpt import SculptTool
    from editor2.tools.entity import EntityTool
    from editor2.tools.light import LightTool
    from editor2.selection import SelectionState
    from core.zones import Zone

# ── HUD colour constants ─────────────────────────────────────────
HUD_TITLE = (255, 200, 80)
HUD_VALUE = (120, 220, 255)
HUD_TEXT  = (220, 220, 200)
HUD_CAMERA = (255, 120, 80)


def build_hud_lines(
    *,
    active_tool_name: str,
    camera_captured: bool,
    sculpt_tool: SculptTool,
    entity_tool: EntityTool,
    light_tool: LightTool,
    selection: SelectionState,
    zone: Zone,
    snap_labels: list[str],
    entity_snap_labels: list[str],
    paint_texture: str,
    hit,
) -> list[tuple[str, tuple[int, int, int]]]:
    """Build the HUD lines for the viewport overlay.

    Returns a list of ``(text, (r, g, b))`` tuples.
    """
    lines: list[tuple[str, tuple[int, int, int]]] = []

    # Tool line
    tool_name = active_tool_name.replace("_", " ").title()
    lines.append((f"Tool: {tool_name}", HUD_TITLE))

    # Camera mode indicator
    if camera_captured:
        lines.append(("Camera Active (Esc to exit)", HUD_CAMERA))

    # Snap (sculpt only)
    if active_tool_name == "sculpt":
        snap_label = snap_labels[sculpt_tool.snap_idx]
        lines.append((f"Snap: {snap_label}", HUD_VALUE))

    # Current texture (paint only)
    if active_tool_name == "paint":
        tex = paint_texture or '—'
        lines.append((f"Texture: {tex}", HUD_VALUE))

    # Entity type (entity tool only)
    if active_tool_name == "entity":
        etype = entity_tool.current_type or '—'
        lines.append((f"Entity: {etype}", HUD_VALUE))
        snap_lbl = entity_snap_labels[entity_tool.snap_idx]
        lines.append((f"Snap: {snap_lbl}", HUD_VALUE))
        if entity_tool.selected_uid is not None:
            lines.append((f"Selected UID: {entity_tool.selected_uid}",
                          HUD_VALUE))

    # Light step (light tool only)
    if active_tool_name == "light":
        lines.append((f"Light step: {light_tool.step}", HUD_VALUE))

    # Selection count
    if selection.has_cells():
        n = len(selection.cells)
        mode = "Ceil" if selection.ceiling_mode else "Floor"
        lines.append((f"Selection: {n} cells ({mode})", HUD_VALUE))

    # Cell info
    if hit is not None:
        r, c = hit.row, hit.col
        fh = zone.floor_heights[r][c] if zone.floor_heights else 0.0
        ch = zone.ceil_heights[r][c] if zone.ceil_heights else 10.0
        ll = zone.light_levels[r][c] if zone.light_levels else 1.0
        tile = zone.tiles[r][c]
        lines.append(("", (0, 0, 0)))  # blank separator
        lines.append((f"Cell: ({c}, {r})  {tile}", HUD_TEXT))
        lines.append((f"Floor: {fh:.2f}  Ceil: {ch:.2f}  Light: {ll:.2f}",
                      HUD_TEXT))
        lines.append((f"Face: {hit.part}.{hit.face.name}", HUD_TEXT))

    return lines
