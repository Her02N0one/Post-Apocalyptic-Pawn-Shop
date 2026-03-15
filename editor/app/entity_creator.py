"""editor/app/entity_creator.py — Entity type creator / editor panel.

Provides an ImGui window for the full entity-authoring workflow:

* **Create** a brand-new entity type (ID, display name, category,
  render type, states, geometry, colour)
* **Edit** an existing entity's visual/placement properties
* **Delete** an entity definition (with confirmation)
* Optionally **generate textures** immediately after saving

On save the panel writes to ``data/entity_defs.toml`` via the
:mod:`editor.app.entity_writer` serialiser, hot-reloads the entity
registry, refreshes the texture-status panel, and (when requested)
generates template textures and reloads the atlas.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import imgui

from core.entity_defs import entity_registry, reload_registry, get_entity_def
from editor.app.entity_writer import load_raw, add_or_update, remove_entity

_log = logging.getLogger(__name__)

_CATEGORIES = ["characters", "props", "gameplay"]
_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")


# ── Form defaults ─────────────────────────────────────────────────

def _default_form() -> dict[str, Any]:
    """Return the initial form state for a new entity."""
    return {
        "id":           "",
        "display_name": "",
        "category":     "characters",
        "render_type":  "billboard",
        "color":        [180, 180, 180],
        "directional":  True,
        "sprite_key":   "",
        "states":       ["idle"],
        "width":        0.5,
        "depth":        0.5,
        "height":       1.0,
        "elevation":    0.0,
        "movable":      False,
        "shared_sides": True,
        "cell_w":       32,
        "cell_h":       128,
    }


def _form_from_raw(eid: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Populate form data from an existing raw TOML entry."""
    color = raw.get("color", [180, 180, 180])
    states = raw.get("states", ["default"])
    textures = raw.get("textures", {})
    shared_sides = textures.get("east", "") == textures.get("west", "")

    return {
        "id":           eid,
        "display_name": raw.get("display_name", eid),
        "category":     raw.get("category", "misc"),
        "render_type":  raw.get("render_type", "billboard"),
        "color":        list(color) if isinstance(color, (list, tuple)) else [180, 180, 180],
        "directional":  bool(raw.get("directional", False)),
        "sprite_key":   raw.get("sprite_key", ""),
        "states":       list(states) if isinstance(states, (list, tuple)) else ["default"],
        "width":        float(raw.get("width", 0.5)),
        "depth":        float(raw.get("depth", 0.5)),
        "height":       float(raw.get("height", 1.0)),
        "elevation":    float(raw.get("elevation", 0.0)),
        "movable":      bool(raw.get("movable", False)),
        "shared_sides": shared_sides,
        "cell_w":       32,
        "cell_h":       128,
    }


# ── Mixin ─────────────────────────────────────────────────────────

