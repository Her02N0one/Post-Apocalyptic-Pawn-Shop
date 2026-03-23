"""editor2/tools/entity_shapes.py — 3D marker geometry for entities.

Factored out of ``entity.py`` to keep per-module size manageable.
Provides:
- ``_get_entity_shape``   — extract shape metadata from an EntityDef
- ``_entity_marker``      — build overlay geometry for an existing entity
- ``_build_box_marker``   — axis-aligned rotated box (prism entities)
- ``_build_cylinder_marker`` — octagonal cylinder (billboard entities)
- ``_build_wall_quad_marker`` — flat wall-flush quad (wall entities)
- ``_placement_ghost``    — translucent preview marker
"""

from __future__ import annotations

import math

from core.zones import Zone
from core.zones.objects import EntityDescriptor
from editor2.picking import CellHit
from editor2.tools import Overlay, OverlayMode
from editor2.tools.entity_wall import (
    _is_wall_entity_type,
    _wall_position,
    _wall_hit_for_placement,
)

# ── Constants ─────────────────────────────────────────────────────

_PILLAR_SEGMENTS = 8   # octagonal cross-section for billboard entities
_BOX_ALPHA_BODY = 0.30
_BOX_ALPHA_EDGE = 0.50


# ── Shape metadata ────────────────────────────────────────────────

def _get_entity_shape(edef, wall_face: str | None = None) -> dict:
    """Extract shape info from an EntityDef for marker rendering.

    Returns a dict with keys:
        shape: "prism" | "cylinder" | "wall_quad"
        width, depth, height, elevation: floats
        color: (r, g, b) 0..1
        wall_face: str | None
    """
    if edef is None:
        return {
            "shape": "cylinder", "width": 0.4, "depth": 0.4,
            "height": 0.8, "elevation": 0.0,
            "color": (0.8, 0.8, 0.8), "wall_face": None,
        }

    cr, cg, cb = edef.color[0] / 255, edef.color[1] / 255, edef.color[2] / 255

    # Wall-mounted entity → flat quad
    if wall_face is not None:
        h = max(edef.scale, 0.3)
        return {
            "shape": "wall_quad",
            "width": h,        # quad dimensions on the wall plane
            "depth": 0.02,     # very thin
            "height": h,
            "elevation": 0.0,
            "color": (cr, cg, cb),
            "wall_face": wall_face,
        }

    if edef.render_type == "prism":
        return {
            "shape": "prism",
            "width": edef.width,
            "depth": edef.depth,
            "height": edef.height,
            "elevation": edef.elevation,
            "color": (cr, cg, cb),
            "wall_face": None,
        }
    else:
        # Billboard / 8way — use scale for height, ~0.3 radius cylinder
        h = max(edef.scale, 0.3)
        return {
            "shape": "cylinder",
            "width": 0.3, "depth": 0.3,
            "height": h,
            "elevation": 0.0,
            "color": (cr, cg, cb),
            "wall_face": None,
        }


# ── Main marker builder ──────────────────────────────────────────

