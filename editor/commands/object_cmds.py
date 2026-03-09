"""editor/commands/object_cmds.py — Object tool command definitions + handlers.

Phase 0: wraps existing entity / box / quad / portal / curve / overlay
methods.  Each command wraps a single mutation; handlers delegate to the
editor's existing mixin methods with undo suppressed.

Entity commands:   EntityPlace, EntityDelete, EntityMove, EntityRotate
Box commands:      BoxPlace, BoxDelete, BoxMove, BoxRotot90, BoxRotateFine,
                   BoxAdjustSize, BoxShiftZ
Quad commands:     QuadPlace, QuadDelete, QuadMove, QuadRotate,
                   QuadAdjustSize, QuadToggleTwosided, QuadPaint
Portal commands:   PortalPlace, PortalDelete
Curve commands:    CurvePlace, CurveDelete, CurveMove, CurvePaint,
                   CurveAdjustRadius, CurveAdjustAngleStart,
                   CurveAdjustAngleEnd
Overlay commands:  OverlayFinishPlace, OverlayDelete, OverlayMove,
                   OverlayPaint, OverlayToggleTransparent,
                   OverlayAdjustHeight
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from editor.commands.base import (
    Command, CommandBus,
    suppress_undo, suppress_and_detect, detect_change,
)


# ═══════════════════════════════════════════════════════════════════
# Entity commands
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class EntityPlace(Command):
    """Place a new entity at the aimed ground position."""
    pass


@dataclass(frozen=True)
class EntityDelete(Command):
    """Delete an entity."""
    index: int | None = None


@dataclass(frozen=True)
class EntityMove(Command):
    """Move the selected entity to the aimed position."""
    pass


@dataclass(frozen=True)
class EntityRotate(Command):
    """Rotate the selected entity by 45° increments."""
    direction: int = 1


# ═══════════════════════════════════════════════════════════════════
# Box (prism) commands
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class BoxPlace(Command):
    """Place a new prism at the aimed position."""
    pass


@dataclass(frozen=True)
class BoxDelete(Command):
    """Delete a prism."""
    index: int | None = None


@dataclass(frozen=True)
class BoxMove(Command):
    """Move the selected prism to the aimed position."""
    pass


@dataclass(frozen=True)
class BoxRotate90(Command):
    """Rotate prism by 90° (R key)."""
    pass


@dataclass(frozen=True)
class BoxRotateFine(Command):
    """Rotate selected prism by 15° increments (Shift+Scroll)."""
    direction: int = 1


@dataclass(frozen=True)
class BoxAdjustSize(Command):
    """Adjust prism dimension (Scroll variants)."""
    direction: int = 1
    axis: str = "w"  # "w", "d", or "h"


@dataclass(frozen=True)
class BoxShiftZ(Command):
    """Move selected prism up/down (Scroll when selected)."""
    direction: int = 1


# ═══════════════════════════════════════════════════════════════════
# Quad commands
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class QuadPlace(Command):
    """Place a new quad at the aimed ground position."""
    pass


@dataclass(frozen=True)
class QuadDelete(Command):
    """Delete a quad."""
    index: int | None = None


@dataclass(frozen=True)
class QuadMove(Command):
    """Move the selected quad to the aimed position."""
    pass


@dataclass(frozen=True)
class QuadRotate(Command):
    """Rotate selected quad by 15° increments."""
    direction: int = 1


@dataclass(frozen=True)
class QuadAdjustSize(Command):
    """Adjust quad width (Ctrl+Scroll)."""
    direction: int = 1


@dataclass(frozen=True)
class QuadToggleTwosided(Command):
    """Toggle two_sided flag on selected quad (MMB)."""
    pass


@dataclass(frozen=True)
class QuadPaint(Command):
    """Apply current texture to selected quad."""
    pass


# ═══════════════════════════════════════════════════════════════════
# Portal commands
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class PortalPlace(Command):
    """Place a portal on the aimed wall face."""
    pass


@dataclass(frozen=True)
class PortalDelete(Command):
    """Delete portal on the aimed wall face."""
    pass


# ═══════════════════════════════════════════════════════════════════
# Curve commands
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class CurvePlace(Command):
    """Place a new curve at the aimed position."""
    pass


@dataclass(frozen=True)
class CurveDelete(Command):
    """Delete a curve."""
    index: int | None = None


@dataclass(frozen=True)
class CurveMove(Command):
    """Move the selected curve to the aimed position."""
    pass


@dataclass(frozen=True)
class CurvePaint(Command):
    """Apply current texture to selected curve."""
    pass


@dataclass(frozen=True)
class CurveAdjustRadius(Command):
    """Adjust curve radius (Scroll)."""
    direction: int = 1


@dataclass(frozen=True)
class CurveAdjustAngleStart(Command):
    """Adjust curve arc start angle (Shift+Scroll)."""
    direction: int = 1


@dataclass(frozen=True)
class CurveAdjustAngleEnd(Command):
    """Adjust curve arc end angle (Ctrl+Scroll)."""
    direction: int = 1


# ═══════════════════════════════════════════════════════════════════
# Overlay wall commands
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class OverlayFinishPlace(Command):
    """Set the second endpoint and create the overlay wall."""
    pass


@dataclass(frozen=True)
class OverlayDelete(Command):
    """Delete an overlay wall."""
    index: int | None = None


@dataclass(frozen=True)
class OverlayMove(Command):
    """Move the selected overlay wall to the aimed position."""
    pass


@dataclass(frozen=True)
class OverlayPaint(Command):
    """Apply current texture to selected overlay wall."""
    pass


@dataclass(frozen=True)
class OverlayToggleTransparent(Command):
    """Toggle transparent flag on selected overlay wall (MMB)."""
    pass


@dataclass(frozen=True)
class OverlayAdjustHeight(Command):
    """Adjust overlay wall height_scale (Shift+Scroll)."""
    direction: int = 1


# ═══════════════════════════════════════════════════════════════════
# Handler factories — Entity
# ═══════════════════════════════════════════════════════════════════

def _make_entity_place_handler(editor: Any):
    def handle(cmd: EntityPlace) -> bool:
        return suppress_and_detect(editor, editor._ent_place)
    return handle


def _make_entity_delete_handler(editor: Any):
    def handle(cmd: EntityDelete) -> bool:
        return suppress_and_detect(editor, editor._ent_delete, cmd.index)
    return handle


def _make_entity_move_handler(editor: Any):
    def handle(cmd: EntityMove) -> bool:
        return suppress_and_detect(editor, editor._ent_move_to_aimed)
    return handle


def _make_entity_rotate_handler(editor: Any):
    def handle(cmd: EntityRotate) -> bool:
        return detect_change(editor, editor._ent_rotate, cmd.direction)
    return handle


# ═══════════════════════════════════════════════════════════════════
# Handler factories — Box
# ═══════════════════════════════════════════════════════════════════

def _make_box_place_handler(editor: Any):
    def handle(cmd: BoxPlace) -> bool:
        return suppress_and_detect(editor, editor._box_place)
    return handle


def _make_box_delete_handler(editor: Any):
    def handle(cmd: BoxDelete) -> bool:
        return suppress_and_detect(editor, editor._box_delete, cmd.index)
    return handle


def _make_box_move_handler(editor: Any):
    def handle(cmd: BoxMove) -> bool:
        return suppress_and_detect(editor, editor._box_move_to_aimed)
    return handle


def _make_box_rotate90_handler(editor: Any):
    def handle(cmd: BoxRotate90) -> bool:
        return detect_change(editor, editor._box_rotate_90)
    return handle


def _make_box_rotate_fine_handler(editor: Any):
    def handle(cmd: BoxRotateFine) -> bool:
        return detect_change(editor, editor._box_rotate_fine, cmd.direction)
    return handle


def _make_box_adjust_size_handler(editor: Any):
    def handle(cmd: BoxAdjustSize) -> bool:
        return detect_change(editor, editor._box_adjust_size,
                             cmd.direction, cmd.axis)
    return handle


def _make_box_shift_z_handler(editor: Any):
    def handle(cmd: BoxShiftZ) -> bool:
        return detect_change(editor, editor._box_shift_z, cmd.direction)
    return handle


# ═══════════════════════════════════════════════════════════════════
# Handler factories — Quad
# ═══════════════════════════════════════════════════════════════════

def _make_quad_place_handler(editor: Any):
    def handle(cmd: QuadPlace) -> bool:
        return suppress_and_detect(editor, editor._quad_place)
    return handle


def _make_quad_delete_handler(editor: Any):
    def handle(cmd: QuadDelete) -> bool:
        return suppress_and_detect(editor, editor._quad_delete, cmd.index)
    return handle


def _make_quad_move_handler(editor: Any):
    def handle(cmd: QuadMove) -> bool:
        return suppress_and_detect(editor, editor._quad_move_to_aimed)
    return handle


def _make_quad_rotate_handler(editor: Any):
    def handle(cmd: QuadRotate) -> bool:
        return detect_change(editor, editor._quad_rotate, cmd.direction)
    return handle


def _make_quad_adjust_size_handler(editor: Any):
    def handle(cmd: QuadAdjustSize) -> bool:
        return detect_change(editor, editor._quad_adjust_size, cmd.direction)
    return handle


def _make_quad_toggle_twosided_handler(editor: Any):
    def handle(cmd: QuadToggleTwosided) -> bool:
        return suppress_and_detect(editor, editor._quad_toggle_twosided)
    return handle


def _make_quad_paint_handler(editor: Any):
    def handle(cmd: QuadPaint) -> bool:
        return suppress_and_detect(editor, editor._quad_paint)
    return handle


# ═══════════════════════════════════════════════════════════════════
# Handler factories — Portal
# ═══════════════════════════════════════════════════════════════════

def _make_portal_place_handler(editor: Any):
    def handle(cmd: PortalPlace) -> bool:
        return suppress_and_detect(editor, editor._portal_place)
    return handle


def _make_portal_delete_handler(editor: Any):
    def handle(cmd: PortalDelete) -> bool:
        return suppress_and_detect(editor, editor._portal_delete)
    return handle


# ═══════════════════════════════════════════════════════════════════
# Handler factories — Curve
# ═══════════════════════════════════════════════════════════════════

def _make_curve_place_handler(editor: Any):
    def handle(cmd: CurvePlace) -> bool:
        return suppress_and_detect(editor, editor._curve_place)
    return handle


def _make_curve_delete_handler(editor: Any):
    def handle(cmd: CurveDelete) -> bool:
        return suppress_and_detect(editor, editor._curve_delete, cmd.index)
    return handle


def _make_curve_move_handler(editor: Any):
    def handle(cmd: CurveMove) -> bool:
        return suppress_and_detect(editor, editor._curve_move_to_aimed)
    return handle


def _make_curve_paint_handler(editor: Any):
    def handle(cmd: CurvePaint) -> bool:
        return suppress_and_detect(editor, editor._curve_paint)
    return handle


def _make_curve_adjust_radius_handler(editor: Any):
    def handle(cmd: CurveAdjustRadius) -> bool:
        return detect_change(editor, editor._curve_adjust_radius, cmd.direction)
    return handle


def _make_curve_adjust_angle_start_handler(editor: Any):
    def handle(cmd: CurveAdjustAngleStart) -> bool:
        return detect_change(editor, editor._curve_adjust_angle_start,
                             cmd.direction)
    return handle


def _make_curve_adjust_angle_end_handler(editor: Any):
    def handle(cmd: CurveAdjustAngleEnd) -> bool:
        return detect_change(editor, editor._curve_adjust_angle_end,
                             cmd.direction)
    return handle


# ═══════════════════════════════════════════════════════════════════
# Handler factories — Overlay
# ═══════════════════════════════════════════════════════════════════

def _make_overlay_finish_place_handler(editor: Any):
    def handle(cmd: OverlayFinishPlace) -> bool:
        return suppress_and_detect(editor, editor._ow_finish_place)
    return handle


def _make_overlay_delete_handler(editor: Any):
    def handle(cmd: OverlayDelete) -> bool:
        return suppress_and_detect(editor, editor._ow_delete, cmd.index)
    return handle


def _make_overlay_move_handler(editor: Any):
    def handle(cmd: OverlayMove) -> bool:
        return suppress_and_detect(editor, editor._ow_move_to_aimed)
    return handle


def _make_overlay_paint_handler(editor: Any):
    def handle(cmd: OverlayPaint) -> bool:
        return suppress_and_detect(editor, editor._ow_paint)
    return handle


def _make_overlay_toggle_transparent_handler(editor: Any):
    def handle(cmd: OverlayToggleTransparent) -> bool:
        return suppress_and_detect(editor, editor._ow_toggle_transparent)
    return handle


def _make_overlay_adjust_height_handler(editor: Any):
    def handle(cmd: OverlayAdjustHeight) -> bool:
        return detect_change(editor, editor._ow_adjust_height, cmd.direction)
    return handle


# ═══════════════════════════════════════════════════════════════════
# Bulk registration
# ═══════════════════════════════════════════════════════════════════

def register_object_handlers(bus: CommandBus, editor: Any) -> None:
    """Register all object (entity/box/quad/portal/curve/overlay) handlers."""
    # Entity
    bus.register(EntityPlace,           _make_entity_place_handler(editor))
    bus.register(EntityDelete,          _make_entity_delete_handler(editor))
    bus.register(EntityMove,            _make_entity_move_handler(editor))
    bus.register(EntityRotate,          _make_entity_rotate_handler(editor))
    # Box
    bus.register(BoxPlace,              _make_box_place_handler(editor))
    bus.register(BoxDelete,             _make_box_delete_handler(editor))
    bus.register(BoxMove,               _make_box_move_handler(editor))
    bus.register(BoxRotate90,           _make_box_rotate90_handler(editor))
    bus.register(BoxRotateFine,         _make_box_rotate_fine_handler(editor))
    bus.register(BoxAdjustSize,         _make_box_adjust_size_handler(editor))
    bus.register(BoxShiftZ,             _make_box_shift_z_handler(editor))
    # Quad
    bus.register(QuadPlace,             _make_quad_place_handler(editor))
    bus.register(QuadDelete,            _make_quad_delete_handler(editor))
    bus.register(QuadMove,              _make_quad_move_handler(editor))
    bus.register(QuadRotate,            _make_quad_rotate_handler(editor))
    bus.register(QuadAdjustSize,        _make_quad_adjust_size_handler(editor))
    bus.register(QuadToggleTwosided,    _make_quad_toggle_twosided_handler(editor))
    bus.register(QuadPaint,             _make_quad_paint_handler(editor))
    # Portal
    bus.register(PortalPlace,           _make_portal_place_handler(editor))
    bus.register(PortalDelete,          _make_portal_delete_handler(editor))
    # Curve
    bus.register(CurvePlace,            _make_curve_place_handler(editor))
    bus.register(CurveDelete,           _make_curve_delete_handler(editor))
    bus.register(CurveMove,             _make_curve_move_handler(editor))
    bus.register(CurvePaint,            _make_curve_paint_handler(editor))
    bus.register(CurveAdjustRadius,     _make_curve_adjust_radius_handler(editor))
    bus.register(CurveAdjustAngleStart, _make_curve_adjust_angle_start_handler(editor))
    bus.register(CurveAdjustAngleEnd,   _make_curve_adjust_angle_end_handler(editor))
    # Overlay
    bus.register(OverlayFinishPlace,         _make_overlay_finish_place_handler(editor))
    bus.register(OverlayDelete,              _make_overlay_delete_handler(editor))
    bus.register(OverlayMove,                _make_overlay_move_handler(editor))
    bus.register(OverlayPaint,               _make_overlay_paint_handler(editor))
    bus.register(OverlayToggleTransparent,   _make_overlay_toggle_transparent_handler(editor))
    bus.register(OverlayAdjustHeight,        _make_overlay_adjust_height_handler(editor))
