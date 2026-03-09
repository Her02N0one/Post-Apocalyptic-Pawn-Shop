"""editor/commands/paint_cmds.py — Paint tool command definitions + handlers.

Phase 0: wraps existing paint methods.  The commands represent the
high-level paint operations; handlers delegate to the editor's existing
``_paint()`` / ``_erase_texture()`` / ``_paint_all()`` methods.

Commands
~~~~~~~~
* ``PaintFace``       — paint one face of a cell
* ``PaintAllFaces``   — paint every surface of a cell
* ``EraseFace``       — erase texture from one face
* ``PaintPrismFace``  — paint one (or all) face(s) of a prism
* ``ErasePrismFace``  — erase one (or all) face(s) of a prism
* ``PaintQuad``       — paint a quad's texture
* ``EraseQuad``       — erase a quad's texture
* ``FloodFill``       — BFS flood fill from a cell
* ``FloodClear``      — BFS flood clear from a cell
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from editor.commands.base import Command, CommandBus


# ── Command definitions ───────────────────────────────────────────

@dataclass(frozen=True)
class PaintFace(Command):
    """Paint the currently aimed face with the editor's current texture.

    This is a thin wrapper — the handler calls ``editor._paint()``
    which reads ``editor.aimed`` and ``editor.current_texture``.
    The command exists to funnel the mutation through the bus.
    """
    pass


@dataclass(frozen=True)
class PaintAllFaces(Command):
    """Shift+LMB: paint every surface of the aimed cell."""
    pass


@dataclass(frozen=True)
class EraseFace(Command):
    """Erase the texture on the currently aimed face."""
    pass


@dataclass(frozen=True)
class PaintPrismFace(Command):
    """Paint a prism face (or all faces if face is None)."""
    index: int
    face: str | None = None


@dataclass(frozen=True)
class ErasePrismFace(Command):
    """Erase a prism face (or all faces if face is None)."""
    index: int
    face: str | None = None


@dataclass(frozen=True)
class PaintQuad(Command):
    """Paint a quad with the current texture."""
    index: int


@dataclass(frozen=True)
class EraseQuad(Command):
    """Erase a quad's texture."""
    index: int


@dataclass(frozen=True)
class FloodFill(Command):
    """BFS flood fill from the aimed cell."""
    pass


@dataclass(frozen=True)
class FloodClear(Command):
    """BFS flood clear from the aimed cell."""
    pass


@dataclass(frozen=True)
class SelectionFillTexture(Command):
    """Fill all selected cells with the current texture."""
    pass


@dataclass(frozen=True)
class SelectionClearTextures(Command):
    """Clear textures on all selected cells."""
    pass


@dataclass(frozen=True)
class ContinuousPaint(Command):
    """Continuous paint while dragging (execute_continuation path)."""
    pass


# ── Handler factories ─────────────────────────────────────────────

def _make_paint_face_handler(editor: Any):
    def handle(cmd: PaintFace) -> bool:
        # _paint() is void — detect mutation via the dirty flag.
        saved = editor.dirty
        editor.dirty = False
        editor._paint(push_undo=False)
        changed = editor.dirty
        editor.dirty = saved or changed
        return changed
    return handle


def _make_continuous_paint_handler(editor: Any):
    def handle(cmd: ContinuousPaint) -> bool:
        # Identical to PaintFace — called via execute_continuation()
        # which already skips the undo push.
        saved = editor.dirty
        editor.dirty = False
        editor._paint(push_undo=False)
        changed = editor.dirty
        editor.dirty = saved or changed
        return changed
    return handle


def _make_paint_all_handler(editor: Any):
    def handle(cmd: PaintAllFaces) -> bool:
        if not editor.aimed:
            return False
        # _paint_all does its own texturing without undo push
        zone = editor.zone
        r, c = editor.aimed.row, editor.aimed.col
        tex = editor.current_texture

        editor._ensure_face_textures()

        if zone.floor_textures:
            zone.floor_textures[r][c] = tex
        if zone.ceil_textures:
            zone.ceil_textures[r][c] = tex
        zone.wall_textures[r][c] = tex
        zone.face_textures[r][c] = [tex, tex, tex, tex]

        if zone.floor_step_textures and len(zone.floor_step_textures) > r:
            zone.floor_step_textures[r][c] = [tex, tex, tex, tex]
        if zone.ceil_step_textures and len(zone.ceil_step_textures) > r:
            zone.ceil_step_textures[r][c] = [tex, tex, tex, tex]

        f2t = getattr(zone, 'floor2_textures', None)
        if f2t and len(f2t) > r and len(f2t[r]) > c:
            f2t[r][c] = tex
        c2t = getattr(zone, 'ceil2_textures', None)
        if c2t and len(c2t) > r and len(c2t[r]) > c:
            c2t[r][c] = tex

        return True
    return handle


