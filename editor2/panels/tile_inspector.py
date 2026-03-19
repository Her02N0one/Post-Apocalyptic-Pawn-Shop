"""editor2/panels/tile_inspector.py — Tile type tool inspector panel."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QGroupBox, QTreeWidget, QTreeWidgetItem,
)

from core.tiles.registry import tiles_by_category, tile_def
from core.tiles.types import TileType
from editor2.tools.tile_type import TileTypeTool

# Short labels that explain what each type DOES
_TYPE_TAG = {
    TileType.FLOOR:     "floor",
    TileType.WALL:      "solid",
    TileType.HALF_WALL: "barrier",
    TileType.PLATFORM:  "platform",
    TileType.DOOR:      "door",
    TileType.LIQUID:    "liquid",
}


class TileTypeInspector(QWidget):
    """Dock panel showing tile palette grouped by category."""

    def __init__(self, tool: TileTypeTool,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tool = tool
        self._id_to_item: dict[str, QTreeWidgetItem] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # ── Info ──
        info_box = QGroupBox("Tile Type Tool")
        info_lay = QVBoxLayout(info_box)

        self._lbl_selected = QLabel()
        self._lbl_hover = QLabel("Hover: —")
        self._lbl_cell = QLabel("Cell: —")
        info_lay.addWidget(self._lbl_selected)
        info_lay.addWidget(self._lbl_hover)
        info_lay.addWidget(self._lbl_cell)
        layout.addWidget(info_box)

        # ── Palette (tree grouped by category) ──
        palette_box = QGroupBox("Tiles")
        palette_lay = QVBoxLayout(palette_box)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setIndentation(12)
        self._build_tree()

        self._tree.currentItemChanged.connect(self._on_select)
        palette_lay.addWidget(self._tree)
        layout.addWidget(palette_box)

        # ── Help ──
        help_lbl = QLabel(
            "Left-click: set tile type\n"
            "Middle-click: pick tile from cell\n"
            "Drag to paint area"
        )
        help_lbl.setWordWrap(True)
        layout.addWidget(help_lbl)

        self._update_selected_label()
        self._select_tree_item(tool.current_tile)

    def _build_tree(self) -> None:
        by_cat = tiles_by_category()
        for cat, defs in by_cat.items():
            cat_item = QTreeWidgetItem([cat])
            cat_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            for td in defs:
                tag = _TYPE_TAG.get(td.type, td.type.value)
                label = f"{td.name}  [{tag}]"
                child = QTreeWidgetItem([label])
                child.setData(0, Qt.ItemDataRole.UserRole, td.id)
                cat_item.addChild(child)
                self._id_to_item[td.id] = child
            self._tree.addTopLevelItem(cat_item)
            cat_item.setExpanded(True)

    def _select_tree_item(self, tile_id: str) -> None:
        """Select the tree item matching tile_id without triggering _on_select."""
        item = self._id_to_item.get(tile_id)
        if item:
            self._tree.blockSignals(True)
            self._tree.setCurrentItem(item)
            self._tree.blockSignals(False)

    def _update_selected_label(self) -> None:
        tid = self._tool.current_tile
        td = tile_def(tid)
        tag = _TYPE_TAG.get(td.type, td.type.value)
        self._lbl_selected.setText(f"Selected: {td.name}  [{tag}]")

    def _on_select(self, current: QTreeWidgetItem | None,
                   _prev: QTreeWidgetItem | None) -> None:
        if current is None:
            return
        tile_id = current.data(0, Qt.ItemDataRole.UserRole)
        if tile_id:
            self._tool.current_tile = tile_id
            self._update_selected_label()

    def refresh(self) -> None:
        """Update display from tool state."""
        self._update_selected_label()
        self._select_tree_item(self._tool.current_tile)

        hit = self._tool.hover_hit
        if hit:
            self._lbl_hover.setText(
                f"Hover: ({hit.row},{hit.col}) {hit.part}.{hit.face.name}")
            cell_id = self._tool._zone.tiles[hit.row][hit.col]
            td = tile_def(cell_id)
            tag = _TYPE_TAG.get(td.type, td.type.value)
            self._lbl_cell.setText(f"Cell: {td.name}  [{tag}]")
        else:
            self._lbl_hover.setText("Hover: —")
            self._lbl_cell.setText("Cell: —")

    def set_tool(self, tool: TileTypeTool) -> None:
        self._tool = tool
