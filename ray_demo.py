#!/usr/bin/env python3
"""ray_demo.py — Standalone raycasting renderer demo.

Loads a zone and renders it using the new C-based raycaster with
textured walls, floors, and ceilings.  No editor, no game logic —
just raw rendering + camera movement.

Usage
-----
    python ray_demo.py [zone_name]

    zone_name  : Name of a zone in zones/ (default: showcase)

Controls
--------
    Movement
        W / S           Move forward / backward
        A / D           Strafe left / right
        Q / E           Turn left / right (keyboard look)
        Mouse           Look around (when captured)
        Shift           Sprint (2× speed)
        Ctrl            Slow walk (0.3× speed)

    Rendering
        I               Toggle interior / exterior (ceiling on/off)
        N               Cycle day/night (day → dusk → night → dawn)
        [ / ]           Decrease / increase FOV (zoom)
        - / =           Decrease / increase render resolution
        F               Toggle FPS cap (60 / uncapped)
        B               Toggle entity billboard rendering
        Z               Toggle depth buffer debug view

    Navigation
        Tab             Toggle 3D wireframe editor / 2.5D renderer
        Shift+Tab       Cycle to next zone
        R               Respawn at zone anchor
        G               Toggle noclip (fly through walls)

    Display
        M               Toggle minimap
        H               Toggle HUD
        F1              Toggle controls overlay
        F11             Toggle fullscreen

    General
        Escape          Release mouse / quit
        Click           Capture mouse
"""

from __future__ import annotations

import math
import sys
import time

import pygame

# ── Project imports ───────────────────────────────────────────────
from core.zones import load_zone, list_zones
from engine.textures import TextureAtlas
from engine.ray_renderer import RayRenderer
from editor.view_3d import Zone3DEditor

# ═══════════════════════════════════════════════════════════════════
#  Configuration
# ═══════════════════════════════════════════════════════════════════

WINDOW_W   = 1280         # display window width
WINDOW_H   = 720          # display window height

# Render resolution presets (label, width, height)
RES_PRESETS = [
    ("160×90",   160,  90),
    ("320×180",  320, 180),
    ("480×270",  480, 270),
    ("640×360",  640, 360),
    ("800×450",  800, 450),
    ("960×540",  960, 540),
]
DEFAULT_RES   = 3         # index into RES_PRESETS (640×360)

FOV_DEFAULT   = math.pi / 3     # 60°
FOV_MIN       = math.pi / 6     # 30°
FOV_MAX       = math.pi * 0.55  # ~100°
FOV_STEP      = math.pi / 36    # 5° per press

MOVE_SPEED    = 3.0        # tiles per second
SPRINT_MULT   = 2.0
SLOW_MULT     = 0.3
MOUSE_SENS    = 0.003      # radians per mouse pixel
KB_TURN_SPEED = 2.5        # radians per second (Q/E keys)
PLAYER_RAD    = 0.2        # collision radius

# Height / stepping
EYE_HEIGHT       = 0.5     # eye offset above floor
MAX_STEP_UP      = 0.5     # max floor rise that counts as a walkable step
MAX_STEP_DOWN    = 1.0     # max drop the player can walk off
HEAD_CLEARANCE   = 0.4     # min gap between floor and ceiling to fit
CAM_LERP_SPEED   = 8.0     # camera height lerp speed (units/sec)

# Day/night presets (label, dn factor)
DN_PRESETS = [
    ("Day",    1.0),
    ("Dusk",   0.55),
    ("Night",  0.15),
    ("Dawn",   0.70),
]

# ═══════════════════════════════════════════════════════════════════
#  Minimap
# ═══════════════════════════════════════════════════════════════════

