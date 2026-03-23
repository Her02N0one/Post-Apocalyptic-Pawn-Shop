"""editor2/panels/entity_inspector.py — Entity tool palette and inspector."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from core.entity_defs import entity_registry, get_entity_def


class EntityInspector(QWidget):
    """Left/right panel for the Entity tool.

    - Entity type palette (tree grouped by category)
    - Selected entity inspector (type, position, angle)
    """

    # Emitted after the user selects an entity type in the palette.
    # The parent window connects this to restore viewport focus.
    type_selected = Signal()

    def __init__(self, tool, parent=None) -> None:
        super().__init__(parent)
        self._tool = tool
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(6)

        # ── Entity palette ─────────────────────────────────────────
        lay.addWidget(QLabel("<b>Entity Palette</b>"))

        self._filter = QLineEdit()
        self._filter.setPlaceholderText("Filter entities...")
        self._filter.textChanged.connect(self._apply_filter)
        lay.addWidget(self._filter)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setRootIsDecorated(True)
        self._tree.currentItemChanged.connect(self._on_select)
        self._tree.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        lay.addWidget(self._tree, 3)

        self._populate_tree()

        # ── Selected entity info ────────────────────────────────────
        grp = QGroupBox("Selected Entity")
        grp_lay = QVBoxLayout(grp)
        grp_lay.setContentsMargins(4, 4, 4, 4)

        self._sel_type_label = QLabel("Type: —")
        self._sel_uid_label = QLabel("UID: —")
        grp_lay.addWidget(self._sel_type_label)
        grp_lay.addWidget(self._sel_uid_label)

        pos_row = QWidget()
        pos_lay = QHBoxLayout(pos_row)
        pos_lay.setContentsMargins(0, 0, 0, 0)
        pos_lay.addWidget(QLabel("X:"))
        self._pos_x = QLabel("—")
        pos_lay.addWidget(self._pos_x)
        pos_lay.addWidget(QLabel("Y:"))
        self._pos_y = QLabel("—")
        pos_lay.addWidget(self._pos_y)
        grp_lay.addWidget(pos_row)

        angle_row = QWidget()
        angle_lay = QHBoxLayout(angle_row)
        angle_lay.setContentsMargins(0, 0, 0, 0)
        angle_lay.addWidget(QLabel("Angle:"))
        self._angle_label = QLabel("—")
        angle_lay.addWidget(self._angle_label)
        grp_lay.addWidget(angle_row)

        lay.addWidget(grp)

        # ── Help text ────────────────────────────────────────────────
        help_lbl = QLabel(
            "<small>"
            "LMB: place / select entity<br>"
            "Shift+LMB: always place<br>"
            "X / Delete: delete selected<br>"
            "R: rotate selected 90°<br>"
            "Shift+Scroll: rotate 15° steps<br>"
            "M: move to cursor<br>"
            "[ / ]: prev / next entity type<br>"
            "F: quick search entities<br>"
            "S: cycle snap mode"
            "</small>"
        )
        help_lbl.setWordWrap(True)
        lay.addWidget(help_lbl)

        lay.addStretch()

    def set_tool(self, tool) -> None:
        self._tool = tool

    def _populate_tree(self, filter_text: str = "") -> None:
        self._tree.clear()
        reg = entity_registry()
        # Group by category
        cats: dict[str, list] = {}
        ft = filter_text.lower()
        for eid, edef in sorted(reg.items()):
            if ft and ft not in eid.lower() and ft not in edef.display_name.lower():
                continue
            cats.setdefault(edef.category, []).append(edef)

        for cat_name in sorted(cats):
            cat_item = QTreeWidgetItem(self._tree, [cat_name.title()])
            cat_item.setFlags(cat_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            font = cat_item.font(0)
            font.setBold(True)
            cat_item.setFont(0, font)
            cat_item.setExpanded(True)

            for edef in cats[cat_name]:
                child = QTreeWidgetItem(cat_item, [edef.display_name])
                child.setData(0, Qt.ItemDataRole.UserRole, edef.id)
                # Color swatch
                r, g, b = edef.color
                child.setForeground(0, QColor(r, g, b))

    def _apply_filter(self, text: str) -> None:
        self._populate_tree(text)

    def _on_select(self, current: QTreeWidgetItem | None,
                   previous: QTreeWidgetItem | None) -> None:
        if current is None:
            return
        eid = current.data(0, Qt.ItemDataRole.UserRole)
        if eid and self._tool:
            self._tool.current_type = eid
            self.type_selected.emit()

    def select_type_in_tree(self, etype: str) -> None:
        """Programmatically select an entity type in the tree.

        Called when the user cycles types via keyboard so the
        panel stays in sync without stealing focus.
        """
        self._tree.blockSignals(True)
        it = self._tree.invisibleRootItem()
        for ci in range(it.childCount()):
            cat = it.child(ci)
            for ei in range(cat.childCount()):
                child = cat.child(ei)
                if child.data(0, Qt.ItemDataRole.UserRole) == etype:
                    self._tree.setCurrentItem(child)
                    self._tree.scrollToItem(child)
                    self._tree.blockSignals(False)
                    return
        self._tree.blockSignals(False)

    def refresh(self) -> None:
        """Update the selected entity inspector from tool state."""
        if not self._tool:
            return
        uid = self._tool.selected_uid
        if uid is None:
            self._sel_type_label.setText("Type: —")
            self._sel_uid_label.setText("UID: —")
            self._pos_x.setText("—")
            self._pos_y.setText("—")
            self._angle_label.setText("—")
            return

        ent = self._tool._entity_by_uid(uid)
        if ent is None:
            self._sel_type_label.setText("Type: —")
            self._sel_uid_label.setText("UID: —")
            return

        import math
        self._sel_type_label.setText(f"Type: {ent.type}")
        self._sel_uid_label.setText(f"UID: {ent.uid}")
        self._pos_x.setText(f"{ent.x:.2f}")
        self._pos_y.setText(f"{ent.y:.2f}")
        self._angle_label.setText(f"{math.degrees(ent.angle):.1f}°")
