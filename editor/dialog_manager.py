"""editor/dialog_manager.py — Centralised dialog state for the zone editor.

Replaces the 16 ``show_*`` / ``_show_*`` boolean flags scattered across
``ZoneEditorApp.__init__`` with a single :class:`DialogManager` that
tracks which dialogs are open.

A :class:`DialogPropertyBridge` mixin provides drop-in replacement
properties so that existing code (``self.show_new_zone = True``) keeps
working without modification.
"""

from __future__ import annotations


# ── Manager ───────────────────────────────────────────────────────

class DialogManager:
    """Centralised open/close tracking for every editor dialog.

    Dialogs are split into two categories that affect Escape-ordering
    and event blocking:

    * **floating** — non-modal utility windows (find/replace, viewers).
      Closed first by Escape.
    * **modal** — popups that block the main editor (new zone, save-as,
      resize, …).  Closed after floating windows by Escape.
    """

    FLOATING: frozenset[str] = frozenset({
        "find_replace_tex", "validate_zone",
        "entity_defs_viewer", "items_viewer",
        "loot_tables_viewer", "presets_viewer",
        "keybind_editor", "texture_browser",
        "entity_textures", "entity_creator",
    })

    MODAL: frozenset[str] = frozenset({
        "new_zone", "save_as", "unsaved_guard",
        "resize_zone", "zone_settings", "duplicate_zone",
        "export_image",
    })

    ALL: frozenset[str] = FLOATING | MODAL

    def __init__(self) -> None:
        self._open: set[str] = set()

    # ── Mutation ──────────────────────────────────────────────────

    def open(self, name: str) -> None:
        """Mark dialog *name* as open."""
        self._open.add(name)

    def close(self, name: str) -> None:
        """Mark dialog *name* as closed."""
        self._open.discard(name)

    # ── Query ─────────────────────────────────────────────────────

    def is_open(self, name: str) -> bool:
        return name in self._open

    def any_modal_open(self) -> bool:
        """True when at least one modal dialog is visible."""
        return bool(self._open & self.MODAL)

    def any_open(self) -> bool:
        """True when any dialog at all is visible."""
        return bool(self._open)

    @property
    def open_set(self) -> frozenset[str]:
        """Snapshot of currently open dialog names (for testing)."""
        return frozenset(self._open)

    # ── Escape ordering ───────────────────────────────────────────

    def close_any(self) -> bool:
        """Close the first open dialog using Escape priority order:
        floating windows first, then modals.  Returns ``True`` if a
        dialog was closed, ``False`` if nothing was open."""
        # Floating windows first (stable iteration order)
        for name in (
            "find_replace_tex", "validate_zone",
            "entity_defs_viewer", "items_viewer",
            "loot_tables_viewer", "presets_viewer",
            "keybind_editor", "texture_browser",
            "entity_textures", "entity_creator",
        ):
            if name in self._open:
                self._open.discard(name)
                return True
        # Then modals
        for name in (
            "resize_zone", "zone_settings", "duplicate_zone",
            "export_image", "save_as", "new_zone",
        ):
            if name in self._open:
                self._open.discard(name)
                return True
        return False


# ── Property bridge helper ────────────────────────────────────────

def _make_dialog_prop(dialog_name: str) -> property:
    """Create a ``property`` descriptor backed by :attr:`dialog_manager`."""

    def _getter(self):  # type: ignore[no-untyped-def]
        return self.dialog_manager.is_open(dialog_name)

    def _setter(self, val: bool):  # type: ignore[no-untyped-def]
        if val:
            self.dialog_manager.open(dialog_name)
        else:
            self.dialog_manager.close(dialog_name)

    return property(_getter, _setter)


class DialogPropertyBridge:
    """Mixin that exposes ``show_*`` properties backed by :class:`DialogManager`.

    Drop this into the ZoneEditorApp MRO *before* any mixin that writes
    ``self.show_new_zone = …`` so the property intercepts the attribute.
    """

    # ── Modal dialogs ─────────────────────────────────────────────
    show_new_zone       = _make_dialog_prop("new_zone")
    show_save_as        = _make_dialog_prop("save_as")
    _show_unsaved_guard = _make_dialog_prop("unsaved_guard")
    show_resize_zone    = _make_dialog_prop("resize_zone")
    show_zone_settings  = _make_dialog_prop("zone_settings")
    show_duplicate_zone = _make_dialog_prop("duplicate_zone")
    show_export_image   = _make_dialog_prop("export_image")

    # ── Floating windows ──────────────────────────────────────────
    show_keybind_editor      = _make_dialog_prop("keybind_editor")
    show_find_replace_tex    = _make_dialog_prop("find_replace_tex")
    show_validate_zone       = _make_dialog_prop("validate_zone")
    show_entity_defs_viewer  = _make_dialog_prop("entity_defs_viewer")
    show_items_viewer        = _make_dialog_prop("items_viewer")
    show_loot_tables_viewer  = _make_dialog_prop("loot_tables_viewer")
    show_presets_viewer       = _make_dialog_prop("presets_viewer")
    show_texture_browser     = _make_dialog_prop("texture_browser")
    show_entity_textures     = _make_dialog_prop("entity_textures")
    show_entity_creator      = _make_dialog_prop("entity_creator")
