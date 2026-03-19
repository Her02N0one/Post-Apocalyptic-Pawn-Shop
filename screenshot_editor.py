#!/usr/bin/env python3
"""screenshot_editor.py — Capture screenshots of every editor screen.

Usage:
    python screenshot_editor.py [zone_name]

Saves PNGs to screenshots/ with descriptive names.
Default zone: pawn_shop (or first available zone).
"""
from __future__ import annotations

import math
import os
import sys
import time
from pathlib import Path

import pygame
import OpenGL.GL as gl


def capture_gl_screenshot(win_w: int, win_h: int) -> pygame.Surface:
    """Read the current GL framebuffer into a pygame Surface."""
    data = gl.glReadPixels(0, 0, win_w, win_h, gl.GL_RGB, gl.GL_UNSIGNED_BYTE)
    surf = pygame.image.fromstring(bytes(data), (win_w, win_h), "RGB")
    # glReadPixels returns bottom-up; flip vertically
    return pygame.transform.flip(surf, False, True)


def main() -> None:
    zone_arg = sys.argv[1] if len(sys.argv) > 1 else ""

    out_dir = Path(__file__).resolve().parent / "screenshots"
    out_dir.mkdir(exist_ok=True)

    # ── Boot the editor ──────────────────────────────────────────
    from editor.app import ZoneEditorApp
    from editor.view_3d.constants import (
        MODE_ARCH, MODE_SURF, MODE_PROPS, MODE_LOGIC, MODES,
    )
    from core.zones import list_zones

    # Pick a zone with content
    all_zones = list_zones()
    if zone_arg and zone_arg in all_zones:
        target_zone = zone_arg
    elif "pawn_shop" in all_zones:
        target_zone = "pawn_shop"
    elif "showcase" in all_zones:
        target_zone = "showcase"
    elif all_zones:
        target_zone = all_zones[0]
    else:
        print("No zones found. Create one first.")
        sys.exit(1)

    print(f"Using zone: {target_zone}")
    app = ZoneEditorApp(target_zone)

    win_w, win_h = app.win_size

    def pump() -> None:
        """Drain pygame events so the window doesn't freeze."""
        for _ in pygame.event.get():
            pass

    # Helper: render one frame and save
    def snap(name: str, description: str = "") -> None:
        pump()
        app._vp_dirty = True
        app._render_frame()
        pygame.display.flip()
        pump()
        surf = capture_gl_screenshot(win_w, win_h)
        path = out_dir / f"{name}.png"
        pygame.image.save(surf, str(path))
        label = f"  {description}" if description else ""
        print(f"  Saved: {path.name}{label}")

    # Helper: position camera
    def set_camera(x: float, y: float, z: float,
                   yaw: float = 0.0, pitch: float = -0.15) -> None:
        ed = app.editor_3d
        if ed is None:
            return
        ed.cam_x = x
        ed.cam_y = y
        ed.cam_z = z
        ed.yaw = yaw
        ed.pitch = pitch

    # Pump a few frames to let everything settle
    for _ in range(5):
        pump()
        app._vp_dirty = True
        app._render_frame()
        pygame.display.flip()

    # ── Position camera at a good viewpoint ──────────────────────
    if app.zone:
        cx = app.zone.width / 2.0
        cz = app.zone.height / 2.0
        set_camera(cx, 2.5, cz, yaw=math.pi * 0.25, pitch=-0.2)

    # ── 1. 3D view — each tool mode ─────────────────────────────
    print("\n3D Editor views:")
    app.view_mode = "3d"

    mode_labels = {
        MODE_ARCH:  ("3d_arch",    "3D view — Architecture mode"),
        MODE_SURF:  ("3d_surface", "3D view — Surface mode"),
        MODE_PROPS: ("3d_props",   "3D view — Props mode"),
        MODE_LOGIC: ("3d_logic",   "3D view — Logic mode"),
    }

    for mode in MODES:
        app.editor_3d.mode = mode
        fname, desc = mode_labels[mode]
        snap(fname, desc)

    # ── 2. 2.5D raycaster preview ────────────────────────────────
    print("\n2.5D Raycaster preview:")
    app.view_mode = "2d"
    # Sync camera to raycaster
    if app.editor_3d:
        app.px = app.editor_3d.cam_x
        app.py = app.editor_3d.cam_z
        app.angle = app.editor_3d.yaw + math.pi * 0.5
        app.pitch = max(-0.6, min(0.6, app.editor_3d.pitch))
        if app.renderer:
            app.cam_h = app.renderer.floor_height_at(app.px, app.py) + 0.5
    snap("raycaster_preview", "2.5D raycaster preview")

    # ── 3. Back to 3D, try different camera angles ───────────────
    print("\nAdditional angles:")
    app.view_mode = "3d"
    app.editor_3d.mode = MODE_ARCH

    if app.zone:
        # High overview looking down
        set_camera(cx, 6.0, cz, yaw=0.0, pitch=-0.7)
        snap("3d_overview_high", "3D view — high overview")

        # Close-up ground level
        set_camera(cx, 1.0, cz, yaw=math.pi * 0.75, pitch=0.0)
        snap("3d_ground_level", "3D view — ground level")

        # Corner view
        w, h = app.zone.width, app.zone.height
        set_camera(1.0, 3.0, 1.0,
                   yaw=math.pi * 0.25, pitch=-0.3)
        snap("3d_corner_view", "3D view — corner overview")

    # ── 4. Different zones (if available) ────────────────────────
    interesting_zones = ["pawn_shop", "house_interior", "showcase",
                         "crossroads", "outskirts"]
    extra_zones = [z for z in interesting_zones
                   if z in all_zones and z != target_zone]

    if extra_zones:
        print("\nOther zones:")
        for zname in extra_zones[:3]:  # cap at 3 extras
            app._load_zone(zname)
            if app.zone:
                cx2 = app.zone.width / 2.0
                cz2 = app.zone.height / 2.0
                set_camera(cx2, 3.0, cz2,
                           yaw=math.pi * 0.25, pitch=-0.25)
                app.editor_3d.mode = MODE_ARCH
                app.view_mode = "3d"
                snap(f"zone_{zname}_3d", f"Zone: {zname} — 3D view")

                # Raycaster for this zone too
                app.view_mode = "2d"
                app.px = app.editor_3d.cam_x
                app.py = app.editor_3d.cam_z
                app.angle = app.editor_3d.yaw + math.pi * 0.5
                app.pitch = max(-0.6, min(0.6, app.editor_3d.pitch))
                if app.renderer:
                    app.cam_h = (app.renderer.floor_height_at(app.px, app.py)
                                 + 0.5)
                snap(f"zone_{zname}_raycaster",
                     f"Zone: {zname} — raycaster preview")

    # ── Done ─────────────────────────────────────────────────────
    count = len(list(out_dir.glob("*.png")))
    print(f"\nDone! {count} screenshots saved to {out_dir}/")

    app.imgui_impl.shutdown()
    pygame.quit()


if __name__ == "__main__":
    main()
