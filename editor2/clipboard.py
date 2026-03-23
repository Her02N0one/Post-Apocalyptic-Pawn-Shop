"""editor2/clipboard.py — Copy/paste operations for zone cell data.

Provides ``copy_selection()`` to serialise selected cells and
``paste_clipboard()`` to apply them via the command bus.  Stateless
functions that take the clipboard data as arguments.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.zones import Zone
    from editor2.core import CommandBus
    from editor2.selection import SelectionState


def copy_cells(zone: Zone, selection: SelectionState) -> tuple[list[dict], tuple[int, int]] | None:
    """Serialise selected cells into a clipboard payload.

    Returns ``(cells_list, (rmin, cmin))`` or ``None`` if nothing to copy.
    """
    if not selection.has_cells():
        return None
    bounds = selection.bounds()
    if not bounds:
        return None
    rmin, cmin, _, _ = bounds
    cells: list[dict] = []
    for r, c in selection.iter_cells():
        cell = {
            "dr": r - rmin, "dc": c - cmin,
            "tile": zone.tiles[r][c],
            "fh": zone.floor_heights[r][c] if zone.floor_heights else 0.0,
            "ch": zone.ceil_heights[r][c] if zone.ceil_heights else 10.0,
            "ft": zone.floor_textures[r][c] if zone.floor_textures else "",
            "ct": zone.ceil_textures[r][c] if zone.ceil_textures else "",
            "wt": zone.wall_textures[r][c] if zone.wall_textures else "",
            "face_tex": list(zone.face_textures[r][c]) if zone.face_textures else [""] * 4,
        }
        cells.append(cell)
    return cells, (rmin, cmin)


def paste_cells(
    clipboard: list[dict],
    origin: tuple[int, int],
    zone: Zone,
    bus: "CommandBus",
    target: tuple[int, int] | None = None,
) -> int:
    """Paste *clipboard* cells into *zone* via *bus*.

    *target* is ``(row, col)`` for the top-left paste position, or
    ``None`` to paste at the original *origin*.

    Returns the number of cells actually pasted (within bounds).
    """
    from editor2.core import BatchCmd, SetCellFieldCmd, SetFaceFieldCmd

    if target is not None:
        base_r, base_c = target
    else:
        base_r, base_c = origin

    cmds: list = []
    count = 0
    for cell in clipboard:
        r = base_r + cell["dr"]
        c = base_c + cell["dc"]
        if not (0 <= r < zone.height and 0 <= c < zone.width):
            continue
        count += 1
        cmds.append(SetCellFieldCmd(r, c, "tiles", cell["tile"]))
        cmds.append(SetCellFieldCmd(r, c, "floor_heights", cell["fh"]))
        cmds.append(SetCellFieldCmd(r, c, "ceil_heights", cell["ch"]))
        if zone.floor_textures:
            cmds.append(SetCellFieldCmd(r, c, "floor_textures", cell["ft"]))
        if zone.ceil_textures:
            cmds.append(SetCellFieldCmd(r, c, "ceil_textures", cell["ct"]))
        if zone.wall_textures:
            cmds.append(SetCellFieldCmd(r, c, "wall_textures", cell["wt"]))
        if zone.face_textures:
            for fi in range(4):
                cmds.append(SetFaceFieldCmd(r, c, fi, "face_textures",
                                            cell["face_tex"][fi]))
    if cmds:
        bus.execute(BatchCmd(cmds, f"Paste {count} cells"))
    return count