def _entity_marker(
    ent: EntityDescriptor,
    zone: Zone,
    is_selected: bool = False,
    is_hovered: bool = False,
    detailed: bool = False,
) -> list[Overlay]:
    """Build 3D marker geometry for a single entity.

    Prism entities → axis-aligned box matching their actual width/depth/height.
    Billboard entities → octagonal cylinder scaled to their scale value.
    Wall entities → flat quad flush against the wall at wall_height.
    """
    from core.entity_defs import get_entity_def

    edef = get_entity_def(ent.type)
    wall_face = ent.extra.get("wall_face")
    shape = _get_entity_shape(edef, wall_face)
    cr, cg, cb = shape["color"]

    ex, ez = ent.x, ent.y        # world X, Z
    row, col = int(ez), int(ex)
    fh = 0.0
    if 0 <= row < zone.height and 0 <= col < zone.width:
        fh = zone.floor_heights[row][col] if zone.floor_heights else 0.0

    # Wall entities use wall_height for elevation instead of floor.
    # wall_height is the entity BASE (bottom), matching the 2.5D
    # renderers' convention.
    wall_height = ent.extra.get("wall_height")
    if wall_height is not None:
        base_y = float(wall_height) + 0.005
        top_y = base_y + shape["height"]
    else:
        base_y = fh + shape["elevation"] + 0.005
        top_y = base_y + shape["height"]

    # Alpha varies by state
    if is_selected:
        body_alpha = 0.55
        edge_alpha = 0.9
    elif is_hovered:
        body_alpha = 0.45
        edge_alpha = 0.75
    else:
        body_alpha = _BOX_ALPHA_BODY
        edge_alpha = _BOX_ALPHA_EDGE

    ovls: list[Overlay] = []

    if shape["shape"] == "wall_quad":
        ovls.extend(_build_wall_quad_marker(
            ex, ez, base_y, top_y,
            shape["width"], wall_face or "north",
            (cr, cg, cb), body_alpha, edge_alpha,
        ))
    elif shape["shape"] == "prism":
        ovls.extend(_build_box_marker(
            ex, ez, base_y, top_y,
            shape["width"], shape["depth"],
            ent.angle,
            (cr, cg, cb), body_alpha, edge_alpha,
        ))
    else:
        ovls.extend(_build_cylinder_marker(
            ex, ez, base_y, top_y,
            shape["width"] * 0.5,  # radius
            (cr, cg, cb), body_alpha, edge_alpha,
        ))

    # ── Selection / hover ring at mid-height ──────────────────
    if is_selected or is_hovered:
        ring_y = (base_y + top_y) * 0.5
        ring_r = max(shape["width"], shape["depth"]) * 0.5 + 0.08
        ring_col = (1.0, 1.0, 0.2, 0.85) if is_selected else (1.0, 1.0, 1.0, 0.6)
        seg = _PILLAR_SEGMENTS
        ring_verts: list[tuple[float, float, float]] = []
        for i in range(seg):
            j = (i + 1) % seg
            a0 = 2 * math.pi * i / seg
            a1 = 2 * math.pi * j / seg
            ring_verts.extend([
                (ex + math.cos(a0) * ring_r, ring_y, ez + math.sin(a0) * ring_r),
                (ex + math.cos(a1) * ring_r, ring_y, ez + math.sin(a1) * ring_r),
            ])
        ovls.append(Overlay(mode=OverlayMode.LINES, verts=ring_verts, color=ring_col))

    # ── Direction arrow (skip for wall entities — facing is implicit) ──
    if wall_face is None and (detailed or is_selected or is_hovered):
        arrow_y = base_y + shape["height"] * 0.35
        arrow_len = max(shape["width"], shape["depth"]) * 0.5 + 0.25
        dx = math.cos(ent.angle) * arrow_len
        dz = -math.sin(ent.angle) * arrow_len
        tip_x, tip_z = ex + dx, ez + dz
        ovls.append(Overlay(
            mode=OverlayMode.LINES,
            verts=[(ex, arrow_y, ez), (tip_x, arrow_y, tip_z)],
            color=(1.0, 1.0, 0.0, 0.9),
        ))
        # Arrowhead wings
        wing_len = 0.15
        for sign in (1, -1):
            wa = ent.angle + math.pi + sign * 0.5
            awx = tip_x + math.cos(wa) * wing_len
            awz = tip_z - math.sin(wa) * wing_len
            ovls.append(Overlay(
                mode=OverlayMode.LINES,
                verts=[(tip_x, arrow_y, tip_z), (awx, arrow_y, awz)],
                color=(1.0, 1.0, 0.0, 0.9),
            ))

    # ── Wall-face normal indicator (for wall entities) ────────
    if wall_face is not None and (detailed or is_selected or is_hovered):
        mid_y = (base_y + top_y) * 0.5
        info = {"south": (0.0, -1.0), "north": (0.0, 1.0),
                "west": (-1.0, 0.0), "east": (1.0, 0.0)}.get(wall_face, (0.0, 0.0))
        ndx, ndz = info
        n_len = 0.35
        n_tip_x = ex + ndx * n_len
        n_tip_z = ez + ndz * n_len
        ovls.append(Overlay(
            mode=OverlayMode.LINES,
            verts=[(ex, mid_y, ez), (n_tip_x, mid_y, n_tip_z)],
            color=(0.3, 0.8, 1.0, 0.9),
        ))

    return ovls


