"""scenes/world_draw.py — Rendering helpers for the world scene.

All pure-draw functions live here so that WorldScene.draw() stays thin.
Every function receives the data it needs as parameters — no implicit
coupling to the scene object beyond what is explicitly passed.
"""

from __future__ import annotations
import pygame
from core.app import App
from core.constants import TILE_SIZE, TILE_COLORS
from components import (
    Position, Sprite, Player, Camera, Collider, Health, Hunger, Inventory,
    HitFlash, Lod, Facing, Hurtbox, Equipment, Projectile, Identity,
    ItemRegistry,
)
from logic.actions import weapon_rect_for


# ── Tiles ───────────────────────────────────────────────────────────

def draw_tiles(
    surface: pygame.Surface,
    tiles: list[list[int]],
    ox: int, oy: int,
    show_grid: bool,
    start_row: int, start_col: int,
    end_row: int, end_col: int,
):
    for row in range(start_row, end_row):
        for col in range(start_col, end_col):
            tile_id = tiles[row][col]
            color = TILE_COLORS.get(tile_id, (255, 0, 255))
            rect = pygame.Rect(
                ox + col * TILE_SIZE,
                oy + row * TILE_SIZE,
                TILE_SIZE, TILE_SIZE,
            )
            pygame.draw.rect(surface, color, rect)
            if show_grid:
                pygame.draw.rect(surface, (255, 255, 255), rect, 1)


# ── Entities (sprites + health bars) ───────────────────────────────

def draw_entities(
    surface: pygame.Surface,
    app: App,
    ox: int, oy: int,
    zone: str,
    show_all_zones: bool,
):
    entities = []
    for eid, pos, sprite in app.world.query(Position, Sprite):
        if not show_all_zones and getattr(pos, "zone", None) != zone:
            continue
        entities.append((sprite.layer, eid, pos, sprite))
    entities.sort(key=lambda e: e[0])

    for _, eid, pos, sprite in entities:
        sx = ox + int(pos.x * TILE_SIZE)
        sy = oy + int(pos.y * TILE_SIZE)

        if app.world.has(eid, HitFlash):
            app.draw_text(surface, sprite.char, sx + 8, sy + 4,
                          color=(255, 255, 255), font=app.font_lg)
        else:
            app.draw_text(surface, sprite.char, sx + 8, sy + 4,
                          color=sprite.color, font=app.font_lg)

        # Health bar (skip player — shown in HUD, skip full-health entities)
        if not app.world.has(eid, Player) and app.world.has(eid, Health):
            hp = app.world.get(eid, Health)
            if hp.current < hp.maximum:
                bar_w = TILE_SIZE - 4
                bar_h = 3
                bar_x = sx + 2
                bar_y = sy - 5
                ratio = max(0.0, hp.current / hp.maximum)
                pygame.draw.rect(surface, (40, 40, 40), (bar_x, bar_y, bar_w, bar_h))
                if ratio > 0.5:
                    br, bg, bb = 50, 200, 50
                elif ratio > 0.25:
                    br, bg, bb = 220, 200, 50
                else:
                    br, bg, bb = 220, 50, 50
                fill_w = max(1, int(bar_w * ratio))
                pygame.draw.rect(surface, (br, bg, bb), (bar_x, bar_y, fill_w, bar_h))
                pygame.draw.rect(surface, (80, 80, 80), (bar_x, bar_y, bar_w, bar_h), 1)


# ── Debug colliders / hurtboxes ────────────────────────────────────