class EntityCreatorMixin:
    """ImGui panel for creating and editing entity type definitions."""

    # ── Init ──────────────────────────────────────────────────────

    def _ec_init(self) -> None:
        """Initialise entity-creator state.  Call from ``__init__``."""
        self._ec_mode: str = "new"           # "new" or "edit"
        self._ec_form: dict[str, Any] = _default_form()
        self._ec_new_state: str = ""
        self._ec_errors: list[str] = []
        self._ec_col: list[float] = [0.7, 0.7, 0.7]
        self._ec_confirm_delete: bool = False

    # ── Public openers ────────────────────────────────────────────

    def _ec_open_new(self) -> None:
        """Open the creator panel for a brand-new entity."""
        self._ec_mode = "new"
        self._ec_form = _default_form()
        self._ec_new_state = ""
        self._ec_errors = []
        self._ec_confirm_delete = False
        self._ec_col = [0.7, 0.7, 0.7]
        self.show_entity_creator = True

    def _ec_open_edit(self, entity_id: str) -> None:
        """Open the creator panel pre-filled with an existing entity."""
        raw_data = load_raw()
        raw = raw_data.get(entity_id)
        if not raw:
            return
        self._ec_mode = "edit"
        self._ec_form = _form_from_raw(entity_id, raw)
        self._ec_new_state = ""
        self._ec_errors = []
        self._ec_confirm_delete = False
        c = self._ec_form["color"]
        self._ec_col = [c[0] / 255.0, c[1] / 255.0, c[2] / 255.0]
        self.show_entity_creator = True

    # ── Validation ────────────────────────────────────────────────

    def _ec_validate(self) -> list[str]:
        f = self._ec_form
        errors: list[str] = []
        eid = f["id"].strip()
        if not eid:
            errors.append("Entity ID is required.")
        elif not _ID_RE.match(eid):
            errors.append("ID must start with a letter and contain only lowercase letters, digits, underscores.")
        elif self._ec_mode == "new" and eid in entity_registry():
            errors.append(f"Entity '{eid}' already exists.")
        if not f["display_name"].strip():
            errors.append("Display name is required.")
        if not f["states"]:
            errors.append("At least one animation state is required.")
        if f["render_type"] == "prism":
            for dim in ("width", "depth", "height"):
                if f[dim] <= 0:
                    errors.append(f"Prism {dim} must be > 0.")
        return errors

    # ── Build TOML fields ─────────────────────────────────────────

    def _ec_build_fields(self) -> dict[str, Any]:
        """Build the dict that will be merged into the TOML entry."""
        f = self._ec_form
        eid = f["id"].strip()

        fields: dict[str, Any] = {
            "display_name": f["display_name"].strip(),
            "category":     f["category"],
            "render_type":  f["render_type"],
            "color":        [int(self._ec_col[0] * 255),
                             int(self._ec_col[1] * 255),
                             int(self._ec_col[2] * 255)],
            "directional":  f["directional"],
            "states":       list(f["states"]),
            "movable":      f["movable"],
        }

        if f["render_type"] in ("billboard", "8way"):
            fields["sprite_key"] = f["sprite_key"].strip() or eid
        elif f["render_type"] == "prism":
            fields["width"]     = f["width"]
            fields["depth"]     = f["depth"]
            fields["height"]    = f["height"]
            fields["elevation"] = f["elevation"]
            # Auto-generate textures table
            if f["shared_sides"]:
                fields["textures"] = {
                    "north":  f"{eid}:front",
                    "south":  f"{eid}:back",
                    "east":   f"{eid}:side",
                    "west":   f"{eid}:side",
                    "top":    f"{eid}:top",
                    "bottom": "",
                }
            else:
                fields["textures"] = {
                    "north":  f"{eid}:front",
                    "south":  f"{eid}:back",
                    "east":   f"{eid}:right",
                    "west":   f"{eid}:left",
                    "top":    f"{eid}:top",
                    "bottom": "",
                }

        return fields

    # ── Save / generate / delete ──────────────────────────────────

    def _ec_save(self, generate: bool = False) -> bool:
        """Validate → write TOML → reload registry.  Returns ``True`` on success."""
        self._ec_errors = self._ec_validate()
        if self._ec_errors:
            return False

        eid = self._ec_form["id"].strip()
        fields = self._ec_build_fields()

        try:
            add_or_update(eid, fields)
            reload_registry()
            # Refresh the texture-status panel if it exists
            if hasattr(self, "_et_refresh"):
                self._et_refresh()
            if generate:
                self._ec_generate_textures(eid)
            self._ec_errors = []
            return True
        except Exception as exc:
            self._ec_errors = [f"Save failed: {exc}"]
            _log.exception("Entity save failed for %s", eid)
            return False

    def _ec_generate_textures(self, eid: str) -> None:
        """Generate template textures + reload atlas."""
        try:
            from core.paths import BILLBOARD_TEX_DIR, PRISM_TEX_DIR
            from gen_entity_textures import (
                generate_prism_textures,
                generate_billboard_textures,
            )

            edef = get_entity_def(eid)
            if not edef:
                return
            f = self._ec_form

            if edef.render_type == "prism":
                generate_prism_textures(edef, PRISM_TEX_DIR, force=True)
            elif edef.render_type in ("billboard", "8way"):
                n_f = 8 if edef.directional else 1
                generate_billboard_textures(
                    edef, BILLBOARD_TEX_DIR, n_facings=n_f,
                    cell_w=f["cell_w"], cell_h=f["cell_h"],
                    force=True,
                )

            # Reload atlas so new textures are immediately visible
            if hasattr(self, "_et_reload_atlas"):
                self._et_reload_atlas()
        except Exception as exc:
            self._ec_errors.append(f"Texture generation failed: {exc}")
            _log.exception("Texture generation failed for %s", eid)

    def _ec_delete(self) -> None:
        """Delete the currently-edited entity from the TOML."""
        eid = self._ec_form["id"].strip()
        try:
            remove_entity(eid)
            reload_registry()
            if hasattr(self, "_et_refresh"):
                self._et_refresh()
            self.show_entity_creator = False
        except Exception as exc:
            self._ec_errors = [f"Delete failed: {exc}"]

    # ── ImGui draw ────────────────────────────────────────────────

    def _draw_entity_creator(self) -> None:  # noqa: C901
        """Render the Entity Creator / Editor window."""
        win_w, win_h = self.win_size
        imgui.set_next_window_position(
            win_w / 2 - 260, win_h / 2 - 300, imgui.FIRST_USE_EVER)
        imgui.set_next_window_size(520, 600, imgui.FIRST_USE_EVER)

        title = "Edit Entity" if self._ec_mode == "edit" else "New Entity"
        expanded, opened = imgui.begin(f"{title}###entity_creator", True)
        if not opened:
            self.show_entity_creator = False
            imgui.end()
            return

        f = self._ec_form
        LABEL_W = 110  # Label column width

        # ── ID + Display Name ─────────────────────────────────────
        imgui.text("Entity ID")
        imgui.same_line(LABEL_W)
        imgui.push_item_width(150)
        if self._ec_mode == "edit":
            imgui.text_disabled(f["id"])
        else:
            _, f["id"] = imgui.input_text("##ec_id", f["id"], 64)
        imgui.pop_item_width()

        imgui.text("Display Name")
        imgui.same_line(LABEL_W)
        imgui.push_item_width(-1)
        _, f["display_name"] = imgui.input_text(
            "##ec_name", f["display_name"], 64)
        imgui.pop_item_width()

        # ── Category ──────────────────────────────────────────────
        imgui.text("Category")
        imgui.same_line(LABEL_W)
        imgui.push_item_width(150)
        cur_cat = _CATEGORIES.index(f["category"]) if f["category"] in _CATEGORIES else 0
        changed, new_idx = imgui.combo("##ec_cat", cur_cat, _CATEGORIES)
        if changed:
            f["category"] = _CATEGORIES[new_idx]
        imgui.pop_item_width()

        imgui.spacing()
        imgui.separator()

        # ── Render Type ───────────────────────────────────────────
        imgui.text_colored("Render Type", 0.6, 0.8, 1.0, 1.0)
        is_billboard = f["render_type"] in ("billboard", "8way")
        if imgui.radio_button("Billboard##ec_rt", is_billboard):
            f["render_type"] = "billboard"
        imgui.same_line(0, 30)
        if imgui.radio_button("Prism##ec_rt", not is_billboard):
            f["render_type"] = "prism"

        imgui.spacing()
        imgui.separator()

        # ── Appearance ────────────────────────────────────────────
        imgui.text_colored("Appearance", 0.6, 0.8, 1.0, 1.0)

        imgui.text("Color")
        imgui.same_line(LABEL_W)
        changed, new_col = imgui.color_edit3("##ec_color", *self._ec_col)
        if changed:
            self._ec_col = list(new_col)

        _, f["directional"] = imgui.checkbox("Directional##ec", f["directional"])
        imgui.same_line(0, 30)
        _, f["movable"] = imgui.checkbox("Movable##ec", f["movable"])

        imgui.spacing()
        imgui.separator()

        # ── Billboard Settings ────────────────────────────────────
        if f["render_type"] in ("billboard", "8way"):
            imgui.text_colored("Billboard Settings", 0.6, 0.8, 1.0, 1.0)

            imgui.text("Sprite Key")
            imgui.same_line(LABEL_W)
            imgui.push_item_width(150)
            _, f["sprite_key"] = imgui.input_text(
                "##ec_spkey", f["sprite_key"], 64)
            imgui.pop_item_width()
            imgui.same_line()
            hint_key = f["sprite_key"].strip() or f["id"].strip() or "???"
            imgui.text_disabled(f"(auto: {hint_key})")

            imgui.text("Cell Size")
            imgui.same_line(LABEL_W)
            imgui.push_item_width(60)
            _, f["cell_w"] = imgui.input_int("W##ec_cw", f["cell_w"], 0, 0)
            imgui.same_line()
            _, f["cell_h"] = imgui.input_int("H##ec_ch", f["cell_h"], 0, 0)
            imgui.pop_item_width()

            imgui.spacing()
            imgui.separator()

        # ── Prism Settings ────────────────────────────────────────
        if f["render_type"] == "prism":
            imgui.text_colored("Prism Geometry", 0.6, 0.8, 1.0, 1.0)

            imgui.push_item_width(100)
            imgui.text("Width")
            imgui.same_line(LABEL_W)
            _, f["width"] = imgui.input_float(
                "##ec_w", f["width"], 0.05, 0.1, "%.3f")

            imgui.text("Depth")
            imgui.same_line(LABEL_W)
            _, f["depth"] = imgui.input_float(
                "##ec_d", f["depth"], 0.05, 0.1, "%.3f")

            imgui.text("Height")
            imgui.same_line(LABEL_W)
            _, f["height"] = imgui.input_float(
                "##ec_h", f["height"], 0.05, 0.1, "%.3f")

            imgui.text("Elevation")
            imgui.same_line(LABEL_W)
            _, f["elevation"] = imgui.input_float(
                "##ec_e", f["elevation"], 0.05, 0.1, "%.3f")
            imgui.pop_item_width()

            _, f["shared_sides"] = imgui.checkbox(
                "Shared side texture (east = west)##ec", f["shared_sides"])

            imgui.spacing()
            imgui.separator()

        # ── Animation States ──────────────────────────────────────
        imgui.text_colored("Animation States", 0.6, 0.8, 1.0, 1.0)

        to_remove: int | None = None
        for i, state in enumerate(f["states"]):
            imgui.bullet_text(state)
            imgui.same_line()
            if imgui.small_button(f"X##ec_rm_{i}"):
                to_remove = i
        if to_remove is not None and len(f["states"]) > 1:
            f["states"].pop(to_remove)

        imgui.push_item_width(140)
        enter, self._ec_new_state = imgui.input_text(
            "##ec_newst", self._ec_new_state, 32,
            imgui.INPUT_TEXT_ENTER_RETURNS_TRUE)
        imgui.pop_item_width()
        imgui.same_line()
        add_clicked = imgui.small_button("Add State##ec")
        if enter or add_clicked:
            s = self._ec_new_state.strip().lower().replace(" ", "_")
            if s and s not in f["states"]:
                f["states"].append(s)
                self._ec_new_state = ""

        # ── Errors ────────────────────────────────────────────────
        if self._ec_errors:
            imgui.spacing()
            imgui.separator()
            for err in self._ec_errors:
                imgui.text_colored(err, 0.9, 0.3, 0.3, 1.0)

        # ── Action buttons ────────────────────────────────────────
        imgui.spacing()
        imgui.separator()
        btn_h = imgui.get_frame_height() + 4

        if imgui.button("Save & Generate", 150, btn_h):
            if self._ec_save(generate=True):
                self.show_entity_creator = False
        imgui.same_line()
        if imgui.button("Save Only", 100, btn_h):
            if self._ec_save(generate=False):
                self.show_entity_creator = False
        imgui.same_line()
        if imgui.button("Cancel", 80, btn_h):
            self.show_entity_creator = False

        # Delete (edit mode only)
        if self._ec_mode == "edit":
            imgui.same_line(0, 30)
            imgui.push_style_color(imgui.COLOR_BUTTON, 0.6, 0.15, 0.15, 1.0)
            imgui.push_style_color(
                imgui.COLOR_BUTTON_HOVERED, 0.8, 0.2, 0.2, 1.0)
            if not self._ec_confirm_delete:
                if imgui.button("Delete", 80, btn_h):
                    self._ec_confirm_delete = True
            else:
                if imgui.button("Confirm?", 80, btn_h):
                    self._ec_delete()
            imgui.pop_style_color(2)
            if self._ec_confirm_delete:
                imgui.same_line()
                imgui.text_colored(
                    "Click again to confirm", 0.9, 0.5, 0.2, 1.0)

        imgui.end()