# ── Shape primitives ──────────────────────────────────────────────

def _build_box_marker(
    cx: float, cz: float,
    base_y: float, top_y: float,
    width: float, depth: float,
    angle: float,
    color: tuple[float, float, float],
    body_alpha: float, edge_alpha: float,
) -> list[Overlay]:
    """Build an axis-aligned box (rotated by angle) for prism entities."""
    cr, cg, cb = color
    hw, hd = width * 0.5, depth * 0.5

    # Four corners in local space, rotated by entity angle
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    corners_local = [(-hw, -hd), (hw, -hd), (hw, hd), (-hw, hd)]
    corners: list[tuple[float, float]] = []
    for lx, lz in corners_local:
        rx = cx + lx * cos_a - lz * sin_a
        rz = cz + lx * sin_a + lz * cos_a
        corners.append((rx, rz))

    ovls: list[Overlay] = []

    # Side faces (4 faces, 2 triangles each)
    side_verts: list[tuple[float, float, float]] = []
    for i in range(4):
        j = (i + 1) % 4
        x0, z0 = corners[i]
        x1, z1 = corners[j]
        side_verts.extend([
            (x0, base_y, z0), (x1, base_y, z1), (x1, top_y, z1),
            (x0, base_y, z0), (x1, top_y, z1), (x0, top_y, z0),
        ])
    ovls.append(Overlay(
        mode=OverlayMode.TRIS, verts=side_verts,
        color=(cr, cg, cb, body_alpha),
    ))

    # Top cap
    x0, z0 = corners[0]
    x1, z1 = corners[1]
    x2, z2 = corners[2]
    x3, z3 = corners[3]
    top_verts = [
        (x0, top_y, z0), (x1, top_y, z1), (x2, top_y, z2),
        (x0, top_y, z0), (x2, top_y, z2), (x3, top_y, z3),
    ]
    ovls.append(Overlay(
        mode=OverlayMode.TRIS, verts=top_verts,
        color=(min(cr * 1.3, 1.0), min(cg * 1.3, 1.0), min(cb * 1.3, 1.0),
               body_alpha + 0.1),
    ))

    # Wireframe edges
    edge_verts: list[tuple[float, float, float]] = []
    for i in range(4):
        j = (i + 1) % 4
        x0, z0 = corners[i]
        x1, z1 = corners[j]
        # Vertical edges
        edge_verts.extend([(x0, base_y, z0), (x0, top_y, z0)])
        # Top edges
        edge_verts.extend([(x0, top_y, z0), (x1, top_y, z1)])
        # Bottom edges
        edge_verts.extend([(x0, base_y, z0), (x1, base_y, z1)])
    ovls.append(Overlay(
        mode=OverlayMode.LINES, verts=edge_verts,
        color=(cr, cg, cb, edge_alpha),
    ))

    return ovls


