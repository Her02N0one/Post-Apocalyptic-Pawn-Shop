# PAPS — Project Stress-Point Audit

> Where ambition turned into a mess.

**Generated:** 2025-01-XX  
**Scope:** All scene files, core infra, logic layer  
**Total project:** ~17,600 lines across 60+ Python files  
**Scene layer alone:** 4,484 lines across 8 files — 25% of the codebase  

---

## Executive Summary

The project has strong architectural bones — a clean ECS, a composable
scene stack, a unified tick orchestrator (`tick_systems`), a table-driven
entity factory (`spawn_from_descriptor`), and a well-decomposed world
scene.  The problem is that **none of the test scenes use any of it.**

Every test scene (Museum, Gym, Zoo) was copy-pasted from scratch and
evolved in isolation.  The result is 3+ copies of every shared concept —
tile rendering, entity rendering, mouse-to-tile conversion, arena
creation, NPC spawning, system ticking — each slightly different, each
missing features the others have, and none of them able to use the debug
overlay that only works in the main game.

| Scene | Lines | Uses `tick_systems`? | Uses `entity_factory`? | Has debug overlay? | Has DevLog? | Has EventBus? |
|---|---|---|---|---|---|---|
| WorldScene | 415 + 676 + 355 = **1,446** | **Yes** | **Yes** | **Yes** (F1) | **Yes** | **Yes** |
| MuseumScene | **1,357** | No | No | No | No | Per-tab reset |
| GymScene | **476** | No | No | No | No | No |
| ZooScene | **387** | No | No | No | No | No |
| DebugScene | **701** | N/A (overlay) | N/A | — | Yes (reads it) | Yes (reads it) |

The museum alone is nearly as large as the fully-decomposed world scene
(1,357 vs 1,446 lines) despite doing a fraction of the work.

---

## 1. The Copy-Paste Pandemic

### 1.1 Tile Rendering — 4 implementations

The project has one good tile renderer in `world_draw.draw_tiles()` with
viewport culling.  Three scenes ignore it and write their own:

| File | Approx. lines | Viewport culling? |
|---|---|---|
| `scenes/world_draw.py` L28–44 | 16 | **Yes** |
| `scenes/museum_scene.py` L998–1008 | 10 | No — full grid scan |
| `scenes/gym_scene.py` L212–220 | 8 | No — full grid scan |
| `scenes/zoo_scene.py` L208–215 | 7 | No — full grid scan |

All three inline versions share identical structure: nested `for row/col`
→ `TILE_COLORS.get(tid)` → `pygame.draw.rect`.  If a new tile type is
added, you have to change four files.

### 1.2 Entity Rendering — 4 variants

| File | What it draws | Health bar? | Hit-flash? | Sorting? |
|---|---|---|---|---|
| `world_draw.py` L50–92 | Sprite + name + health | Yes (with outline) | Yes | Layer-sorted |
| `museum_scene.py` L1017–54 | Sprite + name + brain label + health | Yes (no outline) | No | No |
| `gym_scene.py` L227–237 | Sprite + name only | **No** | No | No |
| `zoo_scene.py` L218–273 | Sprite + cell label + stat line | **No** | No | No |

Each scene reinvents how to draw an entity.  If you add a new visual
feature (e.g. status icons, team-color outlines), you have to add it in
four places — or more likely, you add it in one and forget the others.

### 1.3 `_mouse_to_tile()` — 3 copies + 1 variant

| File | Function name |
|---|---|
| `museum_scene.py` L1123–1131 | `_mouse_to_tile()` |
| `gym_scene.py` L289–298 | `_mouse_to_tile()` |
| `world_scene.py` L155–164 | `_screen_to_tile()` (same logic, different name) |
| `zoo_scene.py` L174–186 | Inline in `_try_select()` (same math, returns floats) |

Four files, four implementations of "convert screen pixel to tile coord."

### 1.4 `_draw_diamond()` — 3 copies

| File | Lines |
|---|---|
| `museum_scene.py` L1346–1350 | 4 lines |
| `gym_scene.py` L314–317 | 4 lines |
| `world_draw.py` L669–673 | 4 lines |

