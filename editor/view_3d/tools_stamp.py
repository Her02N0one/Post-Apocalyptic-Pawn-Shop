"""editor/view_3d/tools_stamp.py — Stamp tool: apply cell presets (models)."""

from __future__ import annotations

from core.presets import (
    PRESET_REGISTRY, PRESET_CATEGORIES, APPLY_MODES,
    presets_by_category,
    apply_preset, capture_preset,
    register_preset, _next_preset_id,
)


class StampMixin:
    """Apply / capture cell presets ("models") in the 3D editor."""

    # Index into flattened preset list
    _stamp_idx: int = 0
    _stamp_preset_id: str = ""
    _stamp_mode_idx: int = 0          # index into APPLY_MODES

    # ── Capture state ─────────────────────────────────────────────
    _capture_pending: bool = False     # True while waiting for name
    _capture_name: str = ""            # text typed so far
    _capture_row: int = 0
    _capture_col: int = 0

    def _stamp_palette(self) -> list[str]:
        """Return a flat list of preset IDs (for scroll-cycling)."""
        return sorted(PRESET_REGISTRY.keys())

    def _stamp_current(self):
        """Return the currently selected CellPreset, or None."""
        pal = self._stamp_palette()
        if not pal:
            return None
        self._stamp_idx = self._stamp_idx % len(pal)
        self._stamp_preset_id = pal[self._stamp_idx]
        return PRESET_REGISTRY.get(self._stamp_preset_id)

    def _stamp_current_mode(self) -> str:
        """Return the currently selected apply mode string."""
        return APPLY_MODES[self._stamp_mode_idx % len(APPLY_MODES)]

    # ── Tool actions ──────────────────────────────────────────────

    def _stamp_apply(self) -> None:
        """LMB: Stamp the current preset onto the aimed cell."""
        if self._capture_pending:
            return  # ignore clicks while naming a capture
        hit = self.aimed
        if not hit:
            return
        preset = self._stamp_current()
        if preset is None:
            return
        self._push_undo()
        self._ensure_face_textures()
        apply_preset(
            self.zone, hit.row, hit.col, preset,
            wall_tile=self._wall_tile,
            open_tile=self._open_tile,
            mode_override=self._stamp_current_mode(),
        )
        self.dirty = True

    def _stamp_capture_begin(self) -> None:
        """RMB: Begin capturing — enter naming mode."""
        hit = self.aimed
        if not hit:
            return
        if self._capture_pending:
            return  # already in naming mode
        self._capture_pending = True
        self._capture_name = ""
        self._capture_row = hit.row
        self._capture_col = hit.col

    def _stamp_capture_key(self, key: int, unicode: str) -> bool:
        """Handle a keypress while in capture-naming mode.

        Returns True if the event was consumed.
        """
        import pygame
        if not self._capture_pending:
            return False

        if key == pygame.K_ESCAPE:
            self._capture_pending = False
            self._capture_name = ""
            return True

        if key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            name = self._capture_name.strip()
            if not name:
                # Empty name → cancel
                self._capture_pending = False
                self._capture_name = ""
                return True
            self._stamp_capture_commit(name)
            return True

        if key == pygame.K_BACKSPACE:
            self._capture_name = self._capture_name[:-1]
            return True

        # Printable character
        if unicode and unicode.isprintable():
            self._capture_name += unicode
            return True

        return False

    def _stamp_capture_commit(self, name: str) -> None:
        """Finalise capture with chosen name."""
        self._ensure_face_textures()
        pid = _next_preset_id(name)
        preset = capture_preset(
            self.zone,
            self._capture_row,
            self._capture_col,
            preset_id=pid,
            name=name,
            category="Custom",
            apply_mode=self._stamp_current_mode(),
        )
        register_preset(preset, save=True)
        # Switch to the newly captured preset
        pal = self._stamp_palette()
        if pid in pal:
            self._stamp_idx = pal.index(pid)
            self._stamp_preset_id = pid
        self._capture_pending = False
        self._capture_name = ""

    def _stamp_cycle(self, direction: int) -> None:
        """Scroll: cycle through preset palette."""
        if self._capture_pending:
            return
        pal = self._stamp_palette()
        if not pal:
            return
        self._stamp_idx = (self._stamp_idx + direction) % len(pal)
        self._stamp_preset_id = pal[self._stamp_idx]

    def _stamp_cycle_mode(self, direction: int = 1) -> None:
        """Cycle through apply modes (replace → stack_floor → …)."""
        self._stamp_mode_idx = (
            (self._stamp_mode_idx + direction) % len(APPLY_MODES)
        )