def draw_minimap(
    surface: pygame.Surface,
    tiles: list[list[str]],
    px: float, py: float, angle: float,
    map_w: int, map_h: int,
    renderer: RayRenderer,
) -> None:
    """Draw a small 2D minimap in the top-left corner."""
    from core.tiles import TILE_COLORS, tile_def

    cell = 4
    radius = 24  # cells around player
    ox, oy = 8, 8
    cx, cy = int(px), int(py)

    mw = min(radius * 2, map_w)
    mh = min(radius * 2, map_h)
    sx = max(0, cx - radius)
    sy = max(0, cy - radius)
    ex = min(map_w, sx + mw)
    ey = min(map_h, sy + mh)

    # Background
    bg = pygame.Surface(((ex - sx) * cell, (ey - sy) * cell))
    bg.fill((10, 10, 10))

    for r in range(sy, ey):
        for c in range(sx, ex):
            tid = tiles[r][c]
            td = tile_def(tid)
            color = td.color if td else (40, 40, 40)
            pygame.draw.rect(
                bg, color,
                ((c - sx) * cell, (r - sy) * cell, cell, cell),
            )

    surface.blit(bg, (ox, oy))

    # Player dot + direction line
    ppx = ox + (px - sx) * cell
    ppy = oy + (py - sy) * cell
    pygame.draw.circle(surface, (255, 50, 50), (int(ppx), int(ppy)), 3)
    dx = math.cos(angle) * 10
    dy = math.sin(angle) * 10
    pygame.draw.line(
        surface, (255, 100, 100),
        (int(ppx), int(ppy)),
        (int(ppx + dx), int(ppy + dy)),
        2,
    )

# ═══════════════════════════════════════════════════════════════════
#  HUD
# ═══════════════════════════════════════════════════════════════════

def draw_hud(
    surface: pygame.Surface,
    font: pygame.font.Font,
    font_sm: pygame.font.Font,
    fps: float,
    render_ms: float,
    zone_name: str,
    px: float, py: float, angle: float,
    is_interior: bool,
    dn_label: str,
    fov_deg: float,
    res_label: str,
    noclip: bool,
    fps_capped: bool,
    show_controls: bool,
    player_fh: float = 0.0,
    cam_h: float = 0.5,
) -> None:
    """Draw HUD info panels."""
    sw, sh = surface.get_size()

    # ── Top-right info panel ──
    lines_r = [
        (f"FPS: {fps:.0f}  ({render_ms:.1f}ms)", (255, 255, 100)),
        (f"{zone_name}  ({px:.1f}, {py:.1f})  {math.degrees(angle) % 360:.0f}\u00b0", (200, 200, 200)),
        (f"Floor: {player_fh:.2f}  Eye: {cam_h:.2f}", (140, 220, 180)),
        (f"{'Interior' if is_interior else 'Exterior'} | {dn_label} | FOV {fov_deg:.0f}\u00b0 | {res_label}", (160, 160, 160)),
    ]
    if noclip:
        lines_r.append(("NOCLIP", (255, 100, 100)))
    if not fps_capped:
        lines_r.append(("UNCAPPED", (100, 255, 100)))

    y = 8
    for text, color in lines_r:
        surf = font.render(text, True, color)
        surface.blit(surf, (sw - surf.get_width() - 10, y))
        y += 18

    # ── Controls overlay (F1) ──
    if show_controls:
        controls = [
            "W/S = forward/back    A/D = strafe    Q/E = turn",
            "Mouse = look    Shift = sprint    Ctrl = slow",
            "I = interior    N = day/night    [ ] = FOV    - = = resolution",
            "Tab = 3D editor    Shift+Tab = next zone    R = respawn    G = noclip    F = fps cap",
            "M = minimap    H = hud    B = entities    Z = depth    F1 = controls    F11 = fullscreen",
        ]
        panel_h = len(controls) * 16 + 16
        panel_w = 460
        panel_x = (sw - panel_w) // 2
        panel_y = sh // 2 - panel_h // 2

        overlay = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        surface.blit(overlay, (panel_x, panel_y))

        for i, line in enumerate(controls):
            txt = font_sm.render(line, True, (220, 220, 200))
            surface.blit(txt, (panel_x + 12, panel_y + 8 + i * 16))

# ═══════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════

def find_spawn(zone, renderer):
    """Find a valid non-solid spawn position in the zone."""
    # Try anchor first
    px = float(zone.anchor[1])   # col → x
    py = float(zone.anchor[0])   # row → y
    if not renderer.is_solid(px, py):
        return px, py
    # Search for nearest non-solid tile
    for r in range(zone.height):
        for c in range(zone.width):
            if not renderer.is_solid(c + 0.5, r + 0.5):
                return c + 0.5, r + 0.5
    return zone.width / 2.0, zone.height / 2.0