Same 4-line function in three places.  `_draw_circle_alpha()` is
likewise duplicated between `museum_scene.py` and `world_draw.py`.

### 1.5 Arena / Zone Setup — 2 identical functions

| File | Function | Dimensions |
|---|---|---|
| `museum_scene.py` L48–57 | `_make_arena()` | 30×20, grass + wall border |
| `gym_scene.py` L37–44 | `_make_open()` | 30×20, grass + wall border |

These are **the same function** with different names.  Gym extends the
pattern with `_make_maze()` and `_make_rooms()`, but even those just add
walls to the identical base grid.

### 1.6 Wall Painting — 2 near-identical blocks

| File | Lines |
|---|---|
| `museum_scene.py` L851–880 | Pathfinding tab: LMB toggles wall, drag paints |
| `gym_scene.py` L168–191 | LMB toggles wall, drag paints |

Same click-to-toggle, drag-to-paint, mouseup-recalculate logic.

---

## 2. The Museum Monolith

`museum_scene.py` at **1,357 lines** is the largest single file in the
project.  It contains 8 tabbed exhibits with no tab abstraction — each
tab is a cluster of `_setup_*`, `_update_*`, `_draw_*` methods, plus
shared state tracked via instance variables (`_eids`, `_running`, timers,
flags).

### Why this is a problem:

- **No shared `Exhibit` base class or protocol.**  Every tab re-invents
  the same lifecycle: clear arena → spawn entities → start systems →
  draw debug overlay.  Adding a 9th tab means copy-pasting ~120 lines.

- **Entity spawn boilerplate** dominates the file.  There are **5 separate
  places** that manually build entities with 12–17 `w.add()` calls each:
  - `_spawn_npc()` (L125–164)
  - `_spawn_combat_npc()` (L216–255)
  - Faction demo inline spawns (L352–410)
  - Stealth demo inline spawns (L525–600)
  - Needs demo inline spawns (L730–778)

  Meanwhile, `logic/entity_factory.spawn_from_descriptor()` exists and
  handles all of this from a dictionary — but only the zoo uses it.

- **The `update()` method is a 50-line if/elif chain** (L893–945) where
  most branches call `run_brains()` + `movement_system()` with slight
  variations.  `tick_systems()` was literally built for this — its
  `skip_lod`, `skip_needs`, `skip_brains` flags map exactly to what each
  tab needs — but it isn't used.

- **Tab state bleeds.**  Switching tabs calls a new `_setup_*` method,
  which overwrites the EventBus (`app.world.set_res(EventBus())`),
  silently dropping any prior subscriptions.  If a tab forgets to
  re-subscribe, events vanish.

---

## 3. The Debug Island

`debug_scene.py` (701 lines) is a powerful overlay with 4 tabs:

| Tab | What it does |
|---|---|
| AI Observer | NPC table with brain state, action, goal → click for detail sidebar + action log |
| ECS Browser | Filterable list of all entities with component summary |
| Entity Editor | Live field editing on any component |
| Event Log | DevLog feed with category filters (AI, combat, event, etc.) |

**None of this is available from the museum, gym, or zoo.**

The debug scene is imported via `from scenes.debug_scene import DebugScene`
only in `world_helpers.py` (L153–155), behind an `if inp.just("debug_scene")`
check.  The test scenes don't handle F1.  Their docstrings mention "F3 —
back to scene picker" but none of them actually bind F3.

This means:
- You can't inspect AI decisions in the museum's AI Brains exhibit
- You can't browse entities in the gym while testing pathfinding
- You can't check event logs in any test scene
- The debug tools that took 700 lines to build are **walled off** from
  the scenes that need them most

### What the test scenes have instead:

| Scene | Debug info available |
|---|---|
| Museum (Combat) | Inline `_draw_combat_debug()` — range circles, vision cones, hit-flash. **Good but not reusable.** |
| Museum (AI) | Brain state label drawn on entity. No action log. |
| Museum (Needs) | Hunger bar drawn on entity. No detail view. |
| Gym | Metrics panel (FPS, ECS query time, NPC count). A* path visualization. |
| Zoo | Component sidebar on selected entity. |