def draw_debug_colliders(
    surface: pygame.Surface,
    app: App,
    ox: int, oy: int,
    zone: str,
    show_all_zones: bool,
):
    for eid, pos, collider in app.world.query(Position, Collider):
        if not show_all_zones and getattr(pos, "zone", None) != zone:
            continue
        sx = ox + int(pos.x * TILE_SIZE)
        sy = oy + int(pos.y * TILE_SIZE)
        cw = int(collider.width * TILE_SIZE)
        ch = int(collider.height * TILE_SIZE)
        color = (0, 255, 255) if not app.world.has(eid, Player) else (0, 255, 0)
        pygame.draw.rect(surface, color, pygame.Rect(sx, sy, cw, ch), 1)

    for eid, pos, hb in app.world.query(Position, Hurtbox):
        if not show_all_zones and getattr(pos, "zone", None) != zone:
            continue
        hx = ox + int((pos.x + hb.ox) * TILE_SIZE)
        hy = oy + int((pos.y + hb.oy) * TILE_SIZE)
        hw = int(hb.w * TILE_SIZE)
        hh = int(hb.h * TILE_SIZE)
        pygame.draw.rect(surface, (255, 255, 0), (hx, hy, hw, hh), 1)


# ── Weapon hitbox (melee attack visualisation) ─────────────────────

def draw_weapon_hitbox(
    surface: pygame.Surface,
    app: App,
    scene,
    ox: int, oy: int,
):
    if not scene.attack_active:
        return
    res = app.world.query_one(Player, Position)
    if not res:
        return
    player_eid = res[0]
    _, _, player_pos = res
    if player_pos.zone != scene.zone:
        return

    equip = app.world.get(player_eid, Equipment)
    registry = app.world.res(ItemRegistry)
    style = "melee"
    reach = None
    if equip and equip.weapon and registry:
        style = registry.get_field(equip.weapon, "style", "melee")
        reach = registry.get_field(equip.weapon, "reach", 1.5)
    if style == "ranged":
        return

    facing_comp = app.world.get(player_eid, Facing)
    facing = facing_comp.direction if facing_comp else "down"
    wx, wy, ww, wh = weapon_rect_for(player_pos, facing, reach=reach)
    wx_px = ox + int(wx * TILE_SIZE)
    wy_px = oy + int(wy * TILE_SIZE)
    ww_px = int(ww * TILE_SIZE)
    wh_px = int(wh * TILE_SIZE)

    weapon_surf = pygame.Surface((ww_px, wh_px), pygame.SRCALPHA)
    weapon_surf.fill((255, 50, 50, 150))
    surface.blit(weapon_surf, (wx_px, wy_px))
    pygame.draw.rect(surface, (255, 0, 0), (wx_px, wy_px, ww_px, wh_px), 2)


# ── Muzzle flash (ranged weapon visual) ───────────────────────────

def draw_muzzle_flash(surface: pygame.Surface, scene, ox: int, oy: int):
    if scene.muzzle_flash_timer <= 0:
        return
    fx0 = ox + int(scene.muzzle_flash_start[0] * TILE_SIZE)
    fy0 = oy + int(scene.muzzle_flash_start[1] * TILE_SIZE)
    fx1 = ox + int(scene.muzzle_flash_end[0] * TILE_SIZE)
    fy1 = oy + int(scene.muzzle_flash_end[1] * TILE_SIZE)
    pygame.draw.line(surface, (255, 220, 100), (fx0, fy0), (fx1, fy1), 2)


# ── Particles ──────────────────────────────────────────────────────

