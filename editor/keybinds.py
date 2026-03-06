"""editor/keybinds.py — Centralized keybind registry with conflict detection and rebinding.

Every keyboard shortcut in the editor is registered here as a :class:`Keybind`
entry.  The registry is the single source of truth for:

* **Display** — the keybind panel reads from it.
* **Conflict detection** — overlapping key+mod+scope pairs are flagged.
* **Rebinding** — users can change keys at runtime; overrides persist to JSON.
* **Dispatch** — ``check(action, key, mods)`` replaces hardcoded ``K_*`` tests.

Modifier flags
--------------
We use simplified 3-bit flags (SHIFT|CTRL|ALT) instead of raw pygame bitmasks.
This makes matching, display, and serialization trivial.

Scope & Condition
-----------------
Each keybind specifies:

* **scope** — tool name(s) where it's active (``"global"`` = everywhere).
  Pipe-delimited for multi-tool: ``"sculpt|select|paint"``.
* **condition** — extra state guard: ``"selection"``, ``"no_selection"``,
  ``"aimed_ceiling"``, ``"aimed_floor"`` etc.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Optional

import pygame

# ── Simplified modifier flags ─────────────────────────────────────
MOD_NONE  = 0
MOD_SHIFT = 1
MOD_CTRL  = 2
MOD_ALT   = 4


def _simplify_mods(pg_mods: int) -> int:
    """Convert a raw ``pygame.key.get_mods()`` bitmask to 3-bit flags."""
    flags = 0
    if pg_mods & (pygame.KMOD_LSHIFT | pygame.KMOD_RSHIFT):
        flags |= MOD_SHIFT
    if pg_mods & (pygame.KMOD_LCTRL | pygame.KMOD_RCTRL):
        flags |= MOD_CTRL
    if pg_mods & (pygame.KMOD_LALT | pygame.KMOD_RALT):
        flags |= MOD_ALT
    return flags


# ── Keybind dataclass ─────────────────────────────────────────────

@dataclass
class Keybind:
    """A single keybind definition."""

    action: str             # Unique ID, e.g. "file.save"
    key: int                # Default pygame key constant
    mods: int = MOD_NONE    # MOD_SHIFT | MOD_CTRL | MOD_ALT
    scope: str = "global"   # "global", tool name, or "tool1|tool2"
    condition: str = ""     # "", "selection", "no_selection", "aimed_ceiling", …
    description: str = ""   # Human-readable
    category: str = "General"

    # Runtime override (set when user rebinds)
    _override_key: Optional[int] = field(default=None, repr=False)
    _override_mods: Optional[int] = field(default=None, repr=False)

    # ── Effective key/mods (respects overrides) ───────────────────

    @property
    def effective_key(self) -> int:
        return self._override_key if self._override_key is not None else self.key

    @property
    def effective_mods(self) -> int:
        return self._override_mods if self._override_mods is not None else self.mods

    @property
    def is_rebound(self) -> bool:
        return self._override_key is not None

    # ── Human-readable label ──────────────────────────────────────

    def key_label(self, *, use_effective: bool = True) -> str:
        """Return a human-readable key string like ``Ctrl+Shift+T``."""
        k = self.effective_key if use_effective else self.key
        m = self.effective_mods if use_effective else self.mods
        return _key_label(k, m)

    def default_label(self) -> str:
        return _key_label(self.key, self.mods)


def _key_label(key: int, mods: int) -> str:
    parts: list[str] = []
    if mods & MOD_CTRL:
        parts.append("Ctrl")
    if mods & MOD_ALT:
        parts.append("Alt")
    if mods & MOD_SHIFT:
        parts.append("Shift")
    name = pygame.key.name(key)
    # Capitalize nicely
    if len(name) == 1:
        name = name.upper()
    elif name.startswith("f") and name[1:].isdigit():
        name = name.upper()
    else:
        name = name.replace(" ", "").capitalize()
        # Map some ugly names
        _NICE = {
            "Pageup": "PgUp", "Pagedown": "PgDn",
            "Delete": "Del", "Backspace": "Bksp",
            "Semicolon": ";", "Backslash": "\\",
            "Return": "Enter", "Kpenter": "Enter",
            "Leftbracket": "[", "Rightbracket": "]",
            "Minus": "-", "Equals": "=", "Comma": ",",
            "Period": ".", "Slash": "/", "Backquote": "`",
        }
        name = _NICE.get(name, name)
    parts.append(name)
    return "+".join(parts)


# ── Registry ──────────────────────────────────────────────────────

class KeybindRegistry:
    """Central catalog of every editor keybind."""

    def __init__(self) -> None:
        self._binds: dict[str, Keybind] = {}

    # ── Registration ──────────────────────────────────────────────

    def register(
        self,
        action: str,
        key: int,
        mods: int = MOD_NONE,
        scope: str = "global",
        condition: str = "",
        description: str = "",
        category: str = "General",
    ) -> Keybind:
        kb = Keybind(action, key, mods, scope, condition, description, category)
        self._binds[action] = kb
        return kb

    # ── Lookup ────────────────────────────────────────────────────

    def get(self, action: str) -> Optional[Keybind]:
        return self._binds.get(action)

    def check(self, action: str, key: int, pg_mods: int) -> bool:
        """Return True if *key* + raw pygame *pg_mods* matches *action*'s binding.

        This is the primary method for replacing ``if key == K_*`` checks.
        Modifier matching is **exact** (no extra mods allowed).
        """
        kb = self._binds.get(action)
        if kb is None:
            return False
        flags = _simplify_mods(pg_mods)
        return kb.effective_key == key and kb.effective_mods == flags

    def key_for(self, action: str) -> int:
        """Return the effective pygame key constant (for ``get_pressed()`` checks)."""
        kb = self._binds.get(action)
        return kb.effective_key if kb else 0

    # ── Conflict detection ────────────────────────────────────────

    def conflicts(self) -> list[tuple[Keybind, Keybind]]:
        """Return all pairs of keybinds that share the same key+mods
        with overlapping scope and condition (potential conflicts)."""
        result: list[tuple[Keybind, Keybind]] = []
        binds = list(self._binds.values())
        for i, a in enumerate(binds):
            for b in binds[i + 1:]:
                if a.effective_key != b.effective_key:
                    continue
                if a.effective_mods != b.effective_mods:
                    continue
                # Check scope overlap
                a_scopes = set(a.scope.split("|"))
                b_scopes = set(b.scope.split("|"))
                if "global" not in a_scopes and "global" not in b_scopes:
                    if not (a_scopes & b_scopes):
                        continue  # disjoint scopes → no conflict
                # Check condition overlap
                if a.condition and b.condition and a.condition != b.condition:
                    continue  # different exclusive conditions → no conflict
                result.append((a, b))
        return result

    def conflict_set(self) -> set[str]:
        """Return set of action IDs that are involved in at least one conflict."""
        ids: set[str] = set()
        for a, b in self.conflicts():
            ids.add(a.action)
            ids.add(b.action)
        return ids

    # ── Rebinding ─────────────────────────────────────────────────

    def rebind(self, action: str, new_key: int, new_mods: int = MOD_NONE) -> None:
        kb = self._binds.get(action)
        if kb:
            kb._override_key = new_key
            kb._override_mods = new_mods

    def reset(self, action: str) -> None:
        kb = self._binds.get(action)
        if kb:
            kb._override_key = None
            kb._override_mods = None

    def reset_all(self) -> None:
        for kb in self._binds.values():
            kb._override_key = None
            kb._override_mods = None

    # ── Enumeration ───────────────────────────────────────────────

    def all_binds(self) -> list[Keybind]:
        return list(self._binds.values())

    def by_category(self) -> dict[str, list[Keybind]]:
        cats: dict[str, list[Keybind]] = {}
        for kb in self._binds.values():
            cats.setdefault(kb.category, []).append(kb)
        return cats

    # ── Persistence ───────────────────────────────────────────────

    def save_overrides(self, path: str) -> None:
        """Save user rebinds to a JSON file."""
        overrides: dict[str, dict] = {}
        for kb in self._binds.values():
            if kb.is_rebound:
                overrides[kb.action] = {
                    "key": kb._override_key,
                    "mods": kb._override_mods,
                }
        with open(path, "w") as f:
            json.dump(overrides, f, indent=2)

    def load_overrides(self, path: str) -> None:
        """Load user rebinds from a JSON file."""
        if not os.path.exists(path):
            return
        try:
            with open(path) as f:
                overrides = json.load(f)
        except (json.JSONDecodeError, OSError):
            return
        for action, data in overrides.items():
            kb = self._binds.get(action)
            if kb and isinstance(data, dict):
                kb._override_key = data.get("key")
                kb._override_mods = data.get("mods", MOD_NONE)

    def has_any_overrides(self) -> bool:
        return any(kb.is_rebound for kb in self._binds.values())


# ── Default registry factory ──────────────────────────────────────

def create_default_registry() -> KeybindRegistry:
    """Create and populate the registry with all editor keybinds."""
    r = KeybindRegistry()
    K = pygame

    # ═══════════════════════════════════════════════════════════════
    #  CAMERA (per-frame held keys — registered for display/rebind)
    # ═══════════════════════════════════════════════════════════════
    r.register("camera.forward",  K.K_w, description="Move forward",   category="Camera")
    r.register("camera.backward", K.K_s, description="Move backward",  category="Camera")
    r.register("camera.left",     K.K_a, description="Strafe left",    category="Camera")
    r.register("camera.right",    K.K_d, description="Strafe right",   category="Camera")
    r.register("camera.up",       K.K_SPACE, description="Fly up",     category="Camera")
    r.register("camera.down",     K.K_c, description="Fly down",       category="Camera")
    r.register("camera.yaw_left", K.K_q, description="Yaw left",       category="Camera")
    r.register("camera.yaw_right",K.K_e, description="Yaw right",      category="Camera")

    # ═══════════════════════════════════════════════════════════════
    #  FILE / EDIT
    # ═══════════════════════════════════════════════════════════════
    r.register("file.save",      K.K_s, MOD_CTRL, description="Save zone",               category="File")
    r.register("edit.undo",      K.K_z, MOD_CTRL, description="Undo",                    category="File")
    r.register("edit.redo_cz",   K.K_z, MOD_CTRL | MOD_SHIFT, description="Redo (C-S-Z)",category="File")
    r.register("edit.redo_cy",   K.K_y, MOD_CTRL, description="Redo (C-Y)",              category="File")

    # ═══════════════════════════════════════════════════════════════
    #  SELECTION (Ctrl combos)
    # ═══════════════════════════════════════════════════════════════
    r.register("select.all",       K.K_a, MOD_CTRL, description="Select all cells",       category="Selection")
    r.register("select.duplicate", K.K_d, MOD_CTRL, description="Duplicate selection",    category="Selection")
    r.register("edit.copy",        K.K_c, MOD_CTRL, description="Copy aimed cell",        category="Selection")
    r.register("edit.paste",       K.K_v, MOD_CTRL, description="Paste clipboard",        category="Selection")
    r.register("select.similar",   K.K_g, MOD_SHIFT, description="Select similar cells",  category="Selection")

    # ═══════════════════════════════════════════════════════════════
    #  DISPLAY (Ctrl+number variants)
    # ═══════════════════════════════════════════════════════════════
    r.register("display.walls_c",    K.K_1, MOD_CTRL, description="Toggle walls (Ctrl+1)",    category="Display")
    r.register("display.floors_c",   K.K_2, MOD_CTRL, description="Toggle floors (Ctrl+2)",   category="Display")
    r.register("display.ceilings_c", K.K_3, MOD_CTRL, description="Toggle ceilings (Ctrl+3)", category="Display")
    r.register("display.entities_c", K.K_4, MOD_CTRL, description="Toggle entities (Ctrl+4)", category="Display")
    r.register("display.wireframe_c",K.K_5, MOD_CTRL, description="Toggle wireframe (Ctrl+5)",category="Display")

    # ═══════════════════════════════════════════════════════════════
    #  DISPLAY (additional)
    # ═══════════════════════════════════════════════════════════════
    r.register("display.axes",     K.K_F10,       description="Toggle axes",     category="Display")
    r.register("display.isolate",  K.K_i, MOD_ALT,description="Isolate layer",   category="Display")

    # ═══════════════════════════════════════════════════════════════
    #  LAYER / MODE
    # ═══════════════════════════════════════════════════════════════
    r.register("layer.up",   K.K_PAGEUP,   description="Active layer 2",  category="Layer")
    r.register("layer.down", K.K_PAGEDOWN, description="Active layer 1",  category="Layer")
    r.register("view.toggle", K.K_TAB,     description="Toggle 3D/Preview", category="View")
    r.register("mode.arch",    K.K_F1, description="ARCH mode",    category="Mode")
    r.register("mode.surface", K.K_F2, description="SURFACE mode", category="Mode")
    r.register("mode.props",   K.K_F3, description="PROPS mode",   category="Mode")
    r.register("mode.logic",   K.K_F4, description="LOGIC mode",   category="Mode")

    # ═══════════════════════════════════════════════════════════════
    #  TOOL SWITCH (number keys)
    # ═══════════════════════════════════════════════════════════════
    for i in range(1, 6):
        r.register(f"subtool.{i}", getattr(K, f"K_{i}"),
                   description=f"Sub-tool {i}", category="Tool Switch")

    # ═══════════════════════════════════════════════════════════════
    #  UTILITY TOGGLES
    # ═══════════════════════════════════════════════════════════════
    r.register("tool.select", K.K_b,         description="Toggle Select",  category="Tool Switch")
    r.register("tool.stamp",  K.K_p,         description="Toggle Preset",  category="Tool Switch")
    r.register("tool.quad",   K.K_i,         description="Toggle Quad",    category="Tool Switch")
    r.register("tool.portal", K.K_o,         description="Toggle Portal",  category="Tool Switch")
    r.register("tool.curve",  K.K_SEMICOLON, description="Toggle Curve",   category="Tool Switch")

    # (Hotbar keyboard shortcuts removed — use scroll or palette click)

    # ═══════════════════════════════════════════════════════════════
    #  SELECTION OPS (active selection in sculpt/select/paint)
    # ═══════════════════════════════════════════════════════════════
    SS = "sculpt|select|paint"
    r.register("sel.ceil_mode", K.K_x, scope=SS, condition="selection",
               description="Toggle floor/ceiling mode", category="Selection Ops")
    r.register("sel.add_ceilings", K.K_t, scope=SS, condition="selection",
               description="Add ceilings", category="Selection Ops")
    r.register("sel.remove_ceilings", K.K_t, MOD_SHIFT, scope=SS, condition="selection",
               description="Remove ceilings", category="Selection Ops")
    r.register("sel.make_wall", K.K_h, scope=SS, condition="selection",
               description="Make wall", category="Selection Ops")
    r.register("sel.make_open", K.K_h, MOD_SHIFT, scope=SS, condition="selection",
               description="Make open", category="Selection Ops")
    r.register("sel.flatten_floors", K.K_l, scope=SS, condition="selection",
               description="Flatten floors to aimed", category="Selection Ops")
    r.register("sel.flatten_ceilings", K.K_l, MOD_SHIFT, scope=SS, condition="selection",
               description="Flatten ceilings to aimed", category="Selection Ops")
    r.register("sel.reset", K.K_DELETE, scope=SS, condition="selection",
               description="Reset selected cells", category="Selection Ops")
    r.register("sel.raise_upper_wall", K.K_u, scope=SS, condition="selection",
               description="Raise upper wall (batch)", category="Selection Ops")
    r.register("sel.lower_upper_wall", K.K_u, MOD_SHIFT, scope=SS, condition="selection",
               description="Lower upper wall (batch)", category="Selection Ops")
    r.register("sel.reset_upper_wall", K.K_u, MOD_CTRL, scope=SS, condition="selection",
               description="Reset upper wall (batch)", category="Selection Ops")

    # ═══════════════════════════════════════════════════════════════
    #  SCULPT (single cell, no selection)
    # ═══════════════════════════════════════════════════════════════
    r.register("sculpt.toggle_ceiling", K.K_t, scope="sculpt", condition="no_selection",
               description="Toggle ceiling", category="Sculpt")
    r.register("sculpt.make_wall", K.K_h, scope="sculpt", condition="no_selection",
               description="Make wall", category="Sculpt")
    r.register("sculpt.make_open", K.K_h, MOD_SHIFT, scope="sculpt", condition="no_selection",
               description="Make open", category="Sculpt")
    r.register("sculpt.reset_ceiling", K.K_r, scope="sculpt", condition="aimed_ceiling",
               description="Reset ceiling to sky", category="Sculpt")
    r.register("sculpt.reset_floor", K.K_r, scope="sculpt", condition="aimed_floor",
               description="Reset floor to 0", category="Sculpt")
    r.register("sculpt.raise_upper_wall", K.K_u, scope="sculpt", condition="no_selection",
               description="Raise upper wall", category="Sculpt")
    r.register("sculpt.lower_upper_wall", K.K_u, MOD_SHIFT, scope="sculpt", condition="no_selection",
               description="Lower upper wall", category="Sculpt")
    r.register("sculpt.reset_upper_wall", K.K_u, MOD_CTRL, scope="sculpt", condition="no_selection",
               description="Reset upper wall", category="Sculpt")
    r.register("sculpt.cycle_grid", K.K_g, scope="sculpt",
               description="Cycle snap grid", category="Sculpt")
    r.register("sculpt.toggle_layer", K.K_x, scope="sculpt", condition="no_selection",
               description="Toggle layer 1/2", category="Sculpt")

    # ═══════════════════════════════════════════════════════════════
    #  SELECT TOOL
    # ═══════════════════════════════════════════════════════════════
    r.register("select.ceil_mode", K.K_x, scope="select", condition="no_selection",
               description="Toggle ceiling mode", category="Select")

    # ═══════════════════════════════════════════════════════════════
    #  ENTITY TOOL
    # ═══════════════════════════════════════════════════════════════
    r.register("entity.cycle_state", K.K_t, scope="entity",
               description="Cycle entity state", category="Entity")

    # ═══════════════════════════════════════════════════════════════
    #  BOX / QUAD / STAMP
    # ═══════════════════════════════════════════════════════════════
    r.register("box.rotate",      K.K_r, scope="box",  description="Rotate 90°",       category="Box")
    r.register("box.toggle_grid", K.K_g, scope="box",  description="Toggle grid snap",  category="Box")
    r.register("quad.cycle_snap", K.K_g, scope="quad", description="Cycle quad snap",   category="Quad")
    r.register("overlay.cycle_snap", K.K_g, scope="overlay", description="Cycle snap grid", category="Overlay")
    r.register("stamp.cycle_mode",K.K_m, scope="stamp",description="Cycle apply mode",  category="Stamp")

    # ═══════════════════════════════════════════════════════════════
    #  GENERAL
    # ═══════════════════════════════════════════════════════════════
    r.register("delete.aimed",  K.K_DELETE, condition="no_selection",
               description="Delete aimed / clear cell", category="General")
    r.register("help.toggle",   K.K_SLASH, MOD_SHIFT,
               description="Toggle help overlay", category="General")

    return r