Each scene built its own mini-debug-UI from scratch.  None of them can
show you what the Entity Editor or AI Observer shows.

---

## 4. Infrastructure That Exists but Isn't Used

### 4.1 `tick_systems()` — the ignored orchestrator

`logic/tick.py` provides `tick_systems(world, dt, tiles)` with keyword
flags for exactly the kind of selective system ticking the test scenes
need:

```python
def tick_systems(world, dt, tiles, *,
                 skip_lod=False, skip_needs=False, skip_brains=False):
```

It handles: `GameClock` advancement, LOD transitions, hunger/eating,
AI brains, movement, projectiles, and EventBus draining — all in 30 lines.

**Only WorldScene uses it.**  Museum has 6 inline call sites that
manually replicate subsets of this.  Gym has its own inline calls.

### 4.2 `spawn_from_descriptor()` — the ignored factory

`logic/entity_factory.py` (349 lines) provides a table-driven entity
spawner that reads a dictionary of component data and builds a complete
entity.  Characters and items in `data/characters.toml` and
`data/items.toml` are designed to be spawned through it.

**Only the zoo uses it.**  Museum hand-builds every entity with 12–17
`w.add()` calls per NPC, duplicating what the factory does automatically.

### 4.3 `DevLog` — absent from test scenes

`components.dev_log.DevLog` is a ring-buffer logger designed for runtime
AI/combat/event debugging.  WorldScene creates it.  DebugScene reads it.
Test scenes don't create it, don't write to it, and can't display it.

### 4.4 `world_draw.py` helpers — reimplemented locally

`world_draw.py` exports: `draw_tiles()`, `draw_entities()`,
`draw_particles()`, `draw_projectiles()`, `draw_diamond()`,
`draw_circle_alpha()`.  These are exactly the functions that museum, gym,
and zoo each rewrite inline.

---

## 5. Lifecycle & Resource Leaks

### 5.1 WorldScene has no `on_exit()`

Every test scene properly cleans up entities and calls `world.purge()` in
`on_exit()`.  **WorldScene doesn't.**  If the world scene is ever popped
from the stack (e.g. during scene transitions), spawned entities,
EventBus subscriptions, and the world sim are never cleaned up.

### 5.2 EventBus overwrite pattern

Museum creates a fresh `EventBus()` every time a tab is set up:

```python
app.world.set_res(EventBus())  # L176, L324
```

This silently discards any existing subscriptions.  If code outside the
museum subscribed to events (e.g. a system that registered on startup),
those handlers are gone.  The safe pattern — used by WorldScene — is to
check first:

```python
if not app.world.res(EventBus):
    app.world.set_res(EventBus())
```

### 5.3 Tuning inconsistency

| Scene | Loads tuning on enter? | Uses tuning values? |
|---|---|---|
| WorldScene | Yes | Yes |
| GymScene | Yes | Yes |
| MuseumScene | **No** | **Yes** (L682: `_tun_sec`) |
| ZooScene | No | No |

Museum reads tuning parameters without calling `load_tuning()` first,
relying on it having been loaded by a previous scene.  If the museum is
the first scene entered, those values may be stale or default.

### 5.4 Private attribute access

Museum accesses `ParticleManager._particles` (L709–722) — a private
attribute.  If the internal storage changes, this silently breaks.  The
fix is trivial: add a `@property` to `ParticleManager`.

---

## 6. Missing Connections

| What's missing | Impact |
|---|---|
| F1 (debug overlay) in test scenes | Can't inspect AI, browse ECS, edit entities, or see event log |
| F3 (scene picker) in test scenes | Docstrings promise it; code doesn't deliver |
| F4 (tuning reload) in test scenes | Can only hot-reload in world scene |
| Shared sidebar/inspector widget | Museum, zoo, and debug scene each build their own entity inspector |
| Shared metrics panel | Gym has FPS/query-time; museum and zoo have nothing |
| Consistent key bindings | Each scene defines its own ad-hoc key mapping |

---

## 7. Severity Ranking

