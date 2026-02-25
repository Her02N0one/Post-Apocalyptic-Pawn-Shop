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
        zone.save_to_file(path, self._registry)
        self.dirty = False
