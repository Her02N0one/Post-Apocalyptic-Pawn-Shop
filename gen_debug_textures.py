#!/usr/bin/env python3
"""gen_debug_textures.py — Generate labelled debug/dummy textures.

Creates colour-coded placeholder images for:
  • Billboard sprite sheets  (frames × facings × states)
  • Skybox panoramas         (compass labels, zenith/horizon gradient)
  • Single tile textures     (labelled solid-colour squares)

Run from the project root:
    python gen_debug_textures.py --help

Depends only on pygame (already in requirements).

Sprite Sheet Format
───────────────────
A sprite sheet PNG is a grid of *cells*.  Each cell is `frame_w × frame_h`
pixels (default 64×64, matching the engine's TEX_SIZE).

  Columns = animation frames  (left → right, frame 0 … N-1)
  Rows    = state × facing     (top → bottom)

Row ordering (for `facings` = 8, `states` = ["default", "aggro", "dead"]):
  Row  0 : state "default", facing 0 (south)
  Row  1 : state "default", facing 1 (SW)
  ...
  Row  7 : state "default", facing 7 (SE)
  Row  8 : state "aggro",   facing 0
  ...
  Row 15 : state "aggro",   facing 7
  Row 16 : state "dead",    facing 0
  ...
  Row 23 : state "dead",    facing 7

For non-directional entities (`facings` = 1):
  Row 0 : state "default", frame 0 … N-1
  Row 1 : state "aggro",   frame 0 … N-1
  Row 2 : state "dead",    frame 0 … N-1

Total image size:
  width  = max(frames_per_state) × frame_w
  height = len(states) × facings × frame_h

Unused cells (state has fewer frames than max) are fully transparent.

A sidecar TOML file with the same stem sits beside the PNG:
  assets/textures/billboards/guard_npc.toml

Skybox Format
─────────────
A single panoramic image.  The C renderer maps it cylindrically:
  • U = horizontal angle (left edge = 0°, wraps 360° at right edge).
    Left-to-right corresponds to the compass sweep S → W → N → E → S.
  • V = vertical (top row = zenith, bottom row = horizon).
Any resolution is accepted.  Wider images give more horizontal detail.
Recommended aspect: 4:1 (e.g., 1024×256, 2048×512).

Saved to: assets/textures/skyboxes/<name>.png
Set on a zone via `zone.skybox = "<name>.png"`.
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from pathlib import Path

# Bootstrap pygame (headless — no display needed for Surface ops)
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
import pygame  # noqa: E402

pygame.init()
# Tiny hidden display so convert() doesn't crash if called
try:
    pygame.display.set_mode((1, 1), pygame.NOFRAME)
except pygame.error:
    pass

# ── Project paths ────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent
TILE_TEX_DIR = PROJECT_ROOT / "assets" / "textures" / "tiles"
BILLBOARDS_DIR = PROJECT_ROOT / "assets" / "textures" / "billboards"
SKYBOXES_DIR = PROJECT_ROOT / "assets" / "textures" / "skyboxes"

# ── Facing labels (8-way compass, index 0 = south) ──────────────
FACING_LABELS_8 = ["S", "SW", "W", "NW", "N", "NE", "E", "SE"]

# ── Colour palettes (per-state hue, saturated) ──────────────────
STATE_BASE_HUES = [
    (80, 180, 80),    # green
    (200, 80, 80),    # red
    (80, 80, 200),    # blue
    (200, 180, 60),   # yellow
    (180, 80, 200),   # purple
    (80, 200, 200),   # cyan
    (200, 130, 60),   # orange
    (160, 160, 160),  # grey
]


# ═════════════════════════════════════════════════════════════════════
#  Tiny text renderer (no font dependency — pixel glyphs)
# ═════════════════════════════════════════════════════════════════════

# 5×7 pixel font for uppercase + digits.  Each glyph is 5 columns of
# 7-bit bitmasks (LSB = top row).
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
    "3": (0x22, 0x41, 0x49, 0x49, 0x36),
    "4": (0x18, 0x14, 0x12, 0x7F, 0x10),
    "5": (0x27, 0x45, 0x45, 0x45, 0x39),
    "6": (0x3C, 0x4A, 0x49, 0x49, 0x30),
    "7": (0x01, 0x71, 0x09, 0x05, 0x03),
    "8": (0x36, 0x49, 0x49, 0x49, 0x36),
    "9": (0x06, 0x49, 0x49, 0x29, 0x1E),
    " ": (0x00, 0x00, 0x00, 0x00, 0x00),
    ":": (0x00, 0x36, 0x36, 0x00, 0x00),
    "/": (0x20, 0x10, 0x08, 0x04, 0x02),
    "-": (0x08, 0x08, 0x08, 0x08, 0x08),
    ".": (0x00, 0x60, 0x60, 0x00, 0x00),
    "_": (0x40, 0x40, 0x40, 0x40, 0x40),
    "#": (0x14, 0x7F, 0x14, 0x7F, 0x14),
    "(": (0x00, 0x1C, 0x22, 0x41, 0x00),
    ")": (0x00, 0x41, 0x22, 0x1C, 0x00),
    "X": (0x63, 0x14, 0x08, 0x14, 0x63),
}


def _draw_text(surf: pygame.Surface, x: int, y: int, text: str,
               color: tuple[int, int, int], scale: int = 1) -> int:
    """Draw text using the built-in 5×7 pixel font.  Returns width drawn."""
    ox = x
    for ch in text.upper():
        glyph = _FONT_5x7.get(ch)
        if glyph is None:
            ox += 4 * scale  # unknown char → skip
            continue
        for col_idx, col_bits in enumerate(glyph):
            for row in range(7):
                if col_bits & (1 << row):
                    px = ox + col_idx * scale
                    py = y + row * scale
                    for dy in range(scale):
                        for dx in range(scale):
                            sx, sy = px + dx, py + dy
                            if 0 <= sx < surf.get_width() and 0 <= sy < surf.get_height():
                                surf.set_at((sx, sy), color)
        ox += (5 + 1) * scale  # glyph width + 1px gap
    return ox - x


def _text_width(text: str, scale: int = 1) -> int:
    """Calculate pixel width of text *without* drawing it."""
    n = len(text)
    if n == 0:
        return 0
    # Each glyph is 5 cols wide, plus 1-col gap between glyphs.
    return (n * 5 + (n - 1)) * scale


def _text_height(scale: int = 1) -> int:
    """Pixel height of one line of text at *scale*."""
    return 7 * scale


def _fit_text(text: str, max_w: int, max_h: int,
              min_scale: int = 1, max_scale: int = 16
              ) -> tuple[str, int]:
    """Choose the largest scale that fits *text* inside *max_w* × *max_h*.

    Returns ``(possibly_truncated_text, scale)``.
    If even ``min_scale`` doesn't fit, the text is truncated to fit.
    """
    best_scale = min_scale
    for s in range(max_scale, min_scale - 1, -1):
        tw = _text_width(text, s)
        th = _text_height(s)
        if tw <= max_w and th <= max_h:
            best_scale = s
            break
    else:
        best_scale = min_scale
    # Truncate if still too wide at chosen scale
    glyph_w = 6 * best_scale  # 5 col + 1 gap
    max_chars = max(1, max_w // glyph_w)
    return text[:max_chars], best_scale


def _draw_text_centered(surf: pygame.Surface, cx: int, cy: int, text: str,
                        color: tuple[int, int, int], scale: int = 1) -> None:
    """Draw text centred at (cx, cy), clamped to surface bounds."""
    tw = _text_width(text, scale)
    th = _text_height(scale)
    x = max(0, min(cx - tw // 2, surf.get_width() - tw))
    y = max(0, min(cy - th // 2, surf.get_height() - th))
    _draw_text(surf, x, y, text, color, scale)


def _wrap_words(text: str, max_w: int, scale: int) -> list[str]:
    """Split *text* on ``_`` / `` `` boundaries into lines that fit *max_w*."""
    import re
    tokens = re.split(r'[_ ]', text)
    lines: list[str] = []
    cur = ""
    for tok in tokens:
        candidate = f"{cur}_{tok}" if cur else tok
        if _text_width(candidate, scale) <= max_w:
            cur = candidate
        else:
            if cur:
                lines.append(cur)
            cur = tok
    if cur:
        lines.append(cur)
    return lines or [text]


def _fit_text_block(text: str, max_w: int, max_h: int,
                    min_scale: int = 1, max_scale: int = 16,
                    line_gap: int = 2,
                    ) -> tuple[list[str], int]:
    """Word-wrap *text* on ``_`` boundaries, picking the largest scale that fits.

    Returns ``(lines, scale)``.  Lines that are still too wide at the
    chosen scale are truncated.
    """
    for s in range(max_scale, min_scale - 1, -1):
        lines = _wrap_words(text, max_w, s)
        lh = _text_height(s)
        block_h = len(lines) * lh + max(0, len(lines) - 1) * line_gap
        if block_h <= max_h and all(_text_width(ln, s) <= max_w for ln in lines):
            return lines, s
    # Fallback: scale 1, wrap, then truncate any overlong lines
    s = min_scale
    lines = _wrap_words(text, max_w, s)
    glyph_w = 6 * s
    max_chars = max(1, max_w // glyph_w)
    lines = [ln[:max_chars] for ln in lines]
    # Drop lines that won't fit vertically
    lh = _text_height(s)
    max_lines = max(1, (max_h + line_gap) // (lh + line_gap))
    return lines[:max_lines], s


def _draw_text_block_centered(surf: pygame.Surface, cx: int, cy: int,
                              lines: list[str], color: tuple[int, int, int],
                              scale: int = 1, line_gap: int = 2) -> None:
    """Draw multiple lines of text centred at (cx, cy)."""
    lh = _text_height(scale)
    total_h = len(lines) * lh + max(0, len(lines) - 1) * line_gap
    start_y = cy - total_h // 2
    for i, line in enumerate(lines):
        ly = start_y + i * (lh + line_gap) + lh // 2
        _draw_text_centered(surf, cx, ly, line, color, scale)


# ═════════════════════════════════════════════════════════════════════
#  Sprite-sheet debug generator
# ═════════════════════════════════════════════════════════════════════

def gen_spritesheet(
    name: str,
    states: list[str],
    frames_per_state: list[int],
    facings: int = 8,
    frame_w: int = 64,
    frame_h: int = 64,
    frame_rate: int = 6,
    output_dir: Path | None = None,
) -> Path:
    """Generate a colour-coded debug sprite sheet + sidecar TOML.

    Each cell gets:
      • A unique background colour (hue varies by state)
      • Brightness varies by facing direction
      • A diagonal stripe pattern that shifts per frame
      • Text label: state name, facing compass, frame number

    Returns the path to the written PNG.
    """
    if output_dir is None:
        output_dir = BILLBOARDS_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    n_states = len(states)
    max_frames = max(frames_per_state) if frames_per_state else 1
    total_rows = n_states * facings
    img_w = max_frames * frame_w
    img_h = total_rows * frame_h

    sheet = pygame.Surface((img_w, img_h), pygame.SRCALPHA)
    sheet.fill((0, 0, 0, 0))  # fully transparent

    for si, state_name in enumerate(states):
        n_frames = frames_per_state[si] if si < len(frames_per_state) else 1
        base_hue = STATE_BASE_HUES[si % len(STATE_BASE_HUES)]

        for fi in range(facings):
            row = si * facings + fi
            # Brightness ramp by facing: facing 0 is brightest
            bright = 1.0 - 0.3 * (fi / max(facings - 1, 1))
            bg = (
                int(base_hue[0] * bright),
                int(base_hue[1] * bright),
                int(base_hue[2] * bright),
            )
            facing_label = FACING_LABELS_8[fi] if facings == 8 else f"F{fi}"
            if facings == 1:
                facing_label = ""

            for fr in range(n_frames):
                cx = fr * frame_w
                cy = row * frame_h
                cell = pygame.Surface((frame_w, frame_h), pygame.SRCALPHA)
                cell.fill((*bg, 255))

                # Diagonal stripe pattern (shifts per frame)
                stripe_color = (
                    min(255, bg[0] + 40),
                    min(255, bg[1] + 40),
                    min(255, bg[2] + 40),
                    255,
                )
                stripe_period = 12
                stripe_offset = fr * 4
                for py in range(frame_h):
                    for px in range(frame_w):
                        if ((px + py + stripe_offset) % stripe_period) < 3:
                            cell.set_at((px, py), stripe_color)

                # Border (1px white)
                pygame.draw.rect(cell, (255, 255, 255, 180),
                                 (0, 0, frame_w, frame_h), 1)

                # Text labels — auto-scale to fit cell
                text_col = (255, 255, 255)
                pad = max(2, frame_w // 16)
                usable_w = frame_w - pad * 2
                # State name (top-left)
                st_text, st_sc = _fit_text(state_name, usable_w // 2, frame_h // 4)
                _draw_text(cell, pad, pad, st_text, text_col, st_sc)
                # Facing (top-right area)
                if facing_label:
                    fl_text, fl_sc = _fit_text(facing_label, usable_w // 3, frame_h // 4)
                    fw_px = _text_width(fl_text, fl_sc)
                    _draw_text(cell, frame_w - fw_px - pad, pad, fl_text, text_col, fl_sc)
                # Frame number (large, centred)
                frame_str = f"F{fr}"
                fr_text, fr_sc = _fit_text(frame_str, usable_w, frame_h // 2)
                _draw_text_centered(cell, frame_w // 2, frame_h // 2,
                                    fr_text, text_col, fr_sc)
                # Row index (bottom-left, small)
                r_text, r_sc = _fit_text(f"R{row}", usable_w // 3, frame_h // 5)
                _draw_text(cell, pad, frame_h - _text_height(r_sc) - pad,
                           r_text, (200, 200, 200), r_sc)

                sheet.blit(cell, (cx, cy))

    # Save PNG
    png_path = output_dir / f"{name}.png"
    pygame.image.save(sheet, str(png_path))
    print(f"  PNG: {png_path}  ({img_w}×{img_h}, {total_rows} rows × {max_frames} cols)")

    # Save sidecar TOML
    toml_lines = [
        f'# Sprite sheet definition for "{name}"',
        f'# Generated by gen_debug_textures.py',
        f'',
        f'frame_width = {frame_w}',
        f'frame_height = {frame_h}',
        f'facings = {facings}',
        f'frame_rate = {frame_rate}    # ticks per animation frame',
        f'',
        f'# States — one section per visual state.',
        f'# "frames" is the number of animation columns for that state.',
        f'# Row range in the sheet: [state_index * facings .. (state_index+1) * facings - 1]',
        f'',
    ]
    for si, sname in enumerate(states):
        nf = frames_per_state[si] if si < len(frames_per_state) else 1
        row_start = si * facings
        row_end = row_start + facings - 1
        toml_lines.append(f'[states.{sname}]')
        toml_lines.append(f'frames = {nf}')
        toml_lines.append(f'row_start = {row_start}    # rows {row_start}..{row_end}')
        toml_lines.append(f'')

    toml_path = output_dir / f"{name}.toml"
    toml_path.write_text("\n".join(toml_lines) + "\n")
    print(f"  TOML: {toml_path}")
    return png_path


# ═════════════════════════════════════════════════════════════════════
#  Skybox debug generator
# ═════════════════════════════════════════════════════════════════════

def gen_skybox(
    name: str,
    width: int = 1024,
    height: int = 256,
    vspan_deg: float = 51.0,
    output_dir: Path | None = None,
) -> Path:
    """Generate a template skybox panorama meant to be drawn over.

    Layout (matching the C renderer's angular UV):
      • U (horizontal): 0° at left edge, wraps 360° to right edge.
        Compass: S at 0%, W at 25%, N at 50%, E at 75%.
      • V (vertical): top row = *vspan_deg*° above horizon,
        bottom row = 0° (horizon).  Default 51° — this matches the
        engine's computed sky_vspan for the editor configuration
        (640×360, 60° FOV, 54° max pitch) so the full texture is
        visible at maximum pitch.
      • Recommended aspect ratio **4:1** (e.g. 1024×256).

    The template is intentionally neutral — pale grid on light grey — so
    artists can paint directly on top of it as a guide layer.

    Features:
      • Light neutral gradient (pale grey top → slightly warm horizon)
      • Grid lines every 5° vertical / 10° horizontal
      • Compass letters at correct U positions (S, SW, W, NW, N, NE, E, SE)
      • Degree labels at 15° horizontal intervals
      • Elevation markers on the left margin (0° horizon .. vspan° top)
      • "75°" / "HORIZON" labels at top and bottom edges
    """
    if output_dir is None:
        output_dir = SKYBOXES_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    sky = pygame.Surface((width, height))

    # Neutral gradient — pale grey at top, very slightly warmer at bottom
    for y in range(height):
        t = y / max(height - 1, 1)  # 0 = top, 1 = horizon
        r = int(190 + 30 * t)
        g = int(190 + 25 * t)
        b = int(200 + 15 * t)
        pygame.draw.line(sky, (r, g, b), (0, y), (width - 1, y))

    # ── Horizontal grid lines (elevation angles) ──────────────
    grid_light = (170, 170, 180)
    grid_dark  = (140, 140, 155)
    label_fg = (80, 80, 95)
    label_fg_dim = (120, 120, 135)

    step = 5
    for elev in range(0, int(vspan_deg) + 1, step):
        # elev 0 = horizon (bottom), vspan = top
        v = 1.0 - elev / vspan_deg
        y = int(v * (height - 1))
        col = grid_dark if elev % 15 == 0 else grid_light
        pygame.draw.line(sky, col, (0, y), (width - 1, y))
        # Elevation label on left margin
        if elev % 15 == 0 and 6 < y < height - 10:
            _draw_text(sky, 2, y - 3, f"{elev}", label_fg_dim, 1)

    # ── Vertical grid lines (azimuth angles) ─────────────────
    for deg in range(0, 360, 10):
        u = deg / 360.0
        x = int(u * width) % width
        if deg % 90 == 0:
            col = (130, 130, 145)
        elif deg % 45 == 0:
            col = (145, 145, 158)
        elif deg % 30 == 0:
            col = (155, 155, 168)
        else:
            col = grid_light
        pygame.draw.line(sky, col, (x, 0), (x, height - 1))

    # ── Compass labels & degree ticks ─────────────────────────
    compass = {
        0: "S", 45: "SW", 90: "W", 135: "NW",
        180: "N", 225: "NE", 270: "E", 315: "SE",
    }
    for deg in range(0, 360, 15):
        u = deg / 360.0
        x = int(u * width) % width

        if deg in compass:
            _draw_text_centered(sky, x, height // 3, compass[deg], label_fg, 2)
            _draw_text_centered(sky, x, height // 3 + 20, f"{deg}", label_fg_dim, 1)
        else:
            _draw_text_centered(sky, x, 12, f"{deg}", label_fg_dim, 1)

    # ── Edge labels ───────────────────────────────────────────
    _draw_text_centered(sky, width // 2, 4,
                        f"{int(vspan_deg)}", label_fg_dim, 1)
    _draw_text_centered(sky, width // 2, height - 8,
                        "HORIZON", label_fg_dim, 1)

    png_path = output_dir / f"{name}.png"
    pygame.image.save(sky, str(png_path))
    print(f"  Skybox: {png_path}  ({width}x{height}, vspan={vspan_deg})")
    return png_path


# ═════════════════════════════════════════════════════════════════════
#  Single tile debug generator
# ═════════════════════════════════════════════════════════════════════

def gen_tile_texture(
    name: str,
    color: tuple[int, int, int] = (128, 128, 128),
    size: int = 128,
    output_dir: Path | None = None,
) -> Path:
    """Generate a labelled solid-colour tile texture.

    The texture has:
      • Solid background colour
      • 1px border (brighter)
      • Centred label with the texture name
      • Corner dots marking UV origin (top-left = bright)
    """
    if output_dir is None:
        output_dir = TILE_TEX_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    surf = pygame.Surface((size, size))
    surf.fill(color)

    # Border
    border_col = (
        min(255, color[0] + 60),
        min(255, color[1] + 60),
        min(255, color[2] + 60),
    )
    pygame.draw.rect(surf, border_col, (0, 0, size, size), 1)

    # UV origin dot (top-left corner, bright)
    surf.set_at((1, 1), (255, 255, 0))
    surf.set_at((2, 1), (255, 255, 0))
    surf.set_at((1, 2), (255, 255, 0))

    # Label — auto-scale to fit tile
    text_col = (255, 255, 255) if sum(color) < 384 else (0, 0, 0)
    usable = int(size * 0.9)
    label, lbl_scale = _fit_text(name, usable, usable)
    _draw_text_centered(surf, size // 2, size // 2, label, text_col, lbl_scale)

    png_path = output_dir / f"{name}.png"
    pygame.image.save(surf, str(png_path))
    print(f"  Tile: {png_path}  ({size}×{size}, {color})")
    return png_path


# ═════════════════════════════════════════════════════════════════════
#  Entity face texture generator (proportional W:H)
# ═════════════════════════════════════════════════════════════════════

def gen_entity_face_texture(
    key: str,
    width: int,
    height: int,
    color: tuple[int, int, int] = (128, 128, 128),
    label: str = "",
    output_dir: Path | None = None,
) -> Path:
    """Generate a labelled entity face texture at *width* × *height*.

    Unlike tile textures (always square), entity face textures use the
    correct aspect ratio for the physical face they represent.
    """
    if output_dir is None:
        output_dir = TILE_TEX_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    surf = pygame.Surface((width, height))
    surf.fill(color)

    # Border
    border_col = (
        min(255, color[0] + 60),
        min(255, color[1] + 60),
        min(255, color[2] + 60),
    )
    pygame.draw.rect(surf, border_col, (0, 0, width, height), 1)

    # UV origin dot (top-left)
    if width > 4 and height > 4:
        surf.set_at((1, 1), (255, 255, 0))
        surf.set_at((2, 1), (255, 255, 0))
        surf.set_at((1, 2), (255, 255, 0))

    # Label — word-wrap on '_' boundaries, auto-scale to fill
    text_col = (255, 255, 255) if sum(color) < 384 else (0, 0, 0)
    disp = label or key

    # Reserve bottom ~25% for dimension label, use top ~65% for main label
    main_h = int(height * 0.60)
    dim_h  = int(height * 0.20)
    pad_x  = max(2, int(width * 0.05))
    usable_w = width - pad_x * 2

    lines, txt_scale = _fit_text_block(disp, usable_w, main_h)
    _draw_text_block_centered(surf, width // 2,
                              int(height * 0.38),
                              lines, text_col, txt_scale)

    # Dimension label at bottom — single line, auto-scale
    dim_label = f"{width}x{height}"
    dim_label, dim_scale = _fit_text(dim_label, usable_w, dim_h)
    dim_col = (180, 180, 180) if sum(color) < 384 else (60, 60, 60)
    _draw_text_centered(surf, width // 2,
                        height - _text_height(dim_scale) // 2 - 2,
                        dim_label, dim_col, dim_scale)

    png_path = output_dir / f"{key}.png"
    pygame.image.save(surf, str(png_path))
    print(f"  Entity face: {png_path}  ({width}×{height}, {color})")
    return png_path


def gen_all_entity_textures(base_px: int = 256) -> None:
    """Generate proportional placeholder textures for all prism entities.

    Reads entity defs from ``data/entity_defs.toml``, computes correct
    W:H pixel sizes per face based on entity geometry, and writes PNGs
    with the right aspect ratios.

    *base_px* controls the resolution — the longest dimension of each
    face maps to this many pixels (default 256 = "quad resolution"
    vs a 64-px tile).
    """
    from core.entity_defs import entity_registry, EntityDef

    reg = entity_registry()
    print(f"\n── Entity face textures (base {base_px}px) ──")

    # Per-face colour tints (distinguishable at a glance)
    _FACE_COLORS: dict[str, tuple[int, int, int]] = {
        "north":  (60, 140, 200),   # front = blue
        "south":  (100, 100, 100),  # back  = grey
        "east":   (80, 120, 160),   # side  = muted blue
        "west":   (80, 120, 160),   # side  = muted blue
        "top":    (50, 50, 60),     # top   = dark
        "bottom": (40, 40, 45),     # bottom = darker
    }

    generated: set[str] = set()
    for edef in reg.values():
        if edef.render_type != "prism":
            continue
        # Single reference dimension → consistent pixel density across
        # all faces of this entity.
        ref = max(edef.width, edef.depth, edef.height, 0.01)
        for face, tex_key in edef.textures:
            if not tex_key or tex_key in generated:
                continue
            fw, fh = edef.face_dimensions(face)
            w_px, h_px = EntityDef.face_tex_size(fw, fh, base_px,
                                                  ref_dim=ref)
            color = edef.color if edef.color != (120, 120, 140) else _FACE_COLORS.get(face, (128, 128, 128))
            color = _FACE_COLORS.get(face, color)
            gen_entity_face_texture(
                tex_key, w_px, h_px,
                color=color,
            )
            generated.add(tex_key)


# ═════════════════════════════════════════════════════════════════════
#  Slice helper: explode a sprite sheet into individual atlas tiles
# ═════════════════════════════════════════════════════════════════════

def slice_spritesheet(
    png_path: Path,
    toml_path: Path | None = None,
    output_dir: Path | None = None,
) -> list[Path]:
    """Slice a sprite sheet into individual 64×64 PNGs for the tile atlas.

    For an entity named "guard", state "default", 8 facings, 4 frames:
      guard_default_s_f0.png   (row 0, col 0)
      guard_default_s_f1.png   (row 0, col 1)
      ...
      guard_default_sw_f0.png  (row 1, col 0)
      ...

    These can then be loaded by the existing TextureAtlas.get_by_key()
    system and referenced from entity rendering.

    Returns list of written file paths.
    """
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[no-redef]

    if output_dir is None:
        output_dir = TILE_TEX_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    if toml_path is None:
        toml_path = png_path.with_suffix(".toml")

    with open(toml_path, "rb") as f:
        meta = tomllib.load(f)

    fw = meta.get("frame_width", 64)
    fh = meta.get("frame_height", 64)
    facings = meta.get("facings", 1)
    states_dict = meta.get("states", {})

    sheet = pygame.image.load(str(png_path))
    entity_name = png_path.stem

    facing_names = FACING_LABELS_8[:facings] if facings == 8 else [str(i) for i in range(facings)]
    if facings == 1:
        facing_names = [""]

    written: list[Path] = []
    for state_name, state_info in states_dict.items():
        n_frames = state_info.get("frames", 1)
        row_start = state_info.get("row_start", 0)

        for fi in range(facings):
            row = row_start + fi
            facing_str = facing_names[fi].lower() if facing_names[fi] else ""

            for fr in range(n_frames):
                # Extract cell
                src_rect = pygame.Rect(fr * fw, row * fh, fw, fh)
                cell = sheet.subsurface(src_rect).copy()

                # Scale to TEX_SIZE if needed
                if cell.get_size() != (64, 64):
                    cell = pygame.transform.scale(cell, (64, 64))

                # Build name: entity_state_facing_fN
                parts = [entity_name, state_name]
                if facing_str:
                    parts.append(facing_str)
                parts.append(f"f{fr}")
                out_name = "_".join(parts)

                out_path = output_dir / f"{out_name}.png"
                pygame.image.save(cell, str(out_path))
                written.append(out_path)

    print(f"  Sliced {len(written)} tiles from {png_path.name}")
    return written


# ═════════════════════════════════════════════════════════════════════
#  CLI
# ═════════════════════════════════════════════════════════════════════

def _example_spritesheet() -> None:
    """Generate a few example sprite sheets showing the format."""
    print("\n── Example sprite sheets ──")

    # 8-way directional NPC with 3 states, varying frame counts
    gen_spritesheet(
        name="debug_npc_8way",
        states=["default", "aggro", "dead"],
        frames_per_state=[4, 2, 1],
        facings=8,
    )

    # Non-directional prop with 2 states
    gen_spritesheet(
        name="debug_prop",
        states=["default", "broken"],
        frames_per_state=[1, 1],
        facings=1,
    )

    # Animated torch (1 facing, 1 state, 4 frames)
    gen_spritesheet(
        name="debug_torch",
        states=["default"],
        frames_per_state=[4],
        facings=1,
    )


def _example_skybox() -> None:
    """Generate the template skybox panorama."""
    print("\n── Template skybox ──")
    gen_skybox("template_skybox", width=1024, height=256)


def _example_tiles() -> None:
    """Generate a set of labelled debug tile textures."""
    print("\n── Example tile textures ──")
    samples = [
        ("debug_red",    (180, 40, 40)),
        ("debug_green",  (40, 160, 40)),
        ("debug_blue",   (40, 40, 180)),
        ("debug_yellow", (200, 200, 40)),
        ("debug_purple", (160, 40, 200)),
        ("debug_grid",   (100, 100, 100)),
    ]
    for name, color in samples:
        gen_tile_texture(name, color)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate debug/dummy textures for the engine.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate all example textures (sprites, skybox, tiles)
  python gen_debug_textures.py --all

  # Generate a specific sprite sheet
  python gen_debug_textures.py sprite --name guard \\
      --states default,aggro,dead --frames 4,2,1 --facings 8

  # Generate a skybox
  python gen_debug_textures.py skybox --name sunset --width 2048 --height 512

  # Generate a tile texture
  python gen_debug_textures.py tile --name my_floor --color 120,80,60

  # Slice a sprite sheet into individual tile PNGs
  python gen_debug_textures.py slice --sheet assets/textures/billboards/guard.png

  # Generate entity face textures with correct proportions
  python gen_debug_textures.py entity --base 128
""")

    parser.add_argument("--all", action="store_true",
                        help="Generate all example debug textures")

    sub = parser.add_subparsers(dest="command")

    # ── sprite sub-command ────────────────────────────────────
    sp = sub.add_parser("sprite", help="Generate a sprite sheet")
    sp.add_argument("--name", required=True, help="Entity name (output stem)")
    sp.add_argument("--states", required=True,
                    help="Comma-separated state names (e.g., default,aggro,dead)")
    sp.add_argument("--frames", required=True,
                    help="Comma-separated frame counts per state (e.g., 4,2,1)")
    sp.add_argument("--facings", type=int, default=8, choices=[1, 8],
                    help="Number of facings (1 or 8, default: 8)")
    sp.add_argument("--size", type=int, default=64,
                    help="Cell size in pixels (default: 64)")
    sp.add_argument("--fps", type=int, default=6,
                    help="Animation ticks per frame (default: 6)")

    # ── skybox sub-command ────────────────────────────────────
    sk = sub.add_parser("skybox", help="Generate a skybox panorama")
    sk.add_argument("--name", required=True, help="Skybox name (output stem)")
    sk.add_argument("--width", type=int, default=1024, help="Image width")
    sk.add_argument("--height", type=int, default=256, help="Image height")

    # ── tile sub-command ──────────────────────────────────────
    ti = sub.add_parser("tile", help="Generate a single tile texture")
    ti.add_argument("--name", required=True, help="Texture name (output stem)")
    ti.add_argument("--color", required=True,
                    help="RGB colour as R,G,B (e.g., 120,80,60)")
    ti.add_argument("--size", type=int, default=128, help="Texture size")

    # ── slice sub-command ─────────────────────────────────────
    sl = sub.add_parser("slice",
                        help="Slice a sprite sheet into individual tile PNGs")
    sl.add_argument("--sheet", required=True, help="Path to sprite sheet PNG")
    sl.add_argument("--toml", default=None,
                    help="Path to sidecar TOML (default: same stem as PNG)")
    sl.add_argument("--out", default=None,
                    help="Output directory (default: assets/textures/tiles/)")

    # ── entity sub-command ────────────────────────────────────
    en = sub.add_parser("entity",
                        help="Generate entity face textures with correct W:H")
    en.add_argument("--base", type=int, default=256,
                    help="Base resolution (longest face dim in px, default 256)")

    args = parser.parse_args()

    if args.all:
        _example_spritesheet()
        _example_skybox()
        _example_tiles()
        gen_all_entity_textures()
        print("\nDone! All debug textures generated.")
        return

    if args.command == "sprite":
        states = [s.strip() for s in args.states.split(",")]
        frames = [int(f.strip()) for f in args.frames.split(",")]
        gen_spritesheet(
            name=args.name,
            states=states,
            frames_per_state=frames,
            facings=args.facings,
            frame_w=args.size,
            frame_h=args.size,
            frame_rate=args.fps,
        )
    elif args.command == "skybox":
        gen_skybox(name=args.name, width=args.width, height=args.height)
    elif args.command == "tile":
        parts = args.color.split(",")
        color = (int(parts[0]), int(parts[1]), int(parts[2]))
        gen_tile_texture(name=args.name, color=color, size=args.size)
    elif args.command == "slice":
        sheet_path = Path(args.sheet)
        toml_path = Path(args.toml) if args.toml else None
        out_dir = Path(args.out) if args.out else None
        slice_spritesheet(sheet_path, toml_path, out_dir)
    elif args.command == "entity":
        gen_all_entity_textures(base_px=args.base)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