def main() -> None:
    # ── Zone list and selection ───────────────────────────────────
    all_zones = list_zones()
    zone_name = sys.argv[1] if len(sys.argv) > 1 else "showcase"
    if zone_name not in all_zones:
        print(f"Zone '{zone_name}' not found.  Available zones:")
        for z in all_zones:
            print(f"  {z}")
        return
    zone_idx = all_zones.index(zone_name)

    # ── Pygame init ───────────────────────────────────────────────
    pygame.init()
    screen = pygame.display.set_mode(
        (WINDOW_W, WINDOW_H), pygame.RESIZABLE
    )
    pygame.display.set_caption(f"Ray Demo \u2014 {zone_name}")
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("monospace", 14)
    font_sm = pygame.font.SysFont("monospace", 12)

    # ── Load zone ─────────────────────────────────────────────────
    atlas = TextureAtlas()
    atlas.ensure_all()

    zone = load_zone(zone_name)
    res_idx = DEFAULT_RES
    _, rw, rh = RES_PRESETS[res_idx]
    fov = FOV_DEFAULT
    dn_idx = 0
    dn_label, dn = DN_PRESETS[dn_idx]

    renderer = RayRenderer(zone, atlas, sw=rw, sh=rh, fov=fov, dn=dn)

    # ── 3D editor ─────────────────────────────────────────────────
    editor_3d = Zone3DEditor(zone)
    view_mode = "2d"    # "2d" = raycaster, "3d" = wireframe editor

    # ── Camera state ──────────────────────────────────────────────
    px, py = find_spawn(zone, renderer)
    angle = math.pi * 1.5       # face north
    pitch = 0.0                  # vertical look (radians, + = up)
    PITCH_MAX = math.pi * 0.30   # ~55° up/down
    player_fh = renderer.floor_height_at(px, py)  # current floor under player
    cam_h = player_fh + EYE_HEIGHT                # smooth camera height

    show_minimap = True
    show_hud = True
    show_controls = True        # show on launch, dismiss with F1
    show_entities = True        # entity billboard rendering
    show_depth = False            # depth buffer debug overlay
    is_interior = zone.first_person
    fullscreen = False
    noclip = False
    fps_capped = True
    mouse_captured = True
    pygame.mouse.set_visible(False)
    pygame.event.set_grab(True)

    # ── Timing ────────────────────────────────────────────────────
    frame_times: list[float] = []
    render_ms: float = 0.0

    # ── Helper: load a zone by index ──────────────────────────────
    def switch_zone(idx: int) -> None:
        nonlocal zone, zone_name, zone_idx, px, py, angle, pitch, is_interior
        nonlocal renderer, editor_3d, player_fh, cam_h
        zone_idx = idx % len(all_zones)
        zone_name = all_zones[zone_idx]
        zone = load_zone(zone_name)
        renderer.update_zone(zone, atlas, dn)
        renderer._is_interior = int(zone.first_person)
        is_interior = zone.first_person
        editor_3d.set_zone(zone)
        px, py = find_spawn(zone, renderer)
        angle = math.pi * 1.5
        pitch = 0.0
        player_fh = renderer.floor_height_at(px, py)
        cam_h = player_fh + EYE_HEIGHT
        pygame.display.set_caption(f"Ray Demo \u2014 {zone_name}")

    # ── Main loop ─────────────────────────────────────────────────
    running = True
    while running:
        dt = clock.tick(60 if fps_capped else 0) / 1000.0
        dt = min(dt, 0.05)  # cap to avoid huge jumps

        # ── Events ────────────────────────────────────────────────
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    if mouse_captured:
                        mouse_captured = False
                        pygame.mouse.set_visible(True)
                        pygame.event.set_grab(False)
                    else:
                        running = False

                # ── Tab: toggle 3D editor / 2.5D view ──
                elif event.key == pygame.K_TAB:
                    mod = pygame.key.get_mods()
                    if mod & pygame.KMOD_SHIFT:
                        # Shift+Tab = cycle zone
                        switch_zone(zone_idx + 1)
                    else:
                        # Tab = swap view mode
                        if view_mode == "2d":
                            view_mode = "3d"
                            # Sync 3D camera from 2.5D position
                            editor_3d.cam_x = px
                            editor_3d.cam_y = cam_h
                            editor_3d.cam_z = py
                            editor_3d.yaw = angle - math.pi * 0.5
                            editor_3d.pitch = pitch
                            pygame.display.set_caption(
                                f"Ray Demo — {zone_name} [3D EDITOR]")
                        else:
                            view_mode = "2d"
                            # Sync 2.5D camera from 3D position
                            px = editor_3d.cam_x
                            py = editor_3d.cam_z
                            angle = editor_3d.yaw + math.pi * 0.5
                            pitch = max(-PITCH_MAX,
                                       min(PITCH_MAX, editor_3d.pitch))
                            # Zone data already updated by sculpt editor
                            renderer.update_zone(zone, atlas, dn)
                            renderer._is_interior = int(is_interior)
                            player_fh = renderer.floor_height_at(px, py)
                            cam_h = player_fh + EYE_HEIGHT
                            pygame.display.set_caption(
                                f"Ray Demo — {zone_name}")

                # ── 3D editor: forward events ──
                elif view_mode == "3d":
                    editor_3d.handle_event(event)

                # ── 2.5D-specific keys below ──
                elif view_mode == "2d":

                    # ── Display toggles ──
                    if event.key == pygame.K_m:
                        show_minimap = not show_minimap
                    elif event.key == pygame.K_h:
                        show_hud = not show_hud
                    elif event.key == pygame.K_F1:
                        show_controls = not show_controls

                    # ── Rendering mode toggles ──
                    elif event.key == pygame.K_i:
                        is_interior = not is_interior
                        renderer._is_interior = int(is_interior)
                    elif event.key == pygame.K_n:
                        dn_idx = (dn_idx + 1) % len(DN_PRESETS)
                        dn_label, dn = DN_PRESETS[dn_idx]
                        renderer.update_fog(dn)
                    elif event.key == pygame.K_f:
                        fps_capped = not fps_capped
                    elif event.key == pygame.K_b:
                        show_entities = not show_entities
                    elif event.key == pygame.K_z:
                        show_depth = not show_depth

                    # ── FOV control ──
                    elif event.key == pygame.K_LEFTBRACKET:
                        fov = max(FOV_MIN, fov - FOV_STEP)
                        renderer.fov = fov
                    elif event.key == pygame.K_RIGHTBRACKET:
                        fov = min(FOV_MAX, fov + FOV_STEP)
                        renderer.fov = fov

                    # ── Resolution control ──
                    elif event.key == pygame.K_MINUS:
                        if res_idx > 0:
                            res_idx -= 1
                            _, rw, rh = RES_PRESETS[res_idx]
                            renderer.resize(rw, rh)
                    elif event.key == pygame.K_EQUALS:
                        if res_idx < len(RES_PRESETS) - 1:
                            res_idx += 1
                            _, rw, rh = RES_PRESETS[res_idx]
                            renderer.resize(rw, rh)

                    # ── Respawn ──
                    elif event.key == pygame.K_r:
                        px, py = find_spawn(zone, renderer)
                        angle = math.pi * 1.5
                        pitch = 0.0
                        player_fh = renderer.floor_height_at(px, py)
                        cam_h = player_fh + EYE_HEIGHT

                    # ── Noclip ──
                    elif event.key == pygame.K_g:
                        noclip = not noclip

                    # ── Fullscreen ──
                    elif event.key == pygame.K_F11:
                        fullscreen = not fullscreen
                        if fullscreen:
                            screen = pygame.display.set_mode(
                                (0, 0), pygame.FULLSCREEN
                            )
                        else:
                            screen = pygame.display.set_mode(
                                (WINDOW_W, WINDOW_H), pygame.RESIZABLE
                            )

            elif event.type == pygame.MOUSEWHEEL:
                if view_mode == "3d":
                    editor_3d.handle_event(event)

            elif event.type == pygame.MOUSEBUTTONDOWN:
                if view_mode == "3d":
                    if not mouse_captured:
                        mouse_captured = True
                        pygame.mouse.set_visible(False)
                        pygame.event.set_grab(True)
                    else:
                        editor_3d.handle_event(event)
                elif not mouse_captured:
                    mouse_captured = True
                    pygame.mouse.set_visible(False)
                    pygame.event.set_grab(True)

        # ── Mouse look ────────────────────────────────────────────
        if mouse_captured:
            if view_mode == "2d":
                mx, my = pygame.mouse.get_rel()
                angle += mx * MOUSE_SENS
                pitch = max(-PITCH_MAX,
                            min(PITCH_MAX,
                                pitch - my * MOUSE_SENS))
            # 3D mode mouse look is handled in editor_3d.update()

        # ── Per-mode update + render ──────────────────────────────
        if view_mode == "3d":
            editor_3d.update(dt, mouse_captured)
            editor_3d.draw(screen)
            # Simple FPS counter
            frame_times.append(0.0)
            if len(frame_times) > 60:
                frame_times.pop(0)
            pygame.display.flip()
            continue

        # ── Keyboard movement ─────────────────────────────────────
        keys = pygame.key.get_pressed()
        speed = MOVE_SPEED * dt
        if keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT]:
            speed *= SPRINT_MULT
        if keys[pygame.K_LCTRL] or keys[pygame.K_RCTRL]:
            speed *= SLOW_MULT

        # Keyboard turn (Q/E)
        if keys[pygame.K_q]:
            angle -= KB_TURN_SPEED * dt
        if keys[pygame.K_e]:
            angle += KB_TURN_SPEED * dt

        cos_a = math.cos(angle)
        sin_a = math.sin(angle)

        def try_move(dx: float, dy: float) -> None:
            nonlocal px, py, player_fh
            nx, ny = px + dx, py + dy
            if noclip:
                px, py = nx, ny
                player_fh = renderer.floor_height_at(px, py, player_fh)
                return
            # Height-aware collision
            if renderer.can_step_to(nx, py, player_fh,
                                    MAX_STEP_UP, HEAD_CLEARANCE):
                px = nx
            if renderer.can_step_to(px, ny, player_fh,
                                    MAX_STEP_UP, HEAD_CLEARANCE):
                py = ny
            # Update floor height under player
            player_fh = renderer.floor_height_at(px, py, player_fh)

        # Forward / backward
        if keys[pygame.K_w]:
            try_move(cos_a * speed, sin_a * speed)
        if keys[pygame.K_s]:
            try_move(-cos_a * speed, -sin_a * speed)
        # Strafe left / right
        if keys[pygame.K_a]:
            try_move(sin_a * speed, -cos_a * speed)
        if keys[pygame.K_d]:
            try_move(-sin_a * speed, cos_a * speed)

        # ── Smooth camera height toward target ────────────────────
        target_cam_h = player_fh + EYE_HEIGHT
        if abs(cam_h - target_cam_h) < 0.001:
            cam_h = target_cam_h
        else:
            cam_h += (target_cam_h - cam_h) * min(1.0, CAM_LERP_SPEED * dt)

        # ── Render ────────────────────────────────────────────────
        t0 = time.perf_counter()
        frame_surf = renderer.render(px, py, angle, cam_h, pitch)
        if show_entities:
            renderer.render_entities(px, py, angle)
        render_ms = (time.perf_counter() - t0) * 1000

        # ── Depth buffer debug overlay ────────────────────────────
        if show_depth:
            from engine._ray_render import depth_to_grayscale
            depth_to_grayscale(renderer._fb, renderer._depth_px,
                               renderer.sw, renderer.sh, 24.0)

        # Upscale to window
        win_w, win_h = screen.get_size()
        scaled = pygame.transform.scale(frame_surf, (win_w, win_h))
        screen.blit(scaled, (0, 0))

        # ── Overlays ──────────────────────────────────────────────
        # FPS tracking
        frame_times.append(render_ms)
        if len(frame_times) > 60:
            frame_times.pop(0)
        avg_ms = sum(frame_times) / len(frame_times) if frame_times else 16.7
        fps = 1000.0 / avg_ms if avg_ms > 0 else 0

        if show_minimap:
            draw_minimap(
                screen, zone.tiles,
                px, py, angle,
                zone.width, zone.height,
                renderer,
            )

        if show_hud:
            res_label = RES_PRESETS[res_idx][0]
            draw_hud(
                screen, font, font_sm, fps, render_ms,
                zone_name, px, py, angle,
                is_interior, dn_label,
                math.degrees(fov), res_label,
                noclip, fps_capped, show_controls,
                player_fh, cam_h,
            )

        # Render time bar (bottom)
        bar_w = min(int(render_ms * 3), win_w)
        bar_color = (
            (50, 200, 50) if render_ms < 8
            else (200, 200, 50) if render_ms < 16
            else (200, 50, 50)
        )
        pygame.draw.rect(screen, bar_color, (0, win_h - 4, bar_w, 4))

        ms_text = font_sm.render(f"{render_ms:.1f}ms", True, (180, 180, 180))
        screen.blit(ms_text, (10, win_h - 20))

        pygame.display.flip()

    pygame.quit()


if __name__ == "__main__":
    main()
