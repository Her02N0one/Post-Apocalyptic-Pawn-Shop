#!/usr/bin/env python3
"""gen_entity_textures.py — Entity texture pipeline.

Manages the full workflow from entity definition to engine-ready textures:

  1. **template**  — Generate a labelled sprite sheet showing the exact
     cell layout the engine expects (checkerboard fill, borders, state/
     facing labels).  Produces ``<type_id>_sheet.png`` + TOML sidecar.
  2. **detect**    — Compare the entity def fingerprint stored in the
     TOML with the current definition and warn if they diverge.

The atlas loader reads cells directly from the sprite sheet at runtime
— no individual cell PNGs are written to disk.

Artist workflow::

    # New entity — generates template sheet
    python gen_entity_textures.py goblin

    # Artist paints over the sheet in their image editor…

    # Entity def changed — regenerate template (overwrites sheet!)
    python gen_entity_textures.py goblin --force

Output layout:

  • Prism entities →  ``assets/textures/entities/<type_id>/<face>.png``
  • Billboard entities →
      ``<type_id>/<type_id>_sheet.png``  — sprite sheet (artist file)
      ``<type_id>/<type_id>_sheet.toml`` — sidecar with layout metadata

Billboard sheet grid layout:
  Columns = facings (8-way: S, SW, W, NW, N, NE, E, SE)
  Rows    = states  (in definition order)
  Cell    = cell_w × cell_h pixels

Atlas key scheme (descriptive):
  ``<sprite_key>:state_facing``  (e.g. ``dummy:idle_s``, ``dummy:walk_ne``)
  Non-directional: ``<sprite_key>:state``  (e.g. ``item:default``)

Depends only on pygame.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from pathlib import Path

# Headless pygame — only force dummy drivers when running as a script.
# When imported as a library (e.g. from the zone editor), pygame is
# already initialised with a real video driver.
if __name__ == "__main__":
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
import pygame

if not pygame.get_init():
    pygame.init()
try:
    pygame.display.set_mode((1, 1), pygame.NOFRAME)
except pygame.error:
    pass

PROJECT_ROOT = Path(__file__).resolve().parent
ENTITIES_TEX_DIR   = PROJECT_ROOT / "assets" / "textures" / "entities"
BILLBOARD_TEX_DIR  = ENTITIES_TEX_DIR / "billboard"
PRISM_TEX_DIR      = ENTITIES_TEX_DIR / "prism"

# Import after pygame init so tile registry can load
sys.path.insert(0, str(PROJECT_ROOT))
from core.entity_defs import entity_registry, EntityDef

# ── Face naming ──────────────────────────────────────────────────

# Map from local face names to entity_defs.toml compass names
# "front" = the face the entity presents (north in TOML = facing camera)
PRISM_FACES = [
    ("front",  "north"),   # front face
    ("back",   "south"),   # back face
    ("left",   "west"),    # viewer's left
    ("right",  "east"),    # viewer's right
    ("top",    "top"),
    ("bottom", "bottom"),
]

FACING_LABELS_8 = ["S", "SW", "W", "NW", "N", "NE", "E", "SE"]

# ── Colour palette (hue per face) ───────────────────────────────

FACE_COLORS = {
    "front":  (80, 140, 220),   # blue
    "back":   (160, 100, 80),   # brown
    "left":   (100, 180, 100),  # green
    "right":  (180, 100, 180),  # purple
    "side":   (140, 170, 120),  # muted green (shared L+R)
    "top":    (200, 200, 120),  # yellow
    "bottom": (120, 120, 120),  # grey
}

STATE_HUES = [
    (80, 180, 80),    # green
    (200, 80, 80),    # red
    (80, 80, 200),    # blue
    (200, 180, 60),   # yellow
    (180, 80, 200),   # purple
]


# ── Entity-def fingerprinting (change detection) ────────────────

def _visual_fingerprint(edef: EntityDef) -> str:
    """12-char hex hash of visual properties relevant to sheet layout.

    Stored in the TOML sidecar so we can warn when the entity definition
    changes after the artist has already painted the sheet.
    """
    data = {
        "render_type": edef.render_type,
        "directional": edef.directional,
        "states": list(edef.states),
        "sprite_key": edef.sprite_key,
        "scale": edef.scale,
    }
    blob = json.dumps(data, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


def _read_toml_hash(path: Path) -> str:
    """Read ``entity_def_hash`` from a TOML sidecar.

    Checks both ``[meta].entity_def_hash`` (new format) and
    top-level ``entity_def_hash`` (old format).
    """
    try:
        text = path.read_text()
        # Try [meta] section first, then top-level
        m = re.search(r'^entity_def_hash\s*=\s*"([^"]+)"', text, re.M)
        return m.group(1) if m else ""
    except FileNotFoundError:
        return ""

# ── Tiny 5×7 pixel font ─────────────────────────────────────────

_FONT_5x7: dict[str, tuple[int, ...]] = {
    "A": (0x7E, 0x11, 0x11, 0x11, 0x7E),
    "B": (0x7F, 0x49, 0x49, 0x49, 0x36),
    "C": (0x3E, 0x41, 0x41, 0x41, 0x22),
    "D": (0x7F, 0x41, 0x41, 0x41, 0x3E),
    "E": (0x7F, 0x49, 0x49, 0x49, 0x41),
    "F": (0x7F, 0x09, 0x09, 0x09, 0x01),
    "G": (0x3E, 0x41, 0x49, 0x49, 0x3A),
    "H": (0x7F, 0x08, 0x08, 0x08, 0x7F),
    "I": (0x00, 0x41, 0x7F, 0x41, 0x00),
    "J": (0x20, 0x40, 0x41, 0x3F, 0x01),
    "K": (0x7F, 0x08, 0x14, 0x22, 0x41),
    "L": (0x7F, 0x40, 0x40, 0x40, 0x40),
    "M": (0x7F, 0x02, 0x0C, 0x02, 0x7F),
    "N": (0x7F, 0x04, 0x08, 0x10, 0x7F),
    "O": (0x3E, 0x41, 0x41, 0x41, 0x3E),
    "P": (0x7F, 0x09, 0x09, 0x09, 0x06),
    "Q": (0x3E, 0x41, 0x51, 0x21, 0x5E),
    "R": (0x7F, 0x09, 0x19, 0x29, 0x46),
    "S": (0x46, 0x49, 0x49, 0x49, 0x31),
    "T": (0x01, 0x01, 0x7F, 0x01, 0x01),
    "U": (0x3F, 0x40, 0x40, 0x40, 0x3F),
    "V": (0x1F, 0x20, 0x40, 0x20, 0x1F),
    "W": (0x3F, 0x40, 0x30, 0x40, 0x3F),
    "X": (0x63, 0x14, 0x08, 0x14, 0x63),
    "Y": (0x07, 0x08, 0x70, 0x08, 0x07),
    "Z": (0x61, 0x51, 0x49, 0x45, 0x43),
    "0": (0x3E, 0x51, 0x49, 0x45, 0x3E),
    "1": (0x00, 0x42, 0x7F, 0x40, 0x00),
    "2": (0x42, 0x61, 0x51, 0x49, 0x46),
    "3": (0x21, 0x41, 0x45, 0x4B, 0x31),
    "4": (0x18, 0x14, 0x12, 0x7F, 0x10),
    "5": (0x27, 0x45, 0x45, 0x45, 0x39),
    "6": (0x3C, 0x4A, 0x49, 0x49, 0x30),
    "7": (0x01, 0x71, 0x09, 0x05, 0x03),
    "8": (0x36, 0x49, 0x49, 0x49, 0x36),
    "9": (0x06, 0x49, 0x49, 0x29, 0x1E),
    " ": (0x00, 0x00, 0x00, 0x00, 0x00),
    "_": (0x40, 0x40, 0x40, 0x40, 0x40),
    "-": (0x08, 0x08, 0x08, 0x08, 0x08),
    ".": (0x00, 0x60, 0x60, 0x00, 0x00),
    ":": (0x00, 0x36, 0x36, 0x00, 0x00),
    "/": (0x20, 0x10, 0x08, 0x04, 0x02),
    "(": (0x00, 0x1C, 0x22, 0x41, 0x00),
    ")": (0x00, 0x41, 0x22, 0x1C, 0x00),
    "x": (0x00, 0x44, 0x28, 0x10, 0x28),
}


def _draw_text(surf: pygame.Surface, text: str,
               x: int, y: int, color: tuple[int, int, int],
               scale: int = 1) -> int:
    """Draw text using the 5×7 pixel font.  Returns width drawn."""
    cx = x
    for ch in text.upper():
        glyph = _FONT_5x7.get(ch)
        if glyph is None:
            cx += 4 * scale
            continue
        for col_i, col_bits in enumerate(glyph):
            for row_i in range(7):
                if col_bits & (1 << row_i):
                    for sy in range(scale):
                        for sx in range(scale):
                            px = cx + col_i * scale + sx
                            py = y + row_i * scale + sy
                            if 0 <= px < surf.get_width() and 0 <= py < surf.get_height():
                                surf.set_at((px, py), color)
        cx += 6 * scale
    return cx - x


def _text_width(text: str, scale: int = 1) -> int:
    return len(text) * 6 * scale - scale


def _text_height(scale: int = 1) -> int:
    return 7 * scale


def _draw_text_vertical(surf: pygame.Surface, text: str,
                        x: int, y: int, color: tuple[int, int, int],
                        scale: int = 1) -> int:
    """Draw text rotated 90° CW (reads top-to-bottom).  Returns height drawn."""
    cy = y
    for ch in text.upper():
        glyph = _FONT_5x7.get(ch)
        if glyph is None:
            cy += 4 * scale
            continue
        # Rotate each glyph: col→row, row→col (mirrored for CW rotation)
        for col_i, col_bits in enumerate(glyph):
            for row_i in range(7):
                if col_bits & (1 << row_i):
                    for sy in range(scale):
                        for sx in range(scale):
                            # CW 90°: (col, row) → (6-row, col)
                            px = x + (6 - row_i) * scale + sx
                            py = cy + col_i * scale + sy
                            if 0 <= px < surf.get_width() and 0 <= py < surf.get_height():
                                surf.set_at((px, py), color)
        cy += 6 * scale
    return cy - y


def _auto_text(surf: pygame.Surface, text: str,
               region_x: int, region_y: int,
               region_w: int, region_h: int,
               color: tuple[int, int, int],
               scale: int = 0,
               anchor: str = "center") -> None:
    """Draw text, auto-rotating and auto-scaling to fit the region.

    *anchor*: "center", "top", or "bottom" — vertical alignment within region.
    *scale*: 0 = auto-pick largest scale that fits.  >0 = force that scale.

    Tries horizontal first; if the text is wider than *region_w* at any
    viable scale, draws vertically (rotated 90° CW, reading top-to-bottom)
    and picks the largest scale that fits.
    """
    if not text:
        return
    n = len(text)

    # --- Try horizontal first: find largest scale where text fits width ---
    h_scale = 0
    if scale > 0:
        if _text_width(text, scale) <= region_w and _text_height(scale) <= region_h:
            h_scale = scale
    else:
        for s in range(8, 0, -1):
            if _text_width(text, s) <= region_w and _text_height(s) <= region_h:
                h_scale = s
                break

    # --- Try vertical: find largest scale where rotated text fits ---
    v_scale = 0
    if scale > 0:
        if _text_height(scale) <= region_w and _text_width(text, scale) <= region_h:
            v_scale = scale
    else:
        for s in range(8, 0, -1):
            # Rotated: glyph-height becomes width, text-width becomes height
            if _text_height(s) <= region_w and _text_width(text, s) <= region_h:
                v_scale = s
                break

    # Pick whichever orientation gives us a bigger scale (prefer horizontal on tie)
    if h_scale >= v_scale and h_scale > 0:
        s = h_scale
        tw = _text_width(text, s)
        th = _text_height(s)
        tx = region_x + max(0, (region_w - tw) // 2)
        if anchor == "top":
            ty = region_y
        elif anchor == "bottom":
            ty = region_y + region_h - th
        else:
            ty = region_y + max(0, (region_h - th) // 2)
        _draw_text(surf, text, tx, ty, color, s)
    elif v_scale > 0:
        s = v_scale
        vert_w = _text_height(s)
        vert_h = _text_width(text, s)
        tx = region_x + max(0, (region_w - vert_w) // 2)
        if anchor == "top":
            ty = region_y
        elif anchor == "bottom":
            ty = region_y + region_h - vert_h
        else:
            ty = region_y + max(0, (region_h - vert_h) // 2)
        _draw_text_vertical(surf, text, tx, ty, color, s)
    else:
        # Nothing fits at scale 1 — just draw horizontal clipped at scale 1
        _draw_text(surf, text, region_x, region_y, color, 1)


# ── Prism face generator ────────────────────────────────────────

def _generate_prism_face(
    edef: EntityDef,
    face_name: str,
    compass_name: str,
    w_px: int,
    h_px: int,
) -> pygame.Surface:
    """Create a labelled placeholder texture for one prism face."""
    base = FACE_COLORS.get(face_name, (140, 140, 140))
    surf = pygame.Surface((w_px, h_px), pygame.SRCALPHA)

    # Gradient fill
    for y in range(h_px):
        t = y / max(h_px - 1, 1)
        r = int(base[0] * (1 - 0.3 * t))
        g = int(base[1] * (1 - 0.3 * t))
        b = int(base[2] * (1 - 0.3 * t))
        pygame.draw.line(surf, (r, g, b), (0, y), (w_px - 1, y))

    # Border
    border_col = tuple(max(0, c - 40) for c in base)
    pygame.draw.rect(surf, border_col, (0, 0, w_px, h_px), 2)

    # Label scale: auto-fit
    margin = 2

    # Entity name (top region — upper third)
    name_region_h = h_px // 3
    _auto_text(surf, edef.id.upper(),
               margin, margin, w_px - 2 * margin, name_region_h,
               (255, 255, 255), anchor="top")

    # Face label (middle)
    face_region_y = name_region_h
    face_region_h = h_px // 3
    _auto_text(surf, face_name.upper(),
               margin, face_region_y, w_px - 2 * margin, face_region_h,
               (200, 200, 200), anchor="center")

    # Dimension info (bottom region)
    dim_label = f"{w_px}x{h_px}"
    dim_region_y = h_px * 2 // 3
    dim_region_h = h_px - dim_region_y - margin
    _auto_text(surf, dim_label,
               margin, dim_region_y, w_px - 2 * margin, dim_region_h,
               (180, 180, 180), anchor="bottom")

    return surf


def generate_prism_textures(
    edef: EntityDef,
    out_dir: Path,
    force: bool = False,
) -> list[Path]:
    """Generate a prism net texture (box unfold) + TOML sidecar.

    Lays out all faces in a cross pattern::

                  ┌──top──┐
        ┌──left──┼─front──┼─right─┬──back──┐
        └────────┼────────┼───────┴────────┘
                  └─(bot)──┘

    The atlas loader extracts individual face textures from this
    single image at runtime — no individual face PNGs are created.
    """
    ref_dim = max(edef.width, edef.depth, edef.height, 0.01)
    base_px = 256

    out_dir.mkdir(parents=True, exist_ok=True)
    net_path = out_dir / f"{edef.id}_net.png"
    toml_path = out_dir / f"{edef.id}_net.toml"
    created: list[Path] = []

    tex_map = edef.texture_map()
    east_key = tex_map.get("east", "")
    west_key = tex_map.get("west", "")
    use_side = east_key == west_key
    has_bottom = bool(tex_map.get("bottom"))

    # Compute face pixel dimensions (consistent pixel density)
    front_w, front_h = EntityDef.face_tex_size(
        edef.width, edef.height, base_px, ref_dim=ref_dim)
    side_w, side_h = EntityDef.face_tex_size(
        edef.depth, edef.height, base_px, ref_dim=ref_dim)
    top_w, top_h = EntityDef.face_tex_size(
        edef.width, edef.depth, base_px, ref_dim=ref_dim)

    # Cross layout positions
    net_w = side_w + front_w + side_w + front_w
    net_h = top_h + front_h + (top_h if has_bottom else 0)

    rects: dict[str, tuple[int, int, int, int]] = {
        "top":   (side_w, 0, top_w, top_h),
        "left":  (0, top_h, side_w, side_h),
        "front": (side_w, top_h, front_w, front_h),
        "right": (side_w + front_w, top_h, side_w, side_h),
        "back":  (side_w + front_w + side_w, top_h, front_w, front_h),
    }
    if has_bottom:
        rects["bottom"] = (side_w, top_h + front_h, top_w, top_h)

    _NET_COMPASS = {
        "front": "north", "back": "south", "left": "west",
        "right": "east", "top": "top", "bottom": "bottom",
    }

    # ── Generate net PNG ──────────────────────────────
    if net_path.exists() and not force:
        print(f"  SKIP {net_path.relative_to(PROJECT_ROOT)} (exists)")
    else:
        net = pygame.Surface((net_w, net_h), pygame.SRCALPHA)
        net.fill((0, 0, 0, 0))

        for face_name, (fx, fy, fw, fh) in rects.items():
            if use_side and face_name in ("left", "right"):
                label = "side"
            else:
                label = face_name
            compass = _NET_COMPASS[face_name]
            face_surf = _generate_prism_face(edef, label, compass, fw, fh)
            net.blit(face_surf, (fx, fy))

        pygame.image.save(net, str(net_path))
        created.append(net_path)
        print(f"  WROTE {net_path.relative_to(PROJECT_ROOT)} "
              f"({net_w}×{net_h} cross net)")

    # ── Generate TOML sidecar ─────────────────────────
    if toml_path.exists() and not force:
        print(f"  SKIP {toml_path.relative_to(PROJECT_ROOT)} (exists)")
    else:
        lines = [
            f"# {edef.id}_net.toml — Net layout for {edef.id}_net.png",
            f"#",
            f"# Describes how the engine extracts face textures from the",
            f"# box-unfold (cross pattern) image.",
            f"#",
            f"#           ┌──top──┐",
            f"#  ┌──left──┼─front──┼─right─┬──back──┐",
            f"#  └────────┼────────┼───────┴────────┘",
        ]
        if has_bottom:
            lines.append(f"#           └─(bot)──┘")
        lines += [
            f"#",
            f"# Each [faces.X] section gives the pixel rectangle for",
            f"# that face within the image.  x,y = top-left corner.",
            "",
        ]

        # Map texture key suffixes → rects.
        face_keys: dict[str, str] = {}
        if use_side:
            face_keys = {
                "front": "front", "back": "back",
                "side": "left", "top": "top",
            }
        else:
            face_keys = {
                "front": "front", "back": "back",
                "left": "left", "right": "right", "top": "top",
            }
        if has_bottom:
            face_keys["bottom"] = "bottom"

        for suffix, rect_name in face_keys.items():
            x, y, w, h = rects[rect_name]
            lines += [
                f"[faces.{suffix}]",
                f"x = {x}",
                f"y = {y}",
                f"w = {w}",
                f"h = {h}",
                "",
            ]

        lines += [
            f"[meta]",
            f'entity_def_hash = "{_visual_fingerprint(edef)}"',
            "",
        ]

        toml_path.write_text("\n".join(lines))
        created.append(toml_path)
        print(f"  WROTE {toml_path.relative_to(PROJECT_ROOT)}")

    return created


# ── Billboard sheet generator ────────────────────────────────────

def _generate_billboard_frame(
    edef: EntityDef,
    state: str,
    state_idx: int,
    facing: int,
    n_facings: int,
    frame: int,
    cell_w: int,
    cell_h: int,
) -> pygame.Surface:
    """Create one cell of a billboard sprite sheet template.

    Layout:
    ┌─────────────────────┐
    │ STATE          frame │  ← header line
    │                      │
    │   (checkerboard      │  ← drawable area
    │    fill showing      │
    │    allocated space)  │
    │                      │
    │ FACING               │  ← footer line
    └─────────────────────┘
    """
    # Colour: unique hue per state, brightness varies by facing
    base = STATE_HUES[state_idx % len(STATE_HUES)]
    bright = 0.85 - 0.25 * (facing / max(n_facings - 1, 1))
    fill_a = tuple(int(c * bright) for c in base)
    fill_b = tuple(int(c * bright * 0.75) for c in base)  # darker checker

    surf = pygame.Surface((cell_w, cell_h), pygame.SRCALPHA)

    # ── Checkerboard fill ── shows allocated space clearly
    check = max(4, cell_w // 8)  # checker square size
    for cy in range(cell_h):
        for cx in range(cell_w):
            if ((cx // check) + (cy // check)) % 2 == 0:
                surf.set_at((cx, cy), (*fill_a, 255))
            else:
                surf.set_at((cx, cy), (*fill_b, 255))

    # ── 1px border ── makes cell bounds obvious
    border_col = (255, 255, 255, 255)
    pygame.draw.rect(surf, border_col, (0, 0, cell_w, cell_h), 1)

    # ── Corner markers ── small 3px L-shapes in bright white at each corner
    mark = min(6, cell_w // 4, cell_h // 4)
    for dx in range(mark):
        surf.set_at((1 + dx, 1), border_col)
        surf.set_at((1, 1 + dx), border_col)
        surf.set_at((cell_w - 2 - dx, 1), border_col)
        surf.set_at((cell_w - 2, 1 + dx), border_col)
        surf.set_at((1 + dx, cell_h - 2), border_col)
        surf.set_at((1, cell_h - 2 - dx), border_col)
        surf.set_at((cell_w - 2 - dx, cell_h - 2), border_col)
        surf.set_at((cell_w - 2, cell_h - 2 - dx), border_col)

    # ── Labels (all horizontal, scale 1, 5×7 font) ──
    txt_bg = (0, 0, 0, 180)  # dark background behind text for readability
    lh = 9  # line height (7 glyph + 2 pad)

    # Header: state name (top-left) + frame number (top-right)
    state_txt = state.upper()
    sw_px = _text_width(state_txt, 1)
    # Background bar behind header text
    pygame.draw.rect(surf, txt_bg, (1, 1, cell_w - 2, lh))
    _draw_text(surf, state_txt, 3, 2, (255, 255, 100))

    frame_txt = str(frame)
    fw_px = _text_width(frame_txt, 1)
    _draw_text(surf, frame_txt, cell_w - fw_px - 3, 2, (200, 200, 200))

    # Footer: facing label (bottom-left)
    if n_facings > 1:
        facing_txt = FACING_LABELS_8[facing] if n_facings == 8 else str(facing)
    else:
        facing_txt = ""

    if facing_txt:
        pygame.draw.rect(surf, txt_bg, (1, cell_h - lh - 1, cell_w - 2, lh))
        _draw_text(surf, facing_txt, 3, cell_h - lh, (180, 220, 255))

    return surf


def generate_billboard_textures(
    edef: EntityDef,
    out_dir: Path,
    n_facings: int = 0,
    frames_per_state: dict[str, int] | None = None,
    cell_w: int = 32,
    cell_h: int = 128,
    force: bool = False,
) -> list[Path]:
    """Generate a billboard sprite sheet + TOML sidecar.

    Default cell size is 32×128 (1:4 aspect ratio).  Override with
    *cell_w* / *cell_h* for wider or shorter sprites.

    *frames_per_state* maps state name → number of animation frames.
    States not listed default to 1 frame.  Each frame occupies its
    own row in the sheet.

    n_facings=0 means non-directional (1 facing).
    Returns list of created file paths.
    """
    if n_facings <= 0:
        n_facings = 1
    states = list(edef.states)
    if not states:
        states = ["default"]
    fps = frames_per_state or {}

    # Build ordered list: (state, n_frames) — total rows = sum of all frames.
    state_frames: list[tuple[str, int]] = [
        (s, max(fps.get(s, 1), 1)) for s in states
    ]
    total_rows = sum(nf for _, nf in state_frames)

    # Grid layout: columns = facings, rows = total animation frames.
    sheet_w = n_facings * cell_w
    sheet_h = total_rows * cell_h

    out_dir.mkdir(parents=True, exist_ok=True)
    sheet_path = out_dir / f"{edef.id}_sheet.png"
    toml_path = out_dir / f"{edef.id}_sheet.toml"

    created: list[Path] = []

    if sheet_path.exists() and not force:
        print(f"  SKIP {sheet_path.relative_to(PROJECT_ROOT)} (exists)")
    else:
        sheet = pygame.Surface((sheet_w, sheet_h), pygame.SRCALPHA)
        sheet.fill((0, 0, 0, 0))

        cur_row = 0
        for si, (state, nf) in enumerate(state_frames):
            for frame_idx in range(nf):
                for fi in range(n_facings):
                    cell = _generate_billboard_frame(
                        edef, state, si, fi, n_facings,
                        frame_idx, cell_w, cell_h)
                    sheet.blit(cell, (fi * cell_w, cur_row * cell_h))
                cur_row += 1

        pygame.image.save(sheet, str(sheet_path))
        created.append(sheet_path)
        state_summary = ", ".join(
            f"{s}({nf})" for s, nf in state_frames)
        print(f"  WROTE {sheet_path.relative_to(PROJECT_ROOT)} "
              f"({sheet_w}×{sheet_h}, {n_facings} cols × {total_rows} rows  "
              f"[{state_summary}])")

    if toml_path.exists() and not force:
        print(f"  SKIP {toml_path.relative_to(PROJECT_ROOT)} (exists)")
    else:
        lines = [
            f"# {edef.id}_sheet.toml — Sprite sheet layout for {edef.id}_sheet.png",
            f"#",
            f"# Describes how the engine extracts cells from the grid.",
            f"# Each cell fills one row × all facing columns.",
            f"# Multi-frame states occupy consecutive rows.",
            f"#",
            f"#   Columns (left to right)  = facing directions",
            f"#   Rows    (top to bottom)  = animation frames, grouped by state",
            f"#   Cell size                = frame_width × frame_height pixels",
            "",
            f"[grid]",
            f"frame_width  = {cell_w}",
            f"frame_height = {cell_h}",
            "",
        ]
        # Columns array
        if n_facings <= 8:
            col_items = ", ".join(f'"{f}"' for f in FACING_LABELS_8[:n_facings])
        else:
            col_items = ", ".join(str(i) for i in range(n_facings))
        lines.append(f"columns = [{col_items}]")
        lines.append("")

        # Per-state sections with explicit row offset + frame count
        cur_row = 0
        for state, nf in state_frames:
            lines.append(f"[states.{state}]")
            lines.append(f"row    = {cur_row}")
            lines.append(f"frames = {nf}")
            lines.append("")
            cur_row += nf

        lines += [
            f"[meta]",
            f'entity_def_hash = "{_visual_fingerprint(edef)}"',
            "",
        ]

        toml_path.write_text("\n".join(lines))
        created.append(toml_path)
        print(f"  WROTE {toml_path.relative_to(PROJECT_ROOT)}")

    return created


# ── Change detection ─────────────────────────────────────────────

def _check_def_changed(edef: EntityDef, out_dir: Path) -> None:
    """Print a warning if the entity def has changed since the sheet was generated."""
    toml_path = out_dir / f"{edef.id}_sheet.toml"
    stored = _read_toml_hash(toml_path)
    if not stored:
        return  # no existing TOML — nothing to compare
    current = _visual_fingerprint(edef)
    if stored != current:
        print(f"  ⚠ WARNING: entity def has changed since sheet was generated!")
        print(f"    stored hash:  {stored}")
        print(f"    current hash: {current}")
        print(f"    Run with --force to regenerate the template sheet.")


# ── Main ─────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Entity texture pipeline: generate template sprite sheets.",
        epilog=(
            "Default behaviour: generate template sprite sheet if missing.\n"
            "The engine loads cells directly from the sheet at runtime —\n"
            "no individual PNGs are created.\n\n"
            "Typical artist workflow:\n"
            "  1. python gen_entity_textures.py goblin      # generate template\n"
            "  2. … paint over the sheet …\n"
            "  3. Run the game — engine reads cells from the sheet\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "entities", nargs="*",
        help="Entity type IDs to process (default: all)")
    parser.add_argument(
        "--force", action="store_true",
        help="Overwrite existing template sheet")
    parser.add_argument(
        "--facings", type=int, default=0,
        help="Number of billboard facings (0=auto from entity def, default 0)")
    parser.add_argument(
        "--frames", type=str, default="",
        help="Frames per state: 'walk=4,idle=2' or just '4' for all states")
    parser.add_argument(
        '--cell-width', type=int, default=0,
        help="Billboard cell width in pixels (0=use entity def, default 0)")
    parser.add_argument(
        '--cell-height', type=int, default=0,
        help="Billboard cell height in pixels (0=use entity def, default 0)")
    parser.add_argument(
        "--list", action="store_true", dest="list_only",
        help="List entity types and exit")
    args = parser.parse_args()

    registry = entity_registry()

    if args.list_only:
        fmt = "  {id:25s}  {rt:10s}  {cat:12s}  dir={d:<5}  states={s}"
        print(fmt.format(id="ID", rt="RENDER", cat="CATEGORY", d="DIR", s="STATES"))
        print("  " + "─" * 80)
        for eid, edef in sorted(registry.items()):
            print(fmt.format(
                id=eid, rt=edef.render_type, cat=edef.category,
                d=str(edef.directional), s=", ".join(edef.states)))
        return

    targets = args.entities if args.entities else list(registry.keys())
    total_created = 0

    for eid in targets:
        edef = registry.get(eid)
        if edef is None:
            print(f"WARNING: '{eid}' not found in entity registry — skipping")
            continue

        print(f"\n── {edef.display_name} ({eid}) ──  render_type={edef.render_type}")

        # Skip editor-only / system entities that players never see
        if eid in ("spawn_point", "trigger_zone", "loot_socket", "ground_item"):
            print("  SKIP (editor-only marker entity)")
            continue

        if edef.render_type == "prism":
            out_dir = PRISM_TEX_DIR
            paths = generate_prism_textures(edef, out_dir, force=args.force)
            total_created += len(paths)

        elif edef.render_type in ("billboard", "8way"):
            out_dir = BILLBOARD_TEX_DIR
            # Derive facings: CLI override > entity def > default
            n_f = args.facings if args.facings > 0 else (
                8 if edef.directional else 1)

            # Change detection
            _check_def_changed(edef, out_dir)

            # Template generation
            # Parse per-state frame counts from CLI
            fps: dict[str, int] = {}
            if args.frames:
                for part in args.frames.split(","):
                    part = part.strip()
                    if "=" in part:
                        k, v = part.split("=", 1)
                        fps[k.strip()] = int(v.strip())
                    else:
                        # bare number → applies to every state
                        default_nf = int(part)
                        for s in (edef.states or ("default",)):
                            fps.setdefault(s, default_nf)

            paths = generate_billboard_textures(
                edef, out_dir, n_facings=n_f,
                frames_per_state=fps or None,
                cell_w=args.cell_width or edef.frame_width,
                cell_h=args.cell_height or edef.frame_height,
                force=args.force)
            total_created += len(paths)

        else:
            print(f"  SKIP (unknown render_type: {edef.render_type})")

    print(f"\nDone — {total_created} files created.")


if __name__ == "__main__":
    main()