def _build_cylinder_marker(
    cx: float, cz: float,
    base_y: float, top_y: float,
    radius: float,
    color: tuple[float, float, float],
    body_alpha: float, edge_alpha: float,
) -> list[Overlay]:
    """Build an octagonal cylinder for billboard entities."""
    cr, cg, cb = color
    seg = _PILLAR_SEGMENTS
    ring: list[tuple[float, float]] = []
    for i in range(seg):
        a = 2 * math.pi * i / seg
        ring.append((cx + math.cos(a) * radius, cz + math.sin(a) * radius))

    ovls: list[Overlay] = []

    # Side faces
    side_verts: list[tuple[float, float, float]] = []
    for i in range(seg):
        j = (i + 1) % seg
        x0, z0 = ring[i]
        x1, z1 = ring[j]
        side_verts.extend([
            (x0, base_y, z0), (x1, base_y, z1), (x1, top_y, z1),
            (x0, base_y, z0), (x1, top_y, z1), (x0, top_y, z0),
        ])
    ovls.append(Overlay(
        mode=OverlayMode.TRIS, verts=side_verts,
        color=(cr, cg, cb, body_alpha),
    ))

    # Top cap
    cap_verts: list[tuple[float, float, float]] = []
    for i in range(seg):
        j = (i + 1) % seg
        cap_verts.extend([
            (cx, top_y, cz),
            (ring[i][0], top_y, ring[i][1]),
            (ring[j][0], top_y, ring[j][1]),
        ])
    ovls.append(Overlay(
        mode=OverlayMode.TRIS, verts=cap_verts,
        color=(min(cr * 1.3, 1.0), min(cg * 1.3, 1.0), min(cb * 1.3, 1.0),
               body_alpha + 0.1),
    ))

    # Wireframe edges
    edge_verts: list[tuple[float, float, float]] = []
    for i in range(seg):
        x0, z0 = ring[i]
        edge_verts.extend([(x0, base_y, z0), (x0, top_y, z0)])
    for i in range(seg):
        j = (i + 1) % seg
        edge_verts.extend([
            (ring[i][0], top_y, ring[i][1]),
            (ring[j][0], top_y, ring[j][1]),
        ])
    for i in range(seg):
        j = (i + 1) % seg
        edge_verts.extend([
            (ring[i][0], base_y, ring[i][1]),
            (ring[j][0], base_y, ring[j][1]),
        ])
    ovls.append(Overlay(
        mode=OverlayMode.LINES, verts=edge_verts,
        color=(cr, cg, cb, edge_alpha),
    ))

    return ovls


def _build_wall_quad_marker(
    cx: float, cz: float,
    base_y: float, top_y: float,
    width: float,
    wall_face: str,
    color: tuple[float, float, float],
    body_alpha: float, edge_alpha: float,
) -> list[Overlay]:
    """Build a flat quad flush against a wall for wall-mounted entities.

    ``wall_face`` is the outward-normal direction of the entity
    (i.e. the direction the entity faces *away* from the wall).
    The quad is oriented perpendicular to that normal, centered at
    *(cx, (base_y+top_y)/2, cz)* with the given width and spanning
    from *base_y* to *top_y*.
    """
    cr, cg, cb = color
    hw = width * 0.5

    # Compute the four corners of the wall-aligned quad.
    # The quad runs along the wall tangent direction.
    if wall_face in ("north", "south"):
        # Wall runs east-west  →  tangent along X
        corners = [
            (cx - hw, base_y, cz),
            (cx + hw, base_y, cz),
            (cx + hw, top_y, cz),
            (cx - hw, top_y, cz),
        ]
    else:
        # Wall runs north-south  →  tangent along Z
        corners = [
            (cx, base_y, cz - hw),
            (cx, base_y, cz + hw),
            (cx, top_y, cz + hw),
            (cx, top_y, cz - hw),
        ]

    ovls: list[Overlay] = []

    # Filled quad (two triangles)
    ovls.append(Overlay(
        mode=OverlayMode.TRIS,
        verts=[
            corners[0], corners[1], corners[2],
            corners[0], corners[2], corners[3],
        ],
        color=(cr, cg, cb, body_alpha),
    ))

    # Wireframe border
    edge_verts: list[tuple[float, float, float]] = []
    for i in range(4):
        edge_verts.append(corners[i])
        edge_verts.append(corners[(i + 1) % 4])
    ovls.append(Overlay(
        mode=OverlayMode.LINES,
        verts=edge_verts,
        color=(cr, cg, cb, edge_alpha),
    ))

    return ovls


# ── Placement preview ghost ───────────────────────────────────────