| # | Problem | Severity | Effort to fix | Impact |
|---|---|---|---|---|
| 1 | Museum monolith (1,357 lines, no tab abstraction) | **Critical** | High | Every new exhibit adds ~120 lines to one file |
| 2 | Debug overlay walled off from test scenes | **Critical** | Medium | 700 lines of tooling are useless in 3/4 scenes |
| 3 | `tick_systems` not used by test scenes | **High** | Low | 6+ inline call sites that should be 1-liners |
| 4 | `spawn_from_descriptor` not used by museum/gym | **High** | Medium | ~200 lines of manual `w.add()` calls that the factory handles |
| 5 | 4× tile rendering, 4× entity rendering | **High** | Medium | Any visual change needs 4-file edits |
| 6 | No `on_exit` in WorldScene | **High** | Low | Potential resource/entity leak |
| 7 | 3× `_mouse_to_tile` | **Medium** | Low | Trivial to extract |
| 8 | EventBus overwrite in museum | **Medium** | Low | Silent subscription loss |
| 9 | No DevLog in test scenes | **Medium** | Low | Can't trace AI decisions where you most need to |
| 10 | 3× `_draw_diamond`, 2× `_draw_circle_alpha` | **Low** | Low | 4 lines each but symbolic of the pattern |

---

## 8. Recommended Remediation Path

These are ordered to maximize payoff relative to effort, not by severity.

### Phase 1 — Low-hanging fruit (small changes, big wins)

1. **Wire `tick_systems` into museum and gym.**  Replace every inline
   `run_brains() / movement_system() / projectile_system() / bus.drain()`
   block with a single `tick_systems(w, dt, tiles, skip_lod=True, ...)`
   call.  Deletes ~40 lines from museum alone.

2. **Make debug overlay scene-agnostic.**  Move the F1 handler into
   `Scene` base class or into a mixin.  Any scene that has a `world`
   with entities should be able to pop up the debug overlay.

3. **Add `on_exit` to WorldScene.**  Even if it's just entity cleanup +
   `purge()`.

4. **Extract `_mouse_to_tile` to a shared utility.**  One function in
   `scenes/` `__init__.py` or a new `scenes/shared.py`.

5. **Add a `particles` property to `ParticleManager`.**  Stop reaching
   into `_particles`.

### Phase 2 — Consolidate rendering

6. **Have test scenes call `world_draw.draw_tiles()` and
   `world_draw.draw_entities()`** instead of inline rendering.  The
   existing functions already handle everything the test scenes need;
   test scenes just need to pass the right arguments.

7. **Delete duplicate `_draw_diamond`, `_draw_circle_alpha`** from
   museum and gym; import from `world_draw`.

### Phase 3 — Museum decomposition

8. **Define an `Exhibit` protocol or base class:**
   ```
   class Exhibit:
       name: str
       def setup(self, world, tiles) -> list[int]: ...
       def update(self, world, dt, tiles): ...
       def draw(self, surf, world, cam): ...
       def teardown(self, world, eids): ...
   ```
   Each tab becomes a self-contained class in its own file under
   `scenes/exhibits/`.  MuseumScene becomes a thin tab-bar host.

9. **Use `spawn_from_descriptor` in exhibits** instead of manual
   component assembly.  Define exhibit NPC templates as dicts (or
   in a TOML file) and let the factory handle the 12-field boilerplate.

### Phase 4 — Unify scene infrastructure

10. **Create a `TestScene` base class** (or mixin) that provides:
    - Camera + GameClock setup
    - Tuning load
    - DevLog creation
    - F1/F3/F4 key handling
    - Arena creation
    - Entity cleanup in `on_exit`
    - Wall-painting helpers

    Museum, Gym, and Zoo inherit from `TestScene` instead of raw `Scene`.

---

## Appendix: File-by-File Line Counts

```
scenes/museum_scene.py    1,357   ← largest single file
scenes/debug_scene.py       701
scenes/world_draw.py        676
scenes/gym_scene.py         476
scenes/world_scene.py       415
scenes/zoo_scene.py         387
scenes/world_helpers.py     355
scenes/scene_picker.py      117
                          ─────
scenes/ total             4,484
project total            ~17,600
```
