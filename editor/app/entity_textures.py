"""editor/app/entity_textures.py — Entity Texture Manager panel.

Integrates gen_entity_textures.py into the zone editor as an ImGui
window accessible from the Data menu.  Artists can:

* See every entity type with its texture status at a glance
* Generate template sprite sheets (billboard/prism)
* Open sheets in the system image editor
* Detect when entity definitions have changed since the sheet was made
* Reload the texture atlas after making changes

The engine loads cells directly from sprite sheets at atlas-build time —
no individual per-cell PNGs are created.

All heavy work (PNG generation) is done on the main thread because
pygame surfaces aren't thread-safe, but the operations are fast enough
(<100 ms per entity) that no async machinery is needed.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import imgui

from core.entity_defs import entity_registry, EntityDef
from core.paths import BILLBOARD_TEX_DIR, PRISM_TEX_DIR

# Import gen_entity_textures functions
from gen_entity_textures import (
    generate_prism_textures,
    generate_billboard_textures,
    _visual_fingerprint,
    _read_toml_hash,
    FACING_LABELS_8,
)

_log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Entities that never need textures (editor/system markers)
_SKIP_IDS = frozenset(("spawn_point", "trigger_zone", "loot_socket", "ground_item"))


# ── Status helpers ────────────────────────────────────────────────

class _EntityTexStatus:
    """Lightweight snapshot of texture status for one entity type."""

    __slots__ = (
        "edef", "out_dir", "render_type", "n_facings", "n_states",
        "sheet_exists", "toml_exists", "face_count", "expected_faces",
        "hash_match", "stored_hash", "current_hash", "is_skip",
    )

    def __init__(self, edef: EntityDef):
        self.edef = edef
        if edef.render_type == "prism":
            self.out_dir = PRISM_TEX_DIR
        else:
            self.out_dir = BILLBOARD_TEX_DIR
        self.render_type = edef.render_type
        self.is_skip = edef.id in _SKIP_IDS

        if self.is_skip:
            self.n_facings = 0
            self.n_states = 0
            self.sheet_exists = False
            self.toml_exists = False
            self.face_count = 0
            self.expected_faces = 0
            self.hash_match = True
            self.stored_hash = ""
            self.current_hash = ""
            return

        # Billboard / 8way — engine loads cells from the sprite sheet
        if edef.render_type in ("billboard", "8way"):
            self.n_facings = 8 if edef.directional else 1
            self.n_states = len(edef.states) or 1
            self.expected_faces = 1  # just the sheet

            sheet = self.out_dir / f"{edef.id}_sheet.png"
            toml = self.out_dir / f"{edef.id}_sheet.toml"
            self.sheet_exists = sheet.exists()
            self.toml_exists = toml.exists()
            self.face_count = int(self.sheet_exists)

            # Hash check
            self.current_hash = _visual_fingerprint(edef)
            self.stored_hash = _read_toml_hash(toml) if self.toml_exists else ""
            self.hash_match = (
                not self.stored_hash or self.stored_hash == self.current_hash
            )

        elif edef.render_type == "prism":
            self.n_facings = 0
            self.n_states = len(edef.states) or 1
            self.expected_faces = 1  # just the net

            net = self.out_dir / f"{edef.id}_net.png"
            toml = self.out_dir / f"{edef.id}_net.toml"
            self.sheet_exists = net.exists()
            self.toml_exists = toml.exists()
            self.face_count = int(self.sheet_exists)

            # Hash check
            self.current_hash = _visual_fingerprint(edef)
            self.stored_hash = _read_toml_hash(toml) if self.toml_exists else ""
            self.hash_match = (
                not self.stored_hash or self.stored_hash == self.current_hash
            )

        else:
            self.n_facings = 0
            self.n_states = 0
            self.expected_faces = 0
            self.face_count = 0
            self.sheet_exists = False
            self.toml_exists = False
            self.hash_match = True
            self.stored_hash = ""
            self.current_hash = ""

    @property
    def status_label(self) -> str:
        if self.is_skip:
            return "skip"
        if not self.hash_match:
            return "stale"
        if self.render_type in ("billboard", "8way"):
            if not self.sheet_exists:
                return "no sheet"
            return "ok"
        elif self.render_type == "prism":
            if not self.sheet_exists:
                return "no net"
            return "ok"
        return "unknown"

    @property
    def status_color(self) -> tuple[float, float, float, float]:
        """RGBA for status label."""
        s = self.status_label
        if s == "ok":
            return (0.4, 0.9, 0.4, 1.0)
        if s == "skip":
            return (0.5, 0.5, 0.5, 1.0)
        if s == "stale":
            return (0.9, 0.7, 0.2, 1.0)
        if s in ("no sheet", "no net", "missing"):
            return (0.9, 0.5, 0.3, 1.0)
        return (0.6, 0.6, 0.6, 1.0)


def _refresh_statuses() -> list[_EntityTexStatus]:
    """Build fresh status list for all entity defs."""
    reg = entity_registry()
    return [_EntityTexStatus(edef) for edef in sorted(reg.values(), key=lambda e: e.id)]


# ── Mixin ─────────────────────────────────────────────────────────

class EntityTexturesMixin:
    """ImGui panel for managing entity textures."""

    def _et_init(self) -> None:
        """Initialize entity-texture manager state.  Call from __init__."""
        self._et_statuses: list[_EntityTexStatus] = []
        self._et_filter: str = ""
        self._et_log: list[str] = []
        self._et_needs_atlas_reload: bool = False
        self._et_cell_w: int = 32
        self._et_cell_h: int = 128

    def _et_refresh(self) -> None:
        """Rebuild the status table (cheap — just stat checks)."""
        self._et_statuses = _refresh_statuses()

    # ── Actions ───────────────────────────────────────────────────

    def _et_generate_one(self, st: _EntityTexStatus, force: bool = False) -> None:
        """Generate template sheet for one entity."""
        edef = st.edef
        out_dir = st.out_dir
        self._et_log.append(f"── {edef.id} ({edef.render_type}) ──")

        try:
            if edef.render_type == "prism":
                paths = generate_prism_textures(edef, out_dir, force=force)
                for p in paths:
                    self._et_log.append(f"  WROTE {p.relative_to(PROJECT_ROOT)}")
            elif edef.render_type in ("billboard", "8way"):
                n_f = 8 if edef.directional else 1
                paths = generate_billboard_textures(
                    edef, out_dir, n_facings=n_f,
                    cell_w=self._et_cell_w, cell_h=self._et_cell_h,
                    force=force)
                for p in paths:
                    self._et_log.append(f"  WROTE {p.relative_to(PROJECT_ROOT)}")
        except Exception as exc:
            self._et_log.append(f"  ERROR: {exc}")
            _log.exception("Entity texture generation failed for %s", edef.id)

        self._et_needs_atlas_reload = True
        self._et_refresh()

    def _et_generate_all(self, force: bool = False) -> None:
        """Generate templates + slice for all non-skip entities."""
        for st in self._et_statuses:
            if st.is_skip:
                continue
            self._et_generate_one(st, force=force)
        self._et_refresh()

    def _et_open_sheet(self, st: _EntityTexStatus) -> None:
        """Open the sprite sheet / net in the system image editor."""
        if st.render_type == "prism":
            path = st.out_dir / f"{st.edef.id}_net.png"
        else:
            path = st.out_dir / f"{st.edef.id}_sheet.png"
        if not path.exists():
            self._et_log.append(f"  No image for {st.edef.id}")
            return
        try:
            subprocess.Popen(["xdg-open", str(path)])
            self._et_log.append(f"  Opened {path.name}")
        except FileNotFoundError:
            self._et_log.append("  Could not open file (xdg-open not found)")

    def _et_open_folder(self, st: _EntityTexStatus) -> None:
        """Open the entity's texture folder."""
        d = st.out_dir
        if d.exists():
            try:
                subprocess.Popen(["xdg-open", str(d)])
            except FileNotFoundError:
                pass

    def _et_reload_atlas(self) -> None:
        """Reload the texture atlas to pick up new/changed sheets."""
        try:
            from engine.textures import TextureAtlas, invalidate_sheet_cache
            from core.tiles.registry import register_extra_texture_keys
            from core.entity_defs import entity_texture_keys

            # Clear cached sheet surfaces so regenerated sheets are re-read
            invalidate_sheet_cache()

            # Re-register keys (in case new entities were added)
            register_extra_texture_keys(entity_texture_keys())
            self.atlas.ensure_all()

            # Rebuild renderer texture data
            if self.renderer and self.zone:
                self.renderer.update_zone(self.zone, self.atlas, getattr(self, 'dn', 1.0))

            self._et_log.append("Atlas reloaded.")
            self._et_needs_atlas_reload = False
        except Exception as exc:
            self._et_log.append(f"Atlas reload ERROR: {exc}")
            _log.exception("Atlas reload failed")

    # ── Draw ──────────────────────────────────────────────────────

    def _draw_entity_textures(self) -> None:
        """Render the Entity Textures manager window."""
        win_w, win_h = self.win_size
        imgui.set_next_window_position(
            win_w / 2 - 340, win_h / 2 - 260, imgui.FIRST_USE_EVER)
        imgui.set_next_window_size(680, 520, imgui.FIRST_USE_EVER)

        expanded, opened = imgui.begin(
            "Entity Textures", True, imgui.WINDOW_NO_SAVED_SETTINGS)
        if not opened:
            self.show_entity_textures = False
            imgui.end()
            return

        # Lazy-init status list
        if not self._et_statuses:
            self._et_refresh()

        # ── Toolbar ───────────────────────────────────────────────
        if imgui.button("New Entity"):
            if hasattr(self, '_ec_open_new'):
                self._ec_open_new()
        imgui.same_line()
        if imgui.button("Generate All"):
            self._et_generate_all(force=False)
        imgui.same_line()
        if imgui.button("Regenerate All"):
            self._et_generate_all(force=True)
        imgui.same_line()

        # Atlas reload button (highlighted when needed)
        if self._et_needs_atlas_reload:
            imgui.push_style_color(imgui.COLOR_BUTTON, 0.8, 0.5, 0.1, 1.0)
            imgui.push_style_color(imgui.COLOR_BUTTON_HOVERED, 0.9, 0.6, 0.2, 1.0)
        if imgui.button("Reload Atlas"):
            self._et_reload_atlas()
        if self._et_needs_atlas_reload:
            imgui.pop_style_color(2)

        imgui.same_line()
        if imgui.button("Refresh"):
            self._et_refresh()

        # ── Cell size ─────────────────────────────────────────────
        imgui.same_line(0, 20)
        imgui.push_item_width(60)
        _, self._et_cell_w = imgui.input_int("W##et_cw", self._et_cell_w, 0, 0)
        imgui.same_line()
        _, self._et_cell_h = imgui.input_int("H##et_ch", self._et_cell_h, 0, 0)
        imgui.pop_item_width()
        if imgui.is_item_hovered():
            imgui.set_tooltip("Billboard cell size (width x height)")

        # ── Filter ────────────────────────────────────────────────
        imgui.push_item_width(200)
        _, self._et_filter = imgui.input_text(
            "Filter##et", self._et_filter, 64)
        imgui.pop_item_width()

        imgui.separator()

        # ── Entity table ──────────────────────────────────────────
        # Reserve space for log at the bottom
        avail_h = imgui.get_content_region_available()[1]
        table_h = max(avail_h - 130, 120)

        imgui.begin_child("##et_table", 0, table_h, border=True)
        imgui.columns(6, "et_cols")
        imgui.set_column_width(0, 140)  # ID
        imgui.set_column_width(1, 75)   # Type
        imgui.set_column_width(2, 60)   # Status
        imgui.set_column_width(3, 70)   # Textures
        imgui.set_column_width(4, 130)  # States
        # col 5: Actions (remaining)

        for hdr in ("Entity", "Type", "Status", "Files", "States", "Actions"):
            imgui.text_colored(hdr, 0.6, 0.7, 0.9, 1.0)
            imgui.next_column()
        imgui.separator()

        filt = self._et_filter.lower().strip()

        for st in self._et_statuses:
            eid = st.edef.id
            if filt and filt not in eid.lower():
                continue

            # ID
            imgui.text(eid)
            imgui.next_column()

            # Render type
            imgui.text(st.render_type)
            imgui.next_column()

            # Status (colored)
            r, g, b, a = st.status_color
            imgui.text_colored(st.status_label, r, g, b, a)
            imgui.next_column()

            # Files count
            if st.is_skip:
                imgui.text_disabled("-")
            elif st.render_type in ("billboard", "8way"):
                imgui.text("sheet" if st.sheet_exists else "-")
            elif st.render_type == "prism":
                imgui.text("net" if st.sheet_exists else "-")
            else:
                imgui.text("-")
            imgui.next_column()

            # States
            if st.edef.states:
                states_str = ", ".join(st.edef.states)
                if len(states_str) > 18:
                    states_str = states_str[:16] + "…"
                imgui.text(states_str)
            else:
                imgui.text_disabled("-")
            imgui.next_column()

            # Actions
            if st.is_skip:
                imgui.text_disabled("(editor-only)")
            else:
                uid = f"##{eid}"
                # Edit (opens entity creator)
                if hasattr(self, '_ec_open_edit'):
                    if imgui.small_button(f"Def{uid}"):
                        self._ec_open_edit(eid)
                    imgui.same_line()
                if st.render_type in ("billboard", "8way"):
                    if imgui.small_button(f"Gen{uid}"):
                        self._et_generate_one(st, force=True)
                    imgui.same_line()
                    if st.sheet_exists:
                        if imgui.small_button(f"Paint{uid}"):
                            self._et_open_sheet(st)
                    imgui.same_line()
                elif st.render_type == "prism":
                    if imgui.small_button(f"Gen{uid}"):
                        self._et_generate_one(st, force=True)
                    imgui.same_line()
                    if st.sheet_exists:
                        if imgui.small_button(f"Paint{uid}"):
                            self._et_open_sheet(st)
                    imgui.same_line()

                if imgui.small_button(f"Dir{uid}"):
                    self._et_open_folder(st)
            imgui.next_column()

        imgui.columns(1)
        imgui.end_child()

        # ── Log output ────────────────────────────────────────────
        imgui.separator()
        imgui.text_colored("Log", 0.6, 0.7, 0.9, 1.0)
        imgui.same_line(0, 20)
        if imgui.small_button("Clear Log"):
            self._et_log.clear()

        imgui.begin_child("##et_log", 0, 0, border=True)
        for line in self._et_log[-50:]:  # last 50 lines
            if "ERROR" in line:
                imgui.text_colored(line, 0.9, 0.3, 0.3, 1.0)
            elif "WARNING" in line or "⚠" in line:
                imgui.text_colored(line, 0.9, 0.7, 0.2, 1.0)
            elif "WROTE" in line or "SLICED" in line:
                imgui.text_colored(line, 0.4, 0.8, 0.4, 1.0)
            else:
                imgui.text(line)
        # Auto-scroll to bottom
        if self._et_log:
            imgui.set_scroll_here_y(1.0)
        imgui.end_child()

        imgui.end()
