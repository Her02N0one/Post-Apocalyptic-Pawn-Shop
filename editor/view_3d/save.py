"""editor/view_3d/save.py — Zone binary serialization for Zone3DEditor."""

from __future__ import annotations

from typing import TYPE_CHECKING

import core.paths as _core_paths

if TYPE_CHECKING:
    from core.zones import GameRegistry


class SaveMixin:
    """Save zone data to binary .zone format."""

    # The owning ZoneEditorApp sets this before calling _save().
    _registry: "GameRegistry | None" = None

    def _save(self) -> None:
        if self._registry is None:
            raise RuntimeError(
                "SaveMixin._registry must be set before calling _save()")
        zone = self.zone
        path = _core_paths.ZONES_DIR / f"{zone.name}.zone"
        try:
            zone.save_to_file(path, self._registry)
        except Exception as exc:  # noqa: BLE001
            self._flash(f"Save failed: {exc}", 3.0, (1.0, 0.3, 0.3, 1.0))
            return
        self.dirty = False
        self._flash("Saved \u2713", 1.5, (0.5, 1.0, 0.6, 1.0))