def _placement_ghost(
    entity_type: str,
    cx: float, cz: float,
    floor_h: float,
    zone: Zone,
    hit: CellHit | None = None,
    snap: float = 0.0,
) -> list[Overlay]:
    """Build a translucent ghost marker showing where a new entity will land.

    For wall-mountable types hovering a wall face, renders a wall-flush quad
    at the proper height instead of a floor-level marker.
    """
    from core.entity_defs import get_entity_def

    edef = get_entity_def(entity_type)
    is_wall = _is_wall_entity_type(entity_type)

    # Wall ghost — also triggers when looking at the TOP of a wall
    # cell from above (inferred to nearest cardinal face).
    wall_hit = _wall_hit_for_placement(hit) if hit is not None else None
    if is_wall and wall_hit is not None:
        # Compute shape first so we know entity_height for base offset
        from editor2.tools.entity_wall import _wall_face_from_hit
        wface_preview = _wall_face_from_hit(wall_hit) or "north"
        shape = _get_entity_shape(edef, wface_preview)
        wx, wz, wh, wface = _wall_position(wall_hit, zone, snap=snap,
                                              entity_height=shape["height"])
        # Re-derive shape with the actual resolved face
        shape = _get_entity_shape(edef, wface)
        cr, cg, cb = shape["color"]
        ghost_r = min(cr + 0.3, 1.0)
        ghost_g = min(cg + 0.4, 1.0)
        ghost_b = min(cb + 0.2, 1.0)
        # wh is the entity BASE (bottom), matching 2.5D convention
        base_y = wh + 0.005
        top_y = base_y + shape["height"]
        ovls: list[Overlay] = []
        ovls.extend(_build_wall_quad_marker(
            wx, wz, base_y, top_y,
            shape["width"], wface,
            (ghost_r, ghost_g, ghost_b), 0.30, 0.70,
        ))

        # ── Above-view indicators ────────────────────────────
        # When looking from above, the vertical wall quad is edge-on.
        # Add a crosshair on the wall top and a drop line so the
        # placement position is visible from any camera angle.
        from editor2.mesh import compute_cell_boxes
        r, c = wall_hit.row, wall_hit.col
        wall_top = 1.0
        for part, yb, yt in compute_cell_boxes(zone, r, c):
            if part == "wall":
                wall_top = yt
                break
        cross_y = wall_top + 0.02
        arm = 0.18
        ovls.append(Overlay(
            mode=OverlayMode.LINES,
            verts=[
                (wx - arm, cross_y, wz), (wx + arm, cross_y, wz),
                (wx, cross_y, wz - arm), (wx, cross_y, wz + arm),
            ],
            color=(0.3, 1.0, 0.5, 0.7),
        ))
        # Vertical drop line from wall top down to entity centre
        mid_y = (base_y + top_y) * 0.5
        ovls.append(Overlay(
            mode=OverlayMode.LINES,
            verts=[(wx, cross_y, wz), (wx, mid_y, wz)],
            color=(0.3, 1.0, 0.5, 0.45),
        ))
        return ovls

    # Normal floor ghost
    # When the hit is on a wall part, use hit_y so the ghost sits on
    # top of the wall instead of rendering inside the wall mesh.
    if hit is not None and hit.part == "wall":
        floor_h = hit.hit_y
    shape = _get_entity_shape(edef)
    cr, cg, cb = shape["color"]
    base_y = floor_h + shape["elevation"] + 0.005
    top_y = base_y + shape["height"]

    ovls = []
    ghost_r = min(cr + 0.3, 1.0)
    ghost_g = min(cg + 0.4, 1.0)
    ghost_b = min(cb + 0.2, 1.0)
    ghost_body_alpha = 0.18
    ghost_edge_alpha = 0.45

    if shape["shape"] == "prism":
        ovls.extend(_build_box_marker(
            cx, cz, base_y, top_y,
            shape["width"], shape["depth"],
            0.0,
            (ghost_r, ghost_g, ghost_b),
            ghost_body_alpha, ghost_edge_alpha,
        ))
    else:
        ovls.extend(_build_cylinder_marker(
            cx, cz, base_y, top_y,
            shape["width"] * 0.5,
            (ghost_r, ghost_g, ghost_b),
            ghost_body_alpha, ghost_edge_alpha,
        ))

    # Crosshair at base
    cross_y = floor_h + 0.02
    arm = max(shape["width"], shape["depth"]) * 0.5 + 0.15
    ovls.append(Overlay(
        mode=OverlayMode.LINES,
        verts=[
            (cx - arm, cross_y, cz), (cx + arm, cross_y, cz),
            (cx, cross_y, cz - arm), (cx, cross_y, cz + arm),
        ],
        color=(0.3, 1.0, 0.3, 0.6),
    ))

    return ovls