def _make_erase_face_handler(editor: Any):
    def handle(cmd: EraseFace) -> bool:
        if not editor.aimed or editor.aimed.face == "ground":
            return False
        # Call the existing method but skip its internal undo push.
        # We temporarily override _push_undo to a no-op.
        _orig = editor._push_undo
        editor._push_undo = lambda: None
        try:
            editor._erase_texture()
        finally:
            editor._push_undo = _orig
        return True
    return handle


def _make_paint_prism_handler(editor: Any):
    def handle(cmd: PaintPrismFace) -> bool:
        zone = editor.zone
        if not zone or not zone.boxes:
            return False
        if cmd.index < 0 or cmd.index >= len(zone.boxes):
            return False
        tex = zone.boxes[cmd.index].setdefault("textures", {})
        key_map = {
            "north": "N", "south": "S", "east": "E", "west": "W",
            "top": "top", "bot": "bot",
        }
        if cmd.face and cmd.face in key_map:
            tex[key_map[cmd.face]] = editor.current_texture
        else:
            for f in ("N", "S", "E", "W", "top", "bot"):
                tex[f] = editor.current_texture
        return True
    return handle


def _make_erase_prism_handler(editor: Any):
    def handle(cmd: ErasePrismFace) -> bool:
        zone = editor.zone
        if not zone or not zone.boxes:
            return False
        if cmd.index < 0 or cmd.index >= len(zone.boxes):
            return False
        tex = zone.boxes[cmd.index].setdefault("textures", {})
        key_map = {
            "north": "N", "south": "S", "east": "E", "west": "W",
            "top": "top", "bot": "bot",
        }
        if cmd.face and cmd.face in key_map:
            tex[key_map[cmd.face]] = ""
        else:
            for f in ("N", "S", "E", "W", "top", "bot"):
                tex[f] = ""
        return True
    return handle


def _make_paint_quad_handler(editor: Any):
    def handle(cmd: PaintQuad) -> bool:
        zone = editor.zone
        if not zone or not zone.quads:
            return False
        if cmd.index < 0 or cmd.index >= len(zone.quads):
            return False
        zone.quads[cmd.index]["texture"] = editor.current_texture
        return True
    return handle


def _make_erase_quad_handler(editor: Any):
    def handle(cmd: EraseQuad) -> bool:
        zone = editor.zone
        if not zone or not zone.quads:
            return False
        if cmd.index < 0 or cmd.index >= len(zone.quads):
            return False
        zone.quads[cmd.index]["texture"] = ""
        return True
    return handle


def _make_flood_fill_handler(editor: Any):
    def handle(cmd: FloodFill) -> bool:
        if not editor.aimed:
            return False
        # _fill() calls _push_undo internally — suppress it since the bus
        # already pushed.  Return _fill()'s bool to indicate change.
        _orig = editor._push_undo
        editor._push_undo = lambda: None
        try:
            return editor._fill()
        finally:
            editor._push_undo = _orig
    return handle


def _make_flood_clear_handler(editor: Any):
    def handle(cmd: FloodClear) -> bool:
        if not editor.aimed:
            return False
        _orig = editor._push_undo
        editor._push_undo = lambda: None
        try:
            return editor._fill_clear()
        finally:
            editor._push_undo = _orig
    return handle


def _make_sel_fill_handler(editor: Any):
    def handle(cmd: SelectionFillTexture) -> bool:
        if not editor._has_selection():
            return False
        _orig = editor._push_undo
        editor._push_undo = lambda: None
        try:
            return editor._sel_fill_texture()
        finally:
            editor._push_undo = _orig
    return handle


def _make_sel_clear_handler(editor: Any):
    def handle(cmd: SelectionClearTextures) -> bool:
        if not editor._has_selection():
            return False
        _orig = editor._push_undo
        editor._push_undo = lambda: None
        try:
            return editor._sel_clear_textures()
        finally:
            editor._push_undo = _orig
    return handle


# ── Bulk registration ─────────────────────────────────────────────

def register_paint_handlers(bus: CommandBus, editor: Any) -> None:
    """Register all paint command handlers on *bus*."""
    bus.register(PaintFace,               _make_paint_face_handler(editor))
    bus.register(PaintAllFaces,           _make_paint_all_handler(editor))
    bus.register(EraseFace,               _make_erase_face_handler(editor))
    bus.register(PaintPrismFace,          _make_paint_prism_handler(editor))
    bus.register(ErasePrismFace,          _make_erase_prism_handler(editor))
    bus.register(PaintQuad,               _make_paint_quad_handler(editor))
    bus.register(EraseQuad,               _make_erase_quad_handler(editor))
    bus.register(FloodFill,               _make_flood_fill_handler(editor))
    bus.register(FloodClear,              _make_flood_clear_handler(editor))
    bus.register(SelectionFillTexture,    _make_sel_fill_handler(editor))
    bus.register(SelectionClearTextures,  _make_sel_clear_handler(editor))
    bus.register(ContinuousPaint,         _make_continuous_paint_handler(editor))