def draw_particles(pm, surface: pygame.Surface, cam_ox: int, cam_oy: int, tile_size: int):
    """Render all particles.  Extracted from ParticleManager.draw()."""
    for p in pm._particles:
        sx = cam_ox + int(p.x * tile_size)
        sy = cam_oy + int(p.y * tile_size)
        if p.fade:
            t = max(0.0, p.life / p.max_life)
            alpha = int(255 * t)
        else:
            t = 1.0
            alpha = 255

        r, g, b = p.color
        radius = max(1, int(p.size * t if p.fade else p.size))

        if alpha >= 250:
            pygame.draw.circle(surface, (r, g, b), (sx, sy), radius)
        else:
            d = radius * 2 + 2
            dot = pygame.Surface((d, d), pygame.SRCALPHA)
            pygame.draw.circle(dot, (r, g, b, alpha), (d // 2, d // 2), radius)
            surface.blit(dot, (sx - d // 2, sy - d // 2))


# ── Projectiles ────────────────────────────────────────────────────

def draw_projectiles(surface: pygame.Surface, app: App, ox: int, oy: int, zone: str):
    for eid, pos, proj in app.world.query(Position, Projectile):
        if pos.zone != zone:
            continue
        px = ox + int(pos.x * TILE_SIZE)
        py = oy + int(pos.y * TILE_SIZE)
        app.draw_text(surface, proj.char, px - 2, py - 4,
                      color=proj.color, font=app.font_lg)


# ── Crosshair ─────────────────────────────────────────────────────

def draw_crosshair(surface: pygame.Surface, scene):
    if not scene.show_crosshair or scene.editor_active or scene.modals.is_open:
        return
    mx, my = pygame.mouse.get_pos()
    if scene.tooltip_eid is not None and scene.tooltip_hp is not None:
        ccolor = (255, 80, 80)
    else:
        ccolor = (200, 200, 200)
    csize = 8
    gap = 3
    pygame.draw.line(surface, ccolor, (mx - csize, my), (mx - gap, my), 1)
    pygame.draw.line(surface, ccolor, (mx + gap, my), (mx + csize, my), 1)
    pygame.draw.line(surface, ccolor, (mx, my - csize), (mx, my - gap), 1)
    pygame.draw.line(surface, ccolor, (mx, my + gap), (mx, my + csize), 1)
    pygame.draw.circle(surface, (255, 255, 255), (mx, my), 1)


# ── Range ring ─────────────────────────────────────────────────────

def draw_range_ring(surface: pygame.Surface, app: App, ox: int, oy: int, zone: str, scene):
    if scene.editor_active or scene.modals.is_open:
        return
    res = app.world.query_one(Player, Position)
    if not res:
        return
    p_eid = res[0]
    _, _, pp = res
    if pp.zone != zone:
        return

    equip = app.world.get(p_eid, Equipment)
    reg = app.world.res(ItemRegistry)
    if not (equip and equip.weapon and reg and reg.get_field(equip.weapon, "style", "melee") == "ranged"):
        return

    rng = reg.get_field(equip.weapon, "range", 10.0)
    ring_px = int(rng * TILE_SIZE)
    cx_s = ox + int((pp.x + 0.4) * TILE_SIZE)
    cy_s = oy + int((pp.y + 0.4) * TILE_SIZE)
    ring_surf = pygame.Surface((ring_px * 2 + 2, ring_px * 2 + 2), pygame.SRCALPHA)
    pygame.draw.circle(ring_surf, (100, 180, 255, 35), (ring_px + 1, ring_px + 1), ring_px)
    pygame.draw.circle(ring_surf, (100, 180, 255, 60), (ring_px + 1, ring_px + 1), ring_px, 1)
    surface.blit(ring_surf, (cx_s - ring_px - 1, cy_s - ring_px - 1))


# ── Entity tooltip ─────────────────────────────────────────────────

def draw_tooltip(surface: pygame.Surface, app: App, scene):
    if scene.tooltip_eid is None or scene.editor_active or scene.modals.is_open:
        return
    mx, my = pygame.mouse.get_pos()
    ty = my - 22
    app.draw_text(surface, scene.tooltip_text, mx + 12, ty, (255, 255, 255))
    if scene.tooltip_hp:
        cur_hp, max_hp = scene.tooltip_hp
        bar_w, bar_h = 48, 4
        bx, by = mx + 12, ty + 14
        ratio = max(0.0, cur_hp / max_hp) if max_hp > 0 else 0
        pygame.draw.rect(surface, (40, 40, 40), (bx, by, bar_w, bar_h))
        if ratio > 0.5:
            bc = (50, 200, 50)
        elif ratio > 0.25:
            bc = (220, 200, 50)
        else:
            bc = (220, 50, 50)
        pygame.draw.rect(surface, bc, (bx, by, max(1, int(bar_w * ratio)), bar_h))
        pygame.draw.rect(surface, (80, 80, 80), (bx, by, bar_w, bar_h), 1)


# ── HUD ────────────────────────────────────────────────────────────

def draw_hud(surface: pygame.Surface, app: App, scene):
    hud_y = 8
    sw = surface.get_width()
    res = app.world.query_one(Player, Position)
    if not res:
        return
    player_eid = res[0]

    if app.world.has(player_eid, Health):
        health = app.world.get(player_eid, Health)
        app.draw_text(surface, f"Health: {health.current:.0f}/{health.maximum:.0f}", 8, hud_y, (255, 100, 100))
        hud_y += 16

    if app.world.has(player_eid, Hunger):
        hunger = app.world.get(player_eid, Hunger)
        app.draw_text(surface, f"Hunger: {hunger.current:.0f}/{hunger.maximum:.0f}", 8, hud_y, (255, 200, 100))
        hud_y += 16

    # ── Game clock display (top-right) ──
    from components import GameClock
    clock = app.world.res(GameClock)
    if clock:
        total_secs = clock.time
        # 1 real second = 1 game minute (base rate)
        game_minutes = total_secs
        hours = int(game_minutes // 60) % 24
        minutes = int(game_minutes) % 60
        day = int(game_minutes // 1440) + 1
        time_str = f"Day {day}  {hours:02d}:{minutes:02d}"
        speed = getattr(scene, "time_scale", 1.0)
        if speed > 1.01:
            time_str += f"  [{speed:.0f}x]"
        app.draw_text(surface, time_str, sw - 180, 8, (200, 200, 255))
        app.draw_text(surface, f"Zone: {scene.zone}", sw - 180, 24, (150, 150, 200))

    if not app.world.has(player_eid, Inventory):
        return

    inv = app.world.get(player_eid, Inventory)
    registry = app.world.res(ItemRegistry)
    equip = app.world.get(player_eid, Equipment)

    # Weapon info line
    if equip and equip.weapon and registry:
        wid = equip.weapon
        wname = registry.display_name(wid)
        wstyle = registry.get_field(wid, "style", "melee")
        wdmg = registry.get_field(wid, "damage", 0.0)
        if wstyle == "ranged":
            acc_pct = int(registry.get_field(wid, "accuracy", 0.9) * 100)
            wrng = registry.get_field(wid, "range", 10.0)
            stat_str = f"Weapon: {wname}  [DMG {wdmg:.0f} | ACC {acc_pct}% | RNG {wrng:.0f}]"
        else:
            wrch = registry.get_field(wid, "reach", 1.5)
            stat_str = f"Weapon: {wname}  [DMG {wdmg:.0f} | RCH {wrch:.1f}]"
        app.draw_text(surface, stat_str, 8, hud_y, (180, 180, 220))
    else:
        app.draw_text(surface, "Weapon: (fists)  [DMG 5]", 8, hud_y, (120, 120, 150))
    hud_y += 16

    # Cooldown bar
    if scene.attack_cooldown > 0:
        cd_ratio = min(1.0, scene.attack_cooldown / max(0.01, scene.attack_cooldown_max))
        cd_w = int(120 * cd_ratio)
        pygame.draw.rect(surface, (180, 80, 80), (8, hud_y, cd_w, 2))
        hud_y += 4

    # Weapon hotbar
    weapons_list = sorted(
        item_id for item_id, qty in inv.items.items()
        if qty > 0 and registry and registry.item_type(item_id) == "weapon"
    )
    if weapons_list:
        parts = []
        for i, wid in enumerate(weapons_list[:4]):
            name = registry.display_name(wid) if registry else wid
            marker = ">" if (equip and equip.weapon == wid) else " "
            parts.append(f"[{i+1}]{marker}{name}")
        app.draw_text(surface, "  ".join(parts), 8, hud_y, (160, 190, 220))
        hud_y += 16

    # Inventory summary
    if inv.items:
        parts = []
        for item_id, qty in inv.items.items():
            name = registry.display_name(item_id) if registry else item_id
            parts.append(f"{name}x{qty}")
        items_str = ", ".join(parts)
    else:
        items_str = "(empty)"
    app.draw_text(surface, f"Items: {items_str}", 8, hud_y, (100, 200, 255))
    hud_y += 16
    app.draw_text(surface, "[I] Inventory  [E] Loot  [RMB] Interact", 8, hud_y, (80, 160, 200))


# ── Debug overlay ──────────────────────────────────────────────────

def draw_debug_overlay(surface: pygame.Surface, app: App, scene, cam: Camera):
    y = 8
    app.draw_text(surface, f"FPS: {int(app.clock.get_fps())}", 8, y, (0, 255, 0))
    y += 16
    app.draw_text(surface, f"Entities: {len(app.world.debug_dump())}", 8, y, (0, 255, 0))
    y += 16
    app.draw_text(surface, f"Camera: ({cam.x:.1f}, {cam.y:.1f})", 8, y, (0, 255, 0))
    y += 16

    result = app.world.query_one(Player, Position)
    if result:
        _, _, pos = result
        app.draw_text(surface, f"Player: ({pos.x:.1f}, {pos.y:.1f})", 8, y, (0, 255, 0))
        y += 16

    i = 0
    for eid, pos, ident in app.world.query(Position, Identity):
        if app.world.has(eid, Player):
            continue
        if not scene.show_all_zones and getattr(pos, "zone", None) != scene.zone:
            continue
        if i >= 12:
            break
        dx = abs(pos.x - cam.x)
        dy = abs(pos.y - cam.y)
        if dx < 30 and dy < 20:
            lod_level = "?"
            lod_comp = app.world.get(eid, Lod)
            if lod_comp:
                lod_level = lod_comp.level
            app.draw_text(surface, f"  {ident.name} ({pos.x:.1f},{pos.y:.1f}) LOD={lod_level}",
                          8, y, (180, 180, 180))
            y += 14
            i += 1

    lod_counts = {"high": 0, "medium": 0, "low": 0}
    for _, lod in app.world.all_of(Lod):
        lod_counts[lod.level] = lod_counts.get(lod.level, 0) + 1
    y += 6
    app.draw_text(surface, f"LOD: H{lod_counts['high']} M{lod_counts['medium']} L{lod_counts['low']}", 8, y, (200, 200, 100))
    y += 14

    # ── Simulation debug info ──
    if hasattr(scene, "world_sim") and scene.world_sim and scene.world_sim.active:
        sim = scene.world_sim
        info = sim.debug_info()
        y += 4
        app.draw_text(surface, "── Simulation ──", 8, y, (100, 200, 255))
        y += 14
        app.draw_text(surface, f"  Nodes: {info['nodes']}  Pending: {info['pending_events']}  Processed: {info['events_processed']}", 8, y, (100, 200, 255))
        y += 14

        # Show off-screen NPCs (SubzonePos entities)
        from components.simulation import SubzonePos
        off_count = 0
        for eid, szp in app.world.all_of(SubzonePos):
            ident = app.world.get(eid, Identity)
            name = ident.name if ident else f"eid{eid}"
            if off_count < 8:
                app.draw_text(surface, f"  [{szp.subzone}] {name}", 8, y, (140, 180, 220))
                y += 14
            off_count += 1
        if off_count > 8:
            app.draw_text(surface, f"  ... +{off_count - 8} more off-screen", 8, y, (140, 180, 220))
            y += 14

        # Upcoming events
        upcoming = info.get("upcoming", [])
        if upcoming:
            y += 4
            app.draw_text(surface, "  Next events:", 8, y, (180, 180, 100))
            y += 14
            for ev in upcoming[:5]:
                if isinstance(ev, dict):
                    t_str = f"t={ev.get('time', 0):.1f}"
                    etype = ev.get('event_type', '?')
                    eeid = ev.get('eid', '?')
                    app.draw_text(surface, f"    {t_str} {etype} eid={eeid}", 8, y, (160, 160, 80))
                else:
                    app.draw_text(surface, f"    {ev}", 8, y, (160, 160, 80))
                y += 14

    y += 8
    app.draw_text(surface, "[Tab] debug  [G] grid  [F] fast-fwd  [F1] inspector", 8, y, (100, 100, 100))
