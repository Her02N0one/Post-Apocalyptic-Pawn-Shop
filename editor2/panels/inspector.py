"""editor2/panels/inspector.py — Paint tool inspector panel."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QGroupBox, QTreeWidget, QTreeWidgetItem,
)

from core.tiles.registry import tiles_by_type
from core.tiles.types import TileType
from editor2.atlas import TileAtlas
from editor2.tools.paint import PaintTool

# Group tile types into surface categories for the palette
_SURFACE_GROUPS: list[tuple[str, list[TileType]]] = [
    ("Floor",  [TileType.FLOOR, TileType.LIQUID]),
    ("Wall",   [TileType.WALL, TileType.HALF_WALL, TileType.DOOR]),
    ("Other",  [TileType.PLATFORM]),
]


class PaintInspector(QWidget):
    """Dock panel showing texture palette grouped by surface type.

    Organises textures into Floor / Wall / Other categories so the
    user can quickly find a texture suited for the surface they're
    painting.
    """

    def __init__(self, tool: PaintTool, atlas: TileAtlas,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tool = tool
        self._atlas = atlas
        self._key_to_item: dict[str, QTreeWidgetItem] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # ── Info ──────────────────────────────────────────────────
        info_box = QGroupBox("Paint Tool")
        info_lay = QVBoxLayout(info_box)

        self._lbl_texture = QLabel()
        self._lbl_hover = QLabel("Hover: —")
        info_lay.addWidget(self._lbl_texture)
        info_lay.addWidget(self._lbl_hover)
        layout.addWidget(info_box)

        # ── Palette (tree grouped by surface type) ────────────────
        palette_box = QGroupBox("Textures")
        palette_lay = QVBoxLayout(palette_box)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setIndentation(12)
        self._build_tree()
        self._tree.currentItemChanged.connect(self._on_select)
        palette_lay.addWidget(self._tree)
        layout.addWidget(palette_box)

        # ── Help ──────────────────────────────────────────────────
        help_lbl = QLabel(
            "Left-click: paint face\n"
            "Shift+click: paint all faces\n"
            "Ctrl+click: flood fill\n"
            "Middle-click: pick texture"
        )
        help_lbl.setWordWrap(True)
        layout.addWidget(help_lbl)

        self._update_label()
        self._select_item(tool.current_texture)

    # ── Tree construction ─────────────────────────────────────────

    def _build_tree(self) -> None:
        by_type = tiles_by_type()
        used_keys: set[str] = set()

        for group_name, types in _SURFACE_GROUPS:
            group_item = QTreeWidgetItem([group_name])
            group_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            for tt in types:
                for td in by_type.get(tt, []):
                    child = QTreeWidgetItem([td.name])
                    child.setData(0, Qt.ItemDataRole.UserRole, td.id)
                    group_item.addChild(child)
                    self._key_to_item[td.id] = child
                    used_keys.add(td.id)
            if group_item.childCount():
                self._tree.addTopLevelItem(group_item)
                group_item.setExpanded(True)

        # Extra textures: PNGs on disk that aren't in the tile registry
        extra_keys = [k for k in self._atlas.keys if k not in used_keys]
        if extra_keys:
            extra_item = QTreeWidgetItem(["Extra"])
            extra_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            for key in sorted(extra_keys):
                child = QTreeWidgetItem([key])
                child.setData(0, Qt.ItemDataRole.UserRole, key)
                extra_item.addChild(child)
                self._key_to_item[key] = child
            self._tree.addTopLevelItem(extra_item)
            extra_item.setExpanded(True)

    # ── Selection helpers ─────────────────────────────────────────

    def _select_item(self, tex_key: str) -> None:
        item = self._key_to_item.get(tex_key)
        if item:
            self._tree.blockSignals(True)
            self._tree.setCurrentItem(item)
            self._tree.blockSignals(False)

    def _update_label(self) -> None:
        self._lbl_texture.setText(f"Texture: {self._tool.current_texture}")

    def _on_select(self, current: QTreeWidgetItem | None,
                   _prev: QTreeWidgetItem | None) -> None:
        if current is None:
            return
        key = current.data(0, Qt.ItemDataRole.UserRole)
        if key:
            self._tool.current_texture = key
            self._update_label()

    # ── Refresh / tool swap ───────────────────────────────────────

    def refresh(self) -> None:
        """Called after zone_changed or tool state change to update UI."""
        self._update_label()
        self._select_item(self._tool.current_texture)
        hit = self._tool.hover_hit
        if hit:
            self._lbl_hover.setText(
                f"Hover: ({hit.row},{hit.col}) {hit.part}.{hit.face.name}")
        else:
            self._lbl_hover.setText("Hover: —")

    def set_tool(self, tool: PaintTool) -> None:
        """Swap the underlying tool (e.g. after zone switch)."""
        self._tool = tool
        self.refresh()
