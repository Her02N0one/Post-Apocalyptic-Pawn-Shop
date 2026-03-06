"""editor/app/data_viewers.py — DataViewersMixin: read-only TOML data browsers.

Provides four windows accessible from the Data menu:

* Entity Definitions  (data/entity_defs.toml)
* Items               (data/items.toml)
* Loot Tables         (data/loot_tables.toml)
* Presets             (data/presets/*.toml)
"""

from __future__ import annotations

from pathlib import Path

import imgui

_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


def _load_toml(path: Path) -> dict:
    """Load a TOML file, returning {} on error."""
    try:
        import tomllib
    except ModuleNotFoundError:          # Python < 3.11
        try:
            import tomli as tomllib      # type: ignore[no-redef]
        except ModuleNotFoundError:
            return {}
    try:
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except Exception:                    # noqa: BLE001
        return {}


class DataViewersMixin:
    """Read-only ImGui windows for browsing game data TOML files."""

    # ── Entity Definitions ────────────────────────────────────────

    def _draw_entity_defs_viewer(self) -> None:
        win_w, win_h = self.win_size
        imgui.set_next_window_position(
            win_w / 2 - 280, win_h / 2 - 220, imgui.FIRST_USE_EVER)
        imgui.set_next_window_size(560, 440, imgui.FIRST_USE_EVER)

        expanded, opened = imgui.begin("Entity Definitions", True,
                                       imgui.WINDOW_NO_SAVED_SETTINGS)
        if not opened:
            self.show_entity_defs_viewer = False
            imgui.end()
            return

        # Lazy-load
        if self._entity_defs_cache is None:
            self._entity_defs_cache = _load_toml(_DATA_DIR / "entity_defs.toml")

        data = self._entity_defs_cache
        if not data:
            imgui.text_colored("Could not load entity_defs.toml", 0.9, 0.4, 0.4, 1.0)
            imgui.end()
            return

        # Filter
        imgui.push_item_width(220)
        _, self._dv_ent_filter = imgui.input_text(
            "Filter##ent", self._dv_ent_filter, 64)
        imgui.pop_item_width()

        imgui.same_line()
        if imgui.button("Reload##ent", 70, 0):
            self._entity_defs_cache = _load_toml(_DATA_DIR / "entity_defs.toml")

        filt = self._dv_ent_filter.lower().strip()

        imgui.separator()
        imgui.begin_child("##ent_table", 0, 0, border=True)

        # Table header
        imgui.columns(5, "ent_cols")
        imgui.set_column_width(0, 140)
        imgui.set_column_width(1, 100)
        imgui.set_column_width(2, 60)
        imgui.set_column_width(3, 80)
        for hdr in ("ID", "Category", "Scale", "Directional", "States"):
            imgui.text_colored(hdr, 0.6, 0.7, 0.9, 1.0)
            imgui.next_column()
        imgui.separator()

        for eid, edef in sorted(data.items()):
            if not isinstance(edef, dict):
                continue
            display = edef.get("display_name", eid)
            if filt and filt not in eid.lower() and filt not in display.lower():
                continue
            imgui.text(eid)
            imgui.next_column()
            imgui.text(edef.get("category", ""))
            imgui.next_column()
            imgui.text(f"{edef.get('scale', 1.0):.2f}")
            imgui.next_column()
            imgui.text("Yes" if edef.get("directional") else "No")
            imgui.next_column()
            states = edef.get("states", [])
            imgui.text(", ".join(states) if states else "\u2014")
            imgui.next_column()

        imgui.columns(1)
        imgui.end_child()
        imgui.end()

    # ── Items ─────────────────────────────────────────────────────

    def _draw_items_viewer(self) -> None:
        win_w, win_h = self.win_size
        imgui.set_next_window_position(
            win_w / 2 - 300, win_h / 2 - 220, imgui.FIRST_USE_EVER)
        imgui.set_next_window_size(600, 440, imgui.FIRST_USE_EVER)

        expanded, opened = imgui.begin("Items", True,
                                       imgui.WINDOW_NO_SAVED_SETTINGS)
        if not opened:
            self.show_items_viewer = False
            imgui.end()
            return

        if self._items_cache is None:
            self._items_cache = _load_toml(_DATA_DIR / "items.toml")

        data = self._items_cache
        if not data:
            imgui.text_colored("Could not load items.toml", 0.9, 0.4, 0.4, 1.0)
            imgui.end()
            return

        imgui.push_item_width(220)
        _, self._dv_item_filter = imgui.input_text(
            "Filter##item", self._dv_item_filter, 64)
        imgui.pop_item_width()

        imgui.same_line()
        if imgui.button("Reload##item", 70, 0):
            self._items_cache = _load_toml(_DATA_DIR / "items.toml")

        filt = self._dv_item_filter.lower().strip()

        imgui.separator()
        imgui.begin_child("##item_table", 0, 0, border=True)

        imgui.columns(5, "item_cols")
        imgui.set_column_width(0, 130)
        imgui.set_column_width(1, 100)
        imgui.set_column_width(2, 80)
        imgui.set_column_width(3, 80)
        for hdr in ("ID", "Name", "Type", "Damage", "Extra"):
            imgui.text_colored(hdr, 0.6, 0.7, 0.9, 1.0)
            imgui.next_column()
        imgui.separator()

        for iid, idef in sorted(data.items()):
            if not isinstance(idef, dict):
                continue
            identity = idef.get("identity", {})
            name = identity.get("name", iid)
            if filt and filt not in iid.lower() and filt not in name.lower():
                continue

            imgui.text(iid)
            imgui.next_column()
            imgui.text(name)
            imgui.next_column()
            itype = idef.get("type", "")
            style = idef.get("style", "")
            imgui.text(f"{itype}/{style}" if style else itype)
            imgui.next_column()
            dmg = idef.get("damage")
            imgui.text(f"{dmg:.1f}" if dmg is not None else "\u2014")
            imgui.next_column()
            # Gather interesting extra fields
            extras = []
            for key in ("reach", "range", "accuracy", "heal", "defense",
                        "cooldown", "proj_speed"):
                val = idef.get(key)
                if val is not None:
                    extras.append(f"{key}={val}")
            imgui.text(", ".join(extras) if extras else "\u2014")
            imgui.next_column()

        imgui.columns(1)
        imgui.end_child()
        imgui.end()

    # ── Loot Tables ───────────────────────────────────────────────

    def _draw_loot_tables_viewer(self) -> None:
        win_w, win_h = self.win_size
        imgui.set_next_window_position(
            win_w / 2 - 260, win_h / 2 - 200, imgui.FIRST_USE_EVER)
        imgui.set_next_window_size(520, 400, imgui.FIRST_USE_EVER)

        expanded, opened = imgui.begin("Loot Tables", True,
                                       imgui.WINDOW_NO_SAVED_SETTINGS)
        if not opened:
            self.show_loot_tables_viewer = False
            imgui.end()
            return

        if self._loot_cache is None:
            self._loot_cache = _load_toml(_DATA_DIR / "loot_tables.toml")

        data = self._loot_cache
        tables = data.get("tables", data)
        if not tables:
            imgui.text_colored("Could not load loot_tables.toml",
                               0.9, 0.4, 0.4, 1.0)
            imgui.end()
            return

        if imgui.button("Reload##loot", 70, 0):
            self._loot_cache = _load_toml(_DATA_DIR / "loot_tables.toml")

        imgui.separator()
        imgui.begin_child("##loot_tree", 0, 0, border=True)

        for tid, tdef in sorted(tables.items()):
            if not isinstance(tdef, dict):
                continue
            desc = tdef.get("description", "")
            node_open = imgui.tree_node(
                f"{tid}##lt",
                imgui.TREE_NODE_DEFAULT_OPEN if len(tables) <= 5
                else 0)
            if desc:
                imgui.same_line()
                imgui.text_disabled(f"  {desc}")
            if node_open:
                for pi, pool in enumerate(tdef.get("pools", [])):
                    pool_name = pool.get("name", f"Pool {pi}")
                    rolls = pool.get("rolls", 1)
                    bonus = pool.get("bonus_rolls", 0)
                    if imgui.tree_node(
                            f"{pool_name}  (rolls={rolls}, bonus={bonus})##p{pi}"):
                        imgui.columns(3, f"lt_entries_{tid}_{pi}")
                        imgui.set_column_width(0, 160)
                        imgui.set_column_width(1, 80)
                        for hdr in ("Item", "Weight", "Count"):
                            imgui.text_colored(hdr, 0.6, 0.7, 0.9, 1.0)
                            imgui.next_column()
                        imgui.separator()
                        for entry in pool.get("entries", []):
                            imgui.text(entry.get("item", "?"))
                            imgui.next_column()
                            imgui.text(str(entry.get("weight", 1)))
                            imgui.next_column()
                            mn = entry.get("min_count", 1)
                            mx = entry.get("max_count", 1)
                            imgui.text(f"{mn}\u2013{mx}" if mn != mx
                                       else str(mn))
                            imgui.next_column()
                        imgui.columns(1)
                        imgui.tree_pop()
                imgui.tree_pop()

        imgui.end_child()
        imgui.end()

    # ── Presets ───────────────────────────────────────────────────

    def _draw_presets_viewer(self) -> None:
        win_w, win_h = self.win_size
        imgui.set_next_window_position(
            win_w / 2 - 260, win_h / 2 - 200, imgui.FIRST_USE_EVER)
        imgui.set_next_window_size(520, 400, imgui.FIRST_USE_EVER)

        expanded, opened = imgui.begin("Presets", True,
                                       imgui.WINDOW_NO_SAVED_SETTINGS)
        if not opened:
            self.show_presets_viewer = False
            imgui.end()
            return

        if self._presets_cache is None:
            self._presets_cache = _load_all_presets()

        data = self._presets_cache
        if not data:
            imgui.text_colored("No presets found in data/presets/",
                               0.9, 0.4, 0.4, 1.0)
            imgui.end()
            return

        if imgui.button("Reload##presets", 70, 0):
            self._presets_cache = _load_all_presets()

        imgui.separator()
        imgui.begin_child("##preset_tree", 0, 0, border=True)

        for fname, pdef in sorted(data.items()):
            pname = pdef.get("name", fname)
            cat = pdef.get("category", "Uncategorised")
            if imgui.tree_node(f"{pname}  [{cat}]##{fname}"):
                for key, val in sorted(pdef.items()):
                    if key in ("name", "category"):
                        continue
                    imgui.text_colored(f"  {key}:", 0.55, 0.65, 0.85, 1.0)
                    imgui.same_line()
                    imgui.text(str(val))
                imgui.tree_pop()

        imgui.end_child()
        imgui.end()


def _load_all_presets() -> dict[str, dict]:
    """Load every .toml in data/presets/ and return {filename: data}."""
    presets_dir = _DATA_DIR / "presets"
    if not presets_dir.is_dir():
        return {}
    result = {}
    for p in sorted(presets_dir.glob("*.toml")):
        data = _load_toml(p)
        if data:
            result[p.stem] = data
    return result